"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type JobDetail, type StudioResponse } from "@/lib/api";
import { ErrorState, StateChip } from "@/components/states";
import { agentStatus, roster } from "@/lib/team";
import { PixelAvatar } from "@/components/pixel/PixelAvatar";
import { ApprovalControls } from "@/components/ApprovalControls";

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
  const [stop, setStop] = useState("storyboard");
  const [meta, setMeta] = useState<StudioResponse | null>(null);
  // Satu sumber kebenaran: daftar stop berasal dari API, bukan salinan lokal.
  // Selama /api/studio belum termuat (atau gagal), satu pilihan aman ditampilkan.
  const stops = meta?.runner_stops?.length ? meta.runner_stops : ["storyboard"];
  const selectedStop = stops.includes(stop) ? stop : stops[0];

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

  // Roster hanya identitas tampilan; kalau gagal, data job tetap terbaca.
  useEffect(() => {
    let alive = true;
    api
      .getStudio()
      .then((value) => {
        if (alive) setMeta(value);
      })
      .catch(() => {
        if (alive) setMeta(null);
      });
    return () => {
      alive = false;
    };
  }, []);

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
      // Mode tidak dikirim: server memakai mode yang terkunci pada job ini.
      await api.runJob(id, { stop: selectedStop });
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

  if (error && !data) return <ErrorState title="Job tidak bisa dimuat" message={error} onRetry={() => void load()} />;
  if (!data)
    return (
      <p className="text-sm text-zinc-500" role="status">
        Memuat job…
      </p>
    );

  const observed = new Set([data.record.state, ...data.events.map((event) => event.to_state)]);
  return (
    <div className="space-y-6">
      <header className="px-page-header">
        <div>
          <Link href="/jobs" className="text-xs text-zinc-500 hover:text-zinc-300">
            ← Semua job
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{data.record.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-zinc-400">
            <StateChip state={data.record.state} />
            <span>id {data.record.id}</span>
            <span>mode {String(data.record.payload.provider_mode ?? "belum diset")}</span>
            {isRunning && <span className="text-amber-400">berjalan…</span>}
          </p>
          {data.record.last_error && (
            <p className="mt-2 max-w-3xl rounded-md border border-rose-900 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
              {data.record.last_error}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="block space-y-1">
            <span className="text-xs text-zinc-500">Mode</span>
            {/* Mode terkunci sejak job dibuat: mencampur mock dan live dalam
                satu job menghasilkan artifact separuh palsu. */}
            <p
              className="rounded-md border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-400"
              title="Mode terkunci sejak job dibuat. Buat job baru untuk mengganti mode."
            >
              {String(data.record.payload.provider_mode ?? "belum diset")}
            </p>
          </div>
          <label className="block space-y-1">
            <span className="text-xs text-zinc-500">Berhenti di</span>
            <select
              value={selectedStop}
              onChange={(e) => setStop(e.target.value)}
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
            >
              {stops.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => void startRun()}
            disabled={starting || isRunning}
            className="px-button"
            data-primary="true"
          >
            {starting || isRunning ? "Berjalan…" : "Jalankan / lanjutkan"}
          </button>
          {isRunning && (
            <button
              onClick={() => void cancelRun()}
              disabled={cancelling}
              className="px-button border-rose-700 text-rose-300"
            >
              {cancelling ? "Membatalkan…" : "Batalkan run"}
            </button>
          )}
        </div>
      </header>

      {data.run.error && <ErrorState title="Run terakhir gagal" message={data.run.error} onRetry={() => void startRun()} />}

      <ApprovalControls jobId={id} state={data.record.state} onDecision={() => void load()} />

      {error && (
        <div className="px-stale" role="status">
          <p>{error}</p>
          <button className="px-button" onClick={() => void load()}>
            Coba lagi aktivitas
          </button>
        </div>
      )}

      <section className="px-frame" aria-label="Tim pada job ini" data-motion="paused">
        <h2 className="mb-4 text-lg font-medium">Tim pada job ini</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {roster(meta).map((member) => {
            const state = agentStatus(member.id, data, Boolean(error), member.available);
            return (
              <div key={member.id} className="flex min-w-0 items-center gap-3">
                <PixelAvatar member={member} kind={state.kind} size={48} />
                <div className="min-w-0">
                  <p className="font-semibold">{member.persona}</p>
                  <p className="text-xs text-zinc-400">{member.role}</p>
                  <span className="px-status" data-kind={state.kind}>
                    {state.label}
                  </span>
                </div>
              </div>
            );
          })}
          {!meta && (
            <p className="text-sm text-zinc-400">
              Profil tim belum tersedia; data job tetap dapat dibaca.
            </p>
          )}
        </div>
      </section>

      <section className="px-frame">
        <h2 className="mb-4 text-lg font-medium">Tahap pipeline</h2>
        <ol className="px-timeline" aria-label="Tahap tersimpan">
          {PIPELINE.map((stage) => {
            const now = stage === data.record.state;
            return (
              <li key={stage} data-current={now} aria-current={now ? "step" : undefined}>
                <span className="px-chip">{stage}</span>
                <span className="text-xs text-zinc-400">
                  {now ? "State tersimpan" : observed.has(stage) ? "Pernah tercatat" : "Belum tercatat"}
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="px-frame">
        <h2 className="mb-4 text-lg font-medium">Artifact</h2>
        {data.artifacts.length === 0 && (
          <p className="text-sm text-zinc-500">Belum ada artifact. Jalankan job untuk menghasilkannya.</p>
        )}
        <div className="flex flex-wrap gap-2">
          {data.artifacts.map((name) => (
            <button
              key={name}
              onClick={() => void openArtifact(name)}
              aria-pressed={artifact?.name === name}
              className="rounded-md border border-zinc-700 px-3 py-1.5 font-mono text-xs hover:bg-zinc-800"
            >
              {name}
            </button>
          ))}
        </div>
        {artifact && (
          <pre
            role="region"
            aria-label="Isi artifact"
            tabIndex={0}
            className="mt-4 max-h-96 max-w-full overflow-auto border border-zinc-700 bg-zinc-950 p-4 text-xs text-zinc-300"
          >
            {JSON.stringify(artifact.body, null, 2)}
          </pre>
        )}
      </section>

      <section className="px-frame">
        <h2 className="mb-4 text-lg font-medium">Riwayat event</h2>
        <ol className="space-y-2 text-sm">
          {data.events.length === 0 && <li className="text-sm text-zinc-400">Belum ada event.</li>}
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
