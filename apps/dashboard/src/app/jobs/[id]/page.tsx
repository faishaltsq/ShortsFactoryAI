"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type JobDetail } from "@/lib/api";
import { ErrorState, StateChip } from "@/components/states";

const PIPELINE = [
  "IDEA_DISCOVERY",
  "TOPIC_SELECTED",
  "SCRIPT_GENERATED",
  "CREATIVE_REVIEW",
  "STORYBOARD_READY",
  "ASSETS_READY",
  "AUDIO_READY",
  "RENDERING",
  "TECHNICAL_QC",
  "EDITORIAL_QC",
  "READY_FOR_APPROVAL",
];

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [artifact, setArtifact] = useState<{ name: string; body: unknown } | null>(null);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [mode, setMode] = useState("mock");
  const [stop, setStop] = useState("storyboard");

  const load = useCallback(async () => {
    try {
      setData(await api.getJob(id));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat job");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const isRunning = Boolean(data?.run.running);
  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [isRunning, load]);

  const openArtifact = async (name: string) => {
    try {
      setArtifact({ name, body: await api.getArtifact(id, name) });
    } catch (err) {
      setArtifact({ name, body: { error: err instanceof ApiError ? err.message : "gagal memuat" } });
    }
  };

  const startRun = async () => {
    setStarting(true);
    try {
      await api.runJob(id, { mode, stop });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal menjalankan");
    } finally {
      setStarting(false);
    }
  };

  const cancelRun = async () => {
    setCancelling(true);
    try {
      await api.cancelJob(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal membatalkan");
    } finally {
      setCancelling(false);
    }
  };

  if (error && !data) return <ErrorState title="Job tidak bisa dimuat" message={error} onRetry={load} />;
  if (!data)
    return (
      <p className="text-sm text-zinc-500" role="status">
        Memuat job…
      </p>
    );

  const current = PIPELINE.indexOf(data.record.state);
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link href="/jobs" className="text-xs text-zinc-500 hover:text-zinc-300">
            ← Semua job
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{data.record.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-zinc-400">
            <StateChip state={data.record.state} />
            <span>id {data.record.id}</span>
            <span>mode {String(data.record.payload.provider_mode ?? mode)}</span>
            {isRunning && <span className="animate-pulse text-amber-400">berjalan…</span>}
          </p>
          {data.record.last_error && (
            <p className="mt-2 max-w-3xl rounded-md border border-rose-900 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
              {data.record.last_error}
            </p>
          )}
        </div>
        <div className="flex items-end gap-2">
          <label className="block space-y-1">
            <span className="text-xs text-zinc-500">Mode</span>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
            >
              <option value="mock">mock</option>
              <option value="live">live</option>
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-zinc-500">Berhenti di</span>
            <select
              value={stop}
              onChange={(e) => setStop(e.target.value)}
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
            >
              {["research", "script", "creative", "storyboard", "audio", "render"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => void startRun()}
            disabled={starting || isRunning}
            className="rounded-md bg-sky-500 px-4 py-2 text-sm font-medium text-white hover:bg-sky-400 disabled:bg-zinc-700 disabled:text-zinc-400"
          >
            {starting || isRunning ? "Berjalan…" : "Jalankan / lanjutkan"}
          </button>
          {isRunning && (
            <button
              onClick={() => void cancelRun()}
              disabled={cancelling}
              className="rounded-md border border-rose-700 px-4 py-2 text-sm text-rose-300 hover:bg-rose-950 disabled:opacity-50"
            >
              {cancelling ? "Membatalkan…" : "Batalkan run"}
            </button>
          )}
        </div>
      </header>

      {data.run.error && <ErrorState title="Run terakhir gagal" message={data.run.error} onRetry={() => void startRun()} />}

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="mb-4 text-lg font-medium">Tahap pipeline</h2>
        <ol className="flex flex-wrap gap-2">
          {PIPELINE.map((stage, index) => {
            const done = current > -1 && index < current;
            const now = stage === data.record.state;
            return (
              <li
                key={stage}
                className={`rounded-md border px-3 py-1.5 text-xs ${
                  now
                    ? "border-sky-600 bg-sky-950 text-sky-200"
                    : done
                      ? "border-emerald-800 bg-emerald-950/60 text-emerald-300"
                      : "border-zinc-800 text-zinc-500"
                }`}
              >
                {done ? "✓ " : ""}
                {stage}
              </li>
            );
          })}
        </ol>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="mb-4 text-lg font-medium">Artifact</h2>
        {data.artifacts.length === 0 && (
          <p className="text-sm text-zinc-500">Belum ada artifact. Jalankan job untuk menghasilkannya.</p>
        )}
        <div className="flex flex-wrap gap-2">
          {data.artifacts.map((name) => (
            <button
              key={name}
              onClick={() => void openArtifact(name)}
              className="rounded-md border border-zinc-700 px-3 py-1.5 font-mono text-xs hover:bg-zinc-800"
            >
              {name}
            </button>
          ))}
        </div>
        {artifact && (
          <pre className="mt-4 max-h-96 overflow-auto rounded-md border border-zinc-800 bg-zinc-950 p-4 text-xs text-zinc-300">
            {JSON.stringify(artifact.body, null, 2)}
          </pre>
        )}
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="mb-4 text-lg font-medium">Riwayat event</h2>
        <ol className="space-y-2 text-sm">
          {data.events.length === 0 && <p className="text-sm text-zinc-500">Belum ada event.</p>}
          {data.events.map((event, index) => (
            <li key={index} className="flex flex-wrap gap-3 border-b border-zinc-900 pb-2 text-zinc-300">
              <span className="w-44 shrink-0 text-xs text-zinc-500">{event.created_at}</span>
              <span className="text-xs text-zinc-500">
                {event.from_state ?? "—"} → {event.to_state}
              </span>
              <span className="text-xs text-zinc-400">{event.detail}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
