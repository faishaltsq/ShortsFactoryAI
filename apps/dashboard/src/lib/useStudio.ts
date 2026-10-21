"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  parseFieldErrors,
  type EffectiveConfig,
  type FieldError,
  type StudioPayload,
  type StudioResponse,
} from "./api";

const EMPTY: StudioPayload = {
  version: 1,
  agents: {},
  budget: {},
  production: {},
  runner: { default_mode: "mock", default_stop: "storyboard" },
};

export type SectionKey = "budget" | "production";
export type AgentKey = keyof NonNullable<StudioPayload["agents"][string]>;

export function useStudio() {
  const [meta, setMeta] = useState<StudioResponse | null>(null);
  const [draft, setDraft] = useState<StudioPayload>(EMPTY);
  const [effective, setEffective] = useState<EffectiveConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getStudio();
      setMeta(data);
      setDraft(data.saved);
      setEffective(data.effective);
      setDirty(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat konfigurasi");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!meta) return;
    setDirty(JSON.stringify(draft) !== JSON.stringify(meta.saved));
  }, [draft, meta]);

  const patchAgent = useCallback((agent: string, key: AgentKey, value: unknown) => {
    setDraft((prev) => ({
      ...prev,
      agents: { ...prev.agents, [agent]: { ...prev.agents[agent], [key]: value } },
    }));
  }, []);

  const patchSection = useCallback((section: SectionKey, key: string, value: number | null) => {
    setDraft((prev) => ({ ...prev, [section]: { ...prev[section], [key]: value } }));
  }, []);

  const patchText = useCallback((section: SectionKey, key: string, value: string) => {
    setDraft((prev) => ({ ...prev, [section]: { ...prev[section], [key]: value } }));
  }, []);

  const patchRunner = useCallback((key: "default_mode" | "default_stop", value: string) => {
    setDraft((prev) => ({
      ...prev,
      runner: { ...prev.runner, [key]: value as StudioPayload["runner"]["default_mode"] },
    }));
  }, []);

  const resetAgentPrompt = useCallback((agent: string) => patchAgent(agent, "prompt", null), [patchAgent]);

  const save = useCallback(async () => {
    setSaving(true);
    setFieldErrors([]);
    setToast(null);
    try {
      const res = await api.putStudio(draft);
      setMeta((prev) => (prev ? { ...prev, saved: res.saved, effective: res.effective } : prev));
      setEffective(res.effective);
      setDraft(res.saved);
      setSavedAt(new Date().toLocaleTimeString("id-ID"));
      setToast({ kind: "ok", text: "Konfigurasi tersimpan dan langsung dipakai run berikutnya." });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        // Ambil detail per-field supaya input bisa menandai errornya sendiri.
        const res = await fetch("/api/studio", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        const detail = (await res.json()).detail;
        setFieldErrors(parseFieldErrors(detail));
      }
      setToast({ kind: "error", text: err instanceof ApiError ? err.message : "Gagal menyimpan" });
    } finally {
      setSaving(false);
    }
  }, [draft]);

  const errorFor = useCallback(
    (...loc: string[]) =>
      fieldErrors.find((f) => f.loc.slice(2).join(".") === loc.join("."))?.msg ?? null,
    [fieldErrors],
  );

  const agents = useMemo(() => meta?.agent_keys ?? [], [meta]);

  return {
    meta,
    draft,
    effective,
    loading,
    error,
    dirty,
    saving,
    savedAt,
    toast,
    setToast,
    save,
    load,
    patchAgent,
    patchSection,
    patchText,
    patchRunner,
    resetAgentPrompt,
    errorFor,
    agents,
    setDraft,
    setSavedAt,
  };
}
