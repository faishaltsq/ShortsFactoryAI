"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type HistoryEntry } from "@/lib/api";
import { useStudio } from "@/lib/useStudio";
import { ErrorState } from "@/components/states";
import { FieldRow, NumberInput, Section, Toast } from "@/components/studio";
import { AgentInspector } from "@/components/pixel/AgentInspector";
import { LiveOffice } from "@/components/pixel/LiveOffice";

export default function StudioPage() {
  const s = useStudio();
  const [models, setModels] = useState<string[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [rollbackName, setRollbackName] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getModels()
      .then((r) => {
        if (!alive) return;
        setModels(r.models);
        setModelsError(r.error);
      })
      .catch(() => alive && setModelsError("Gagal memuat daftar model"));
    return () => {
      alive = false;
    };
  }, []);

  const reloadHistory = () => {
    void api
      .listHistory()
      .then(setHistory)
      .catch(() => setHistory([]));
  };

  useEffect(reloadHistory, [s.savedAt]);

  if (s.loading) return <SkeletonRows label="Memuat konfigurasi studio…" />;
  if (s.error) return <ErrorState title="Konfigurasi tidak bisa dimuat" message={s.error} onRetry={s.load} />;

  const eff = s.effective ?? { budget: {}, production: {} };

  return (
    <div className="space-y-8">
      <header className="px-page-header">
        <div>
          <p className="px-eyebrow">KANTOR KREATIF</p>
          <h1 className="text-2xl font-semibold tracking-tight">Studio</h1>
          <p className="text-sm text-zinc-400">
            Konfigurasi orchestrator. Tersimpan di{" "}
            <code className="text-zinc-300">{s.meta?.studio_path}</code>
            {s.meta?.studio_exists ? "" : " (belum ada — akan dibuat saat simpan pertama)"}.
          </p>
          <p className="text-xs text-zinc-500">
            Nilai efektif aktif: budget token {eff.budget.max_daily_tokens} · cost $
            {eff.budget.max_daily_cost_usd} · fps {eff.production.fps} · TTS {eff.production.tts_voice} (
            {eff.production.tts_rate})
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {s.dirty && <span className="text-xs font-medium text-amber-400">Belum tersimpan</span>}
          {s.savedAt && !s.dirty && <span className="text-xs text-zinc-500">Tersimpan {s.savedAt}</span>}
          <button
            onClick={() => void s.save()}
            disabled={!s.dirty || s.saving || rollbackName !== null}
            className="px-button"
            data-primary="true"
          >
            {s.saving ? "Menyimpan…" : "Simpan perubahan"}
          </button>
        </div>
      </header>

      <LiveOffice
        meta={s.meta}
        renderInspector={(member, state) => (
          <AgentInspector
            member={member}
            state={state}
            studio={s}
            models={models}
            modelsError={modelsError}
          />
        )}
      />

      <Section
        title="Budget harian"
        description="Guard sebelum panggilan model. Melebihi → job jadi BLOCKED, bukan gagal."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <NumberInput
            label="Token harian"
            value={s.draft.budget.max_daily_tokens ?? ""}
            placeholder={String(eff.budget.max_daily_tokens)}
            error={s.errorFor("budget", "max_daily_tokens")}
            onChange={(v) => s.patchSection("budget", "max_daily_tokens", v)}
          />
          <NumberInput
            label="Biaya harian (USD)"
            step={0.1}
            value={s.draft.budget.max_daily_cost_usd ?? ""}
            placeholder={String(eff.budget.max_daily_cost_usd)}
            error={s.errorFor("budget", "max_daily_cost_usd")}
            onChange={(v) => s.patchSection("budget", "max_daily_cost_usd", v)}
          />
          <NumberInput
            label="Maksimal retry"
            value={s.draft.budget.max_retries ?? ""}
            placeholder={String(eff.budget.max_retries)}
            error={s.errorFor("budget", "max_retries")}
            onChange={(v) => s.patchSection("budget", "max_retries", v)}
          />
        </div>
      </Section>

      <Section title="Produksi" description="Default render & narasi untuk job baru.">
        <div className="grid gap-4 md:grid-cols-3">
          <NumberInput
            label="Target durasi (detik)"
            value={s.draft.production.target_duration_s ?? ""}
            placeholder={String(eff.production.target_duration_s)}
            error={s.errorFor("production", "target_duration_s")}
            onChange={(v) => s.patchSection("production", "target_duration_s", v)}
          />
          <NumberInput
            label="Video per hari"
            value={s.draft.production.videos_per_day ?? ""}
            placeholder={String(eff.production.videos_per_day)}
            error={s.errorFor("production", "videos_per_day")}
            onChange={(v) => s.patchSection("production", "videos_per_day", v)}
          />
          <NumberInput
            label="FPS"
            value={s.draft.production.fps ?? ""}
            placeholder={String(eff.production.fps)}
            error={s.errorFor("production", "fps")}
            onChange={(v) => s.patchSection("production", "fps", v)}
          />
          <FieldRow
            label="Suara TTS"
            hint="id-ID-ArdiNeural / id-ID-GadisNeural"
            error={s.errorFor("production", "tts_voice")}
          >
            <input
              list="tts-voices"
              value={s.draft.production.tts_voice ?? ""}
              onChange={(e) => s.patchText("production", "tts_voice", e.target.value)}
              placeholder={String(eff.production.tts_voice)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
            <datalist id="tts-voices">
              <option value="id-ID-ArdiNeural" />
              <option value="id-ID-GadisNeural" />
            </datalist>
          </FieldRow>
          <FieldRow label="Rate TTS" hint="Format +0% atau -10%" error={s.errorFor("production", "tts_rate")}>
            <input
              value={s.draft.production.tts_rate ?? ""}
              onChange={(e) => s.patchText("production", "tts_rate", e.target.value)}
              placeholder={String(eff.production.tts_rate)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
          </FieldRow>
        </div>
      </Section>

      <Section title="Runner" description="Default yang dipakai tombol Buat job di halaman Jobs.">
        <div className="grid gap-4 md:grid-cols-2">
          <FieldRow label="Mode default">
            <select
              value={s.draft.runner.default_mode}
              onChange={(e) => s.patchRunner("default_mode", e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            >
              <option value="mock">mock (tanpa biaya, fixture)</option>
              <option value="live">live (model asli, ada biaya)</option>
            </select>
          </FieldRow>
          <FieldRow label="Berhenti di stage">
            <select
              value={s.draft.runner.default_stop}
              onChange={(e) => s.patchRunner("default_stop", e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            >
              {(s.meta?.runner_stops ?? []).map((stop) => (
                <option key={stop} value={stop}>
                  {stop}
                </option>
              ))}
            </select>
          </FieldRow>
        </div>
      </Section>

      <section className="px-frame">
        <h2 className="text-lg font-medium">Riwayat konfigurasi</h2>
        <p className="mb-4 mt-1 text-sm text-zinc-400">
          Versi dibuat saat Simpan perubahan ditekan. Kembalikan versi tersimpan bila diperlukan.
        </p>
        {history.length === 0 ? (
          <p className="text-sm text-zinc-500">Belum ada perubahan tersimpan.</p>
        ) : (
          <ul className="space-y-2">
            {history.map((entry) => (
              <li
                key={entry.name}
                className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-700 py-3 text-sm"
              >
                <span className="font-mono text-xs text-zinc-400">
                  {entry.name} · {new Date(entry.mtime * 1000).toLocaleString("id-ID")}
                </span>
                <button
                  onClick={async () => {
                    if (rollbackName) return;
                    if (
                      s.dirty &&
                      !window.confirm("Buang perubahan yang belum tersimpan dan kembalikan versi ini?")
                    ) {
                      return;
                    }
                    setRollbackName(entry.name);
                    try {
                      const res = await api.rollback(entry.name);
                      s.acceptSaved(res.restored, res.effective);
                      s.setToast({ kind: "ok", text: `Konfigurasi dikembalikan ke ${entry.name}` });
                      reloadHistory();
                    } catch (err) {
                      s.setToast({
                        kind: "error",
                        text: err instanceof ApiError ? err.message : "Gagal mengembalikan versi",
                      });
                    } finally {
                      setRollbackName(null);
                    }
                  }}
                  disabled={rollbackName !== null || s.saving}
                  className="rounded-md border border-zinc-700 px-3 py-1 text-xs hover:bg-zinc-800 disabled:opacity-50"
                >
                  {rollbackName === entry.name ? "Mengembalikan…" : "Kembalikan"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Toast toast={s.toast} onClose={() => s.setToast(null)} />
    </div>
  );
}

function SkeletonRows({ label }: { label: string }) {
  return (
    <div className="animate-pulse space-y-3" role="status" aria-live="polite">
      <p className="text-sm text-zinc-500">{label}</p>
      <div className="h-24 rounded-lg bg-zinc-900" />
      <div className="h-24 rounded-lg bg-zinc-900" />
    </div>
  );
}
