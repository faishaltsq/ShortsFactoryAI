"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type HistoryEntry, type ScheduleStatus } from "@/lib/api";
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
  const [scheduleStatus, setScheduleStatus] = useState<ScheduleStatus | null>(null);
  const [scheduleBusy, setScheduleBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .schedule()
      .then((r) => alive && setScheduleStatus(r))
      .catch(() => alive && setScheduleStatus(null));
    return () => {
      alive = false;
    };
  }, [s.savedAt]);

  const runTick = async () => {
    setScheduleBusy(true);
    try {
      const plan = await api.scheduleTick();
      s.setToast({
        kind: plan.due ? "ok" : "error",
        text: plan.due
          ? `Jatuh tempo — job dibuat${plan.title ? `: ${plan.title}` : ""}`
          : `Belum waktunya: ${plan.reason}`,
      });
      setScheduleStatus(await api.schedule());
    } catch (err) {
      s.setToast({
        kind: "error",
        text: err instanceof ApiError ? err.message : "Gagal memeriksa jadwal",
      });
    } finally {
      setScheduleBusy(false);
    }
  };

  const applySchedule = async () => {
    setScheduleBusy(true);
    try {
      // Apply membaca konfigurasi yang tersimpan, bukan isian form. Kalau
      // draft masih kotor, simpan dulu supaya centang tidak terasa diabaikan.
      if (s.dirty) {
        const saved = await api.putStudio(s.draft);
        s.acceptSaved(saved.saved, saved.effective);
      }
      const next = await api.scheduleApply();
      setScheduleStatus(next);
      s.setToast({
        kind: "ok",
        text: next.running ? "Setelan tersimpan dan scheduler aktif." : "Setelan tersimpan, scheduler mati.",
      });
    } catch (err) {
      s.setToast({
        kind: "error",
        text: err instanceof ApiError ? err.message : "Gagal menerapkan jadwal",
      });
    } finally {
      setScheduleBusy(false);
    }
  };

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
        <label className="mb-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={s.draft.budget.unlimited === true}
            onChange={(e) => s.patchSection("budget", "unlimited", e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-zinc-600 bg-zinc-900 accent-sky-500"
          />
          <span>
            <span className="font-medium text-zinc-200">Tanpa batas</span>
            <span className="block text-xs text-zinc-400">
              Mematikan batas token dan biaya sekaligus. Angka di bawah diabaikan selama ini aktif.
            </span>
          </span>
        </label>
        <div className="grid gap-4 md:grid-cols-3">
          <NumberInput
            label="Token harian"
            value={s.draft.budget.max_daily_tokens ?? ""}
            placeholder={String(eff.budget.max_daily_tokens ?? "tanpa batas")}
            error={s.errorFor("budget", "max_daily_tokens")}
            onChange={(v) => s.patchSection("budget", "max_daily_tokens", v)}
          />
          <NumberInput
            label="Biaya harian (USD)"
            step={0.1}
            value={s.draft.budget.max_daily_cost_usd ?? ""}
            placeholder={String(eff.budget.max_daily_cost_usd ?? "tanpa batas")}
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

      <Section
        title="Jadwal otomatis"
        description="Buat video sendiri secara berkala. Mati secara default — nyalakan hanya kalau kamu siap menerima job tanpa menekan tombol."
      >
        <label className="mb-4 flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={s.draft.schedule?.enabled === true}
            onChange={(e) => s.patchSection("schedule", "enabled", e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-zinc-600 bg-zinc-900 accent-sky-500"
          />
          <span>
            <span className="font-medium text-zinc-200">Aktifkan scheduler</span>
            <span className="block text-xs text-zinc-400">
              Berjalan selama API hidup. Satu job pada satu waktu, dan judul yang sudah dipakai
              tidak diulang.
            </span>
          </span>
        </label>

        <div className="grid gap-4 md:grid-cols-3">
          <NumberInput
            label="Interval (jam)"
            value={s.draft.schedule?.interval_hours ?? ""}
            placeholder="24"
            error={s.errorFor("schedule", "interval_hours")}
            onChange={(v) => s.patchSection("schedule", "interval_hours", v)}
          />
          <NumberInput
            label="Maksimal per hari"
            value={s.draft.schedule?.max_per_day ?? ""}
            placeholder="1"
            error={s.errorFor("schedule", "max_per_day")}
            onChange={(v) => s.patchSection("schedule", "max_per_day", v)}
          />
          <NumberInput
            label="Jeda antar-job (menit)"
            value={s.draft.schedule?.gap_minutes ?? ""}
            placeholder="0"
            error={s.errorFor("schedule", "gap_minutes")}
            onChange={(v) => s.patchSection("schedule", "gap_minutes", v)}
          />
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <FieldRow label="Mode job otomatis">
            <select
              value={s.draft.schedule?.mode ?? "live"}
              onChange={(e) => s.patchSection("schedule", "mode", e.target.value)}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            >
              <option value="live">live (model asli, ada biaya)</option>
              <option value="mock">mock (tanpa biaya, fixture)</option>
            </select>
          </FieldRow>
          <FieldRow label="Berhenti di stage">
            <select
              value={s.draft.schedule?.stop ?? "render"}
              onChange={(e) => s.patchSection("schedule", "stop", e.target.value)}
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

        <div className="mt-4">
          <FieldRow
            label="Daftar topik"
            hint="Satu topik per baris. Diputar bergantian; yang sudah dipakai dilewati."
            error={s.errorFor("schedule", "topics")}
          >
            <textarea
              rows={5}
              value={(s.draft.schedule?.topics ?? []).join("\n")}
              onChange={(e) =>
                s.patchSection(
                  "schedule",
                  "topics",
                  e.target.value
                    .split("\n")
                    .map((t) => t.trim())
                    .filter(Boolean),
                )
              }
              placeholder={"Lubang hitam terdekat dari Bumi\nSinyal radio yang berulang tiap 16 hari"}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-sm outline-none focus:border-sky-500"
            />
          </FieldRow>
        </div>

        <ScheduleStatusPanel
          status={scheduleStatus}
          onTick={runTick}
          onApply={applySchedule}
          busy={scheduleBusy}
          dirty={s.dirty}
        />
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

function ScheduleStatusPanel({
  status,
  onTick,
  onApply,
  busy,
  dirty,
}: {
  status: ScheduleStatus | null;
  onTick: () => void;
  onApply: () => void;
  busy: boolean;
  dirty: boolean;
}) {
  return (
    <div className="mt-6 rounded-md border border-zinc-700 bg-zinc-950 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className="px-status"
            data-kind={status?.running ? "done" : "failed"}
          >
            {status?.running ? "berjalan" : "berhenti"}
          </span>
          <span className="text-sm text-zinc-300">
            {status?.last_plan
              ? status.last_plan.due
                ? `Terakhir: job dibuat${status.last_plan.title ? ` (${status.last_plan.title})` : ""}`
                : `Menunggu: ${status.last_plan.reason}`
              : "Belum ada pemeriksaan."}
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onTick}
            disabled={busy || !status?.running}
            className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
          >
            Periksa sekarang
          </button>
          <button
            type="button"
            onClick={onApply}
            disabled={busy}
            className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
          >
            Terapkan setelan
          </button>
        </div>
      </div>
      {dirty && (
        <p className="mt-3 text-xs text-amber-400">
          Simpan perubahan dulu, lalu tekan Terapkan setelan agar scheduler memakai nilai baru.
        </p>
      )}
      {status?.last_error && (
        <p className="mt-3 text-xs text-red-400" role="alert">
          {status.last_error}
        </p>
      )}
      {status && status.created.length > 0 && (
        <p className="mt-3 text-xs text-zinc-500">
          Job otomatis terakhir: <code className="text-zinc-400">{status.created.slice(-3).join(", ")}</code>
        </p>
      )}
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
