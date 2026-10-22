"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  parseFieldErrors,
  type EditableProvider,
  type FieldError,
  type ProvidersResponse,
  type StudioPayload,
} from "@/lib/api";
import { ErrorState } from "@/components/states";
import { FieldRow, Toast } from "@/components/studio";

type ProviderKey = "worker" | "strategist_cli" | "strategist_http";
type ProviderDraft = {
  enabled?: boolean | null;
  base_url?: string | null;
  model?: string | null;
  temperature?: number | null;
};
type Draft = Record<ProviderKey, ProviderDraft>;

const PROVIDER_LABEL: Record<ProviderKey, string> = {
  worker: "Worker (HTTP)",
  strategist_cli: "Strategist (CLI)",
  strategist_http: "Strategist (HTTP)",
};

const PROVIDER_ROLE: Record<ProviderKey, string> = {
  worker: "Menjalankan research, script, dan storyboard. Dipakai paling sering.",
  strategist_cli: "Review kreatif lewat Claude CLI. Tidak butuh API key.",
  strategist_http: "Cadangan strategist saat CLI mati. Endpoint OpenAI-compatible.",
};

export default function ProvidersPage() {
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [draft, setDraft] = useState<Draft>({ worker: {}, strategist_cli: {}, strategist_http: {} });
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [modelsError, setModelsError] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [providers, catalog] = await Promise.all([
        api.providers(),
        api.providerModels("worker").catch(() => null),
      ]);
      setData(providers);
      setDraft(toDraft(providers));
      setDirty(false);
      if (catalog) {
        setModels((prev) => ({ ...prev, worker: catalog.models }));
        setModelsError((prev) => ({ ...prev, worker: catalog.error }));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memeriksa provider");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!data?.editable) return;
    setDirty(JSON.stringify(draft) !== JSON.stringify(toDraft(data)));
  }, [draft, data]);

  const patch = useCallback((key: ProviderKey, field: string, value: unknown) => {
    setDraft((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));
  }, []);

  const loadModels = useCallback(async (target: "worker" | "strategist_http") => {
    try {
      const res = await api.providerModels(target);
      setModels((prev) => ({ ...prev, [target]: res.models }));
      setModelsError((prev) => ({ ...prev, [target]: res.error }));
    } catch {
      setModelsError((prev) => ({ ...prev, [target]: "Gagal memuat katalog model" }));
    }
  }, []);

  const save = useCallback(async () => {
    if (!data) return;
    setSaving(true);
    setFieldErrors([]);
    setToast(null);
    try {
      // Endpoint simpan menulis seluruh dokumen studio, jadi setelan lain harus
      // dibaca ulang dulu supaya perubahan di halaman Studio tidak tertimpa.
      const current = await api.getStudio();
      const payload: StudioPayload = { ...current.saved, providers: draft };
      await api.putStudio(payload);
      const fresh = await api.providers();
      setData(fresh);
      setDraft(toDraft(fresh));
      setDirty(false);
      setToast({
        kind: "ok",
        text: "Setelan provider tersimpan. Run berikutnya memakai konfigurasi ini.",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFieldErrors(parseFieldErrors(err.detail));
      }
      setToast({ kind: "error", text: err instanceof ApiError ? err.message : "Gagal menyimpan" });
    } finally {
      setSaving(false);
    }
  }, [data, draft]);

  const errorFor = useCallback(
    (provider: ProviderKey, field: string) => {
      const target = `providers.${provider}.${field}`;
      return (
        fieldErrors.find((f) => {
          const path = f.loc[0] === "body" ? f.loc.slice(1) : f.loc;
          return path.join(".") === target;
        })?.msg ?? null
      );
    },
    [fieldErrors],
  );

  const healthByRef = useMemo(() => {
    const map: Record<string, boolean> = {};
    for (const item of data?.health ?? []) map[item.ref] = item.healthy;
    return map;
  }, [data]);

  return (
    <div className="space-y-6">
      <header className="px-page-header">
        <div>
          <p className="px-eyebrow">RUANG MESIN</p>
          <h1 className="text-2xl font-semibold tracking-tight">Providers</h1>
          <p className="text-sm text-zinc-400">
            Atur endpoint dan model tiap provider. API key tetap di{" "}
            <code className="text-zinc-300">.env</code> — tidak pernah ditampilkan atau disimpan
            lewat halaman ini.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {dirty && <span className="text-xs font-medium text-amber-400">Belum tersimpan</span>}
          <button onClick={() => void load()} disabled={loading || saving} className="px-button">
            {loading ? "Memeriksa…" : "Periksa ulang"}
          </button>
          <button
            onClick={() => void save()}
            disabled={!dirty || saving}
            className="px-button"
            data-primary="true"
          >
            {saving ? "Menyimpan…" : "Simpan"}
          </button>
        </div>
      </header>

      {error && (
        <ErrorState title="Provider tidak bisa diperiksa" message={error} onRetry={() => void load()} />
      )}

      {loading && !data && (
        <p className="text-sm text-zinc-500" role="status">
          Memeriksa provider…
        </p>
      )}

      {data && (
        <>
          <section className="grid gap-4 md:grid-cols-2" aria-label="Rak provider">
            {data.health.map((item) => (
              <div key={item.ref} className="px-frame px-service">
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-sm">{item.ref}</p>
                  <p className="text-xs text-zinc-500">model {item.model}</p>
                </div>
                <span className="px-status" data-kind={item.healthy ? "done" : "failed"}>
                  {item.healthy ? "sehat" : "tidak sehat"}
                </span>
              </div>
            ))}
          </section>

          {data.editable ? (
            <section className="space-y-4" aria-label="Setelan provider">
              <ProviderCard
                name="worker"
                editable={data.editable.worker}
                draft={draft.worker ?? {}}
                healthy={healthByRef["worker:deepseek"]}
                models={models.worker ?? []}
                modelsError={modelsError.worker ?? null}
                onReloadModels={() => void loadModels("worker")}
                onChange={patch}
                errorFor={errorFor}
              />
              <ProviderCard
                name="strategist_cli"
                editable={data.editable.strategist_cli}
                draft={draft.strategist_cli ?? {}}
                healthy={healthByRef["strategist:claude-cli"]}
                onChange={patch}
                errorFor={errorFor}
              />
              <ProviderCard
                name="strategist_http"
                editable={data.editable.strategist_http}
                draft={draft.strategist_http ?? {}}
                healthy={healthByRef["strategist:strategist-http"]}
                models={models.strategist_http ?? []}
                modelsError={modelsError.strategist_http ?? null}
                onReloadModels={() => void loadModels("strategist_http")}
                onChange={patch}
                errorFor={errorFor}
              />
            </section>
          ) : (
            <section className="px-frame text-sm text-zinc-400">
              API ini belum mendukung pengaturan provider dari web. Perbarui API untuk
              mengaktifkannya.
            </section>
          )}

          <section className="px-frame text-sm text-zinc-300">
            <h2 className="mb-2 text-lg font-medium">Nilai efektif</h2>
            <p className="text-zinc-400">
              Worker base URL: {String(data.mode.worker_base_url ?? "belum dikonfigurasi")}
            </p>
            <p className="text-zinc-400">Worker configured: {String(data.mode.worker_configured)}</p>
            <p className="text-zinc-400">Strategist model: {String(data.mode.strategist_model)}</p>
          </section>
        </>
      )}

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function ProviderCard({
  name,
  editable,
  draft,
  healthy,
  models,
  modelsError,
  onReloadModels,
  onChange,
  errorFor,
}: {
  name: ProviderKey;
  editable: EditableProvider;
  draft: NonNullable<Draft[ProviderKey]>;
  healthy?: boolean;
  models?: string[];
  modelsError?: string | null;
  onReloadModels?: () => void;
  onChange: (key: ProviderKey, field: string, value: unknown) => void;
  errorFor: (provider: ProviderKey, field: string) => string | null;
}) {
  const isCli = name === "strategist_cli";
  const listId = `models-${name}`;

  return (
    <div className="px-frame space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">{PROVIDER_LABEL[name]}</h2>
          <p className="text-sm text-zinc-400">{PROVIDER_ROLE[name]}</p>
        </div>
        <div className="flex items-center gap-3">
          {typeof healthy === "boolean" && (
            <span className="px-status" data-kind={healthy ? "done" : "failed"}>
              {healthy ? "sehat" : "tidak sehat"}
            </span>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.enabled !== false}
              onChange={(e) => onChange(name, "enabled", e.target.checked)}
              className="h-4 w-4 rounded border-zinc-600 bg-zinc-900 accent-sky-500"
            />
            <span className="text-zinc-200">Aktif</span>
          </label>
        </div>
      </div>

      {!isCli && (
        <FieldRow
          label="Base URL"
          hint={`Aktif: ${editable.effective_base_url ?? "belum dikonfigurasi"}`}
          error={errorFor(name, "base_url")}
        >
          <input
            value={draft.base_url ?? ""}
            onChange={(e) => onChange(name, "base_url", e.target.value || null)}
            placeholder={editable.effective_base_url ?? "https://api.example.com/v1"}
            spellCheck={false}
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-sm outline-none focus:border-sky-500"
          />
        </FieldRow>
      )}

      <FieldRow
        label="Model"
        hint={
          isCli
            ? `Aktif: ${editable.effective_model ?? "-"}`
            : `Aktif: ${editable.effective_model ?? "belum dikonfigurasi"}${
                editable.has_key === false ? " · tanpa API key" : ""
              }`
        }
        error={errorFor(name, "model")}
      >
        <div className="flex gap-2">
          <input
            list={isCli ? undefined : listId}
            value={draft.model ?? ""}
            onChange={(e) => onChange(name, "model", e.target.value || null)}
            placeholder={editable.effective_model ?? "nama model"}
            spellCheck={false}
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-sm outline-none focus:border-sky-500"
          />
          {!isCli && onReloadModels && (
            <button
              type="button"
              onClick={onReloadModels}
              className="shrink-0 rounded-md border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-800"
            >
              Muat model
            </button>
          )}
        </div>
        {!isCli && (
          <datalist id={listId}>
            {models?.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        )}
      </FieldRow>

      {!isCli && (
        <FieldRow label="Temperature default" hint="Dipakai bila agent tidak punya nilai sendiri">
          <input
            type="number"
            step={0.05}
            min={0}
            max={2}
            value={draft.temperature ?? ""}
            onChange={(e) =>
              onChange(name, "temperature", e.target.value === "" ? null : Number(e.target.value))
            }
            placeholder="0.7"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
        </FieldRow>
      )}

      {isCli && (
        <p className="text-xs text-zinc-500">
          Binary: <code className="text-zinc-300">{editable.binary ?? "claude"}</code>. Model di sini
          harus tersedia di CLI tersebut.
        </p>
      )}

      {editable.key_origin_mismatch && (
        <p
          className="rounded-md border border-amber-700 bg-amber-950 px-3 py-2 text-xs text-amber-100"
          role="alert"
        >
          Base URL ini beda origin dengan yang terdaftar di <code>.env</code>, jadi API key sengaja
          tidak dikirim. Katalog model tetap terbaca (tidak butuh auth) tapi panggilan akan gagal
          401. Pakai host yang persis sama dengan <code>.env</code>, mis.{" "}
          <code>http://localhost:20128/v1</code> — bukan <code>127.0.0.1</code>.
        </p>
      )}

      {modelsError && <p className="text-xs text-amber-400">Katalog model tidak tersedia: {modelsError}</p>}
    </div>
  );
}

function toDraft(data: ProvidersResponse): Draft {
  const editable = data.editable;
  if (!editable) return { worker: {}, strategist_cli: {}, strategist_http: {} };
  const pick = (p: EditableProvider) => ({
    enabled: p.enabled ?? null,
    base_url: p.base_url ?? null,
    model: p.model ?? null,
    temperature: p.temperature ?? null,
  });
  return {
    worker: pick(editable.worker),
    strategist_cli: {
      enabled: editable.strategist_cli.enabled ?? null,
      model: editable.strategist_cli.model ?? null,
    },
    strategist_http: pick(editable.strategist_http),
  };
}
