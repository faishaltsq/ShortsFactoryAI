"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type ProductionStatus, type ScheduleEntry, type ScheduleProjection } from "@/lib/api";
import { ErrorState, StateChip } from "@/components/states";

const STATUS_LABELS: ProductionStatus[] = ["ON GOING", "RESEARCHING", "UPCOMING", "SELESAI", "GAGAL", "TERTAHAN"];
const STATUS_STYLE: Record<ProductionStatus, string> = {
  "ON GOING": "border-sky-800 bg-sky-950/50 text-sky-200",
  RESEARCHING: "border-violet-800 bg-violet-950/50 text-violet-200",
  UPCOMING: "border-amber-800 bg-amber-950/50 text-amber-200",
  SELESAI: "border-emerald-800 bg-emerald-950/50 text-emerald-200",
  GAGAL: "border-rose-800 bg-rose-950/50 text-rose-200",
  TERTAHAN: "border-zinc-700 bg-zinc-900 text-zinc-300",
};

export default function SchedulePage() {
  const [projection, setProjection] = useState<ScheduleProjection | null>(null);
  const [filter, setFilter] = useState<ProductionStatus | "ALL">("ALL");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setProjection(await api.scheduleProjection());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat proyeksi produksi.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !projection) return <p className="text-sm text-zinc-500" role="status">Memuat jadwal produksi…</p>;
  if (error && !projection) return <ErrorState title="Jadwal tidak bisa dimuat" message={error} onRetry={() => void load()} />;

  const entries = projection?.entries.filter((entry) => filter === "ALL" || entry.status === filter) ?? [];
  const counts = projection?.counts;

  return (
    <div className="space-y-6">
      <header className="px-page-header">
        <div>
          <p className="px-eyebrow">PROYEKSI PERSISTEN</p>
          <h1 className="text-2xl font-semibold tracking-tight">Production schedule</h1>
          <p className="mt-1 max-w-3xl text-sm text-zinc-400">
            Tampilan baca-saja dari state job, event tersimpan, dan slot produksi. Halaman ini tidak membuat atau menjalankan job.
          </p>
          {projection && <p className="mt-1 text-xs text-zinc-500">Diperbarui {formatDate(projection.generated_at)}</p>}
        </div>
        <button type="button" className="px-button" onClick={() => void load()} disabled={loading}>
          {loading ? "Memuat…" : "Muat ulang"}
        </button>
      </header>

      {error && <p className="px-stale" role="status">{error} · Menampilkan data terakhir yang berhasil dimuat.</p>}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Jumlah job per status">
        <button
          type="button"
          aria-pressed={filter === "ALL"}
          onClick={() => setFilter("ALL")}
          className="px-frame text-left"
        >
          <p className="text-xs uppercase tracking-wide text-zinc-500">Semua</p>
          <p className="mt-2 text-xl font-semibold">{projection?.total ?? 0}</p>
        </button>
        {STATUS_LABELS.map((status) => (
          <button
            type="button"
            key={status}
            aria-pressed={filter === status}
            onClick={() => setFilter(status)}
            className="px-frame text-left"
          >
            <p className="text-xs uppercase tracking-wide text-zinc-500">{status}</p>
            <p className="mt-2 text-xl font-semibold">{counts?.[status] ?? 0}</p>
          </button>
        ))}
      </section>

      <section className="px-frame" aria-label="Daftar jadwal produksi">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-medium">Job produksi <span className="text-sm text-zinc-500">({entries.length})</span></h2>
          <label className="flex items-center gap-2 text-xs text-zinc-400">
            Filter status
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value as ProductionStatus | "ALL")}
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200"
              aria-label="Filter status jadwal"
            >
              <option value="ALL">Semua status</option>
              {STATUS_LABELS.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
        </div>

        {entries.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">
            {projection?.total ? "Tidak ada job pada status ini." : "Belum ada job produksi tersimpan."}
          </p>
        ) : (
          <ul className="space-y-3">
            {entries.map((entry) => <ScheduleCard key={entry.job_id} entry={entry} />)}
          </ul>
        )}
      </section>
    </div>
  );
}

function ScheduleCard({ entry }: { entry: ScheduleEntry }) {
  return (
    <li data-testid={`schedule-row-${entry.job_id}`} data-status={entry.status} className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/jobs/${entry.job_id}`} className="break-words font-medium hover:text-sky-300">
            {entry.title}
          </Link>
          <p className="mt-1 font-mono text-xs text-zinc-500">{entry.job_id} · {entry.stage_label} · {entry.state}</p>
        </div>
        <span className={`rounded-md border px-2 py-1 text-xs font-medium ${STATUS_STYLE[entry.status]}`}>
          {entry.status}
        </span>
      </div>

      <div className="mt-4">
        <div className="mb-1 flex justify-between text-xs text-zinc-400">
          <span>{entry.next_action}</span>
          <span>{Math.min(100, Math.max(0, entry.progress))}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800" aria-label={`Progres ${entry.progress}%`}>
          <div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.min(100, Math.max(0, entry.progress))}%` }} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-zinc-400">
        {entry.genre && <span>Genre: {entry.genre}</span>}
        {entry.content_type && <span>Tipe: {entry.content_type}</span>}
        <span>{entry.scene_count} scene</span>
        {entry.duration_ms !== null && <span>{(entry.duration_ms / 1000).toFixed(1)} dtk</span>}
        <span>Verifikasi: {entry.verification}</span>
        {entry.sources > 0 && <span>{entry.sources} sumber</span>}
        {entry.due_at && <span>Jatuh tempo: {formatDate(entry.due_at)}</span>}
        <span>Sumber data: {entry.source}</span>
        {entry.approval_required && <span className="text-amber-300">Menunggu keputusan operator</span>}
      </div>
      {entry.templates.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Template storyboard">
          {entry.templates.map((template) => <span key={template} className="px-chip">{template}</span>)}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800 pt-3">
        <StateChip state={entry.state} />
        <span className="text-xs text-zinc-500">Diperbarui {formatDate(entry.updated_at)}</span>
      </div>
    </li>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}
