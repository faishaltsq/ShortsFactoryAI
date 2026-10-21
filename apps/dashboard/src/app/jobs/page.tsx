"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type JobRow } from "@/lib/api";
import { EmptyState, ErrorState, StateChip } from "@/components/states";

export default function JobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [states, setStates] = useState<string[]>([]);
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listJobs(filter || undefined);
      setJobs(data.jobs);
      setStates(data.states);
      setRunning(data.running);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat jobs");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  // Polling hanya saat ada job yang berjalan; berhenti otomatis saat tidak ada.
  const anyRunning = Object.values(running).some(Boolean);
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => void load(), 2500);
    return () => clearInterval(timer);
  }, [anyRunning, load]);

  const create = async () => {
    if (title.trim().length < 3) {
      setNotice("Judul minimal 3 karakter");
      return;
    }
    setCreating(true);
    setNotice(null);
    try {
      const res = await api.createJob({ title: title.trim() });
      setTitle("");
      setNotice(`Job ${res.job_id} dibuat dan mulai berjalan (mode ${res.mode}, berhenti di ${res.stop}).`);
      router.push(`/jobs/${res.job_id}`);
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Gagal membuat job");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="text-sm text-zinc-400">
            Antrean produksi. Mode & stage berhenti mengikuti setelan Studio.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="block space-y-1">
            <span className="text-xs text-zinc-500">Judul video</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Judul minimal 3 karakter"
              className="w-72 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
          </label>
          <button
            onClick={() => void create()}
            disabled={creating}
            className="rounded-md bg-sky-500 px-4 py-2 text-sm font-medium text-white hover:bg-sky-400 disabled:bg-zinc-700 disabled:text-zinc-400"
          >
            {creating ? "Membuat…" : "Buat job"}
          </button>
        </div>
      </header>

      {notice && (
        <p className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-300">{notice}</p>
      )}

      <div className="flex flex-wrap gap-2">
        <FilterChip label="Semua" active={filter === ""} onClick={() => setFilter("")} />
        {states
          .filter((s) => ["READY_FOR_APPROVAL", "FAILED", "BLOCKED", "TECHNICAL_QC"].includes(s))
          .map((s) => (
            <FilterChip key={s} label={s} active={filter === s} onClick={() => setFilter(s)} />
          ))}
      </div>

      {loading && (
        <p className="text-sm text-zinc-500" role="status">
          Memuat jobs…
        </p>
      )}
      {error && <ErrorState title="Daftar job tidak bisa dimuat" message={error} onRetry={load} />}

      {!loading && !error && jobs.length === 0 && (
        <EmptyState
          title={filter ? "Tidak ada job dengan filter ini" : "Belum ada job sama sekali"}
          description={
            filter
              ? "Ubah filter atau lihat semua job."
              : "Buat job pertama dari kolom di atas; mode mock tidak memakai biaya."
          }
          action={
            filter ? (
              <button onClick={() => setFilter("")} className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm">
                Lihat semua
              </button>
            ) : undefined
          }
        />
      )}

      {!loading && !error && jobs.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wide text-zinc-500">
              <th className="py-2">Judul</th>
              <th>State</th>
              <th>Upaya</th>
              <th>Diperbarui</th>
              <th className="text-right">Detail</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-zinc-900 hover:bg-zinc-900/60">
                <td className="max-w-[380px] truncate py-3 pr-4">
                  {job.title}
                  {running[job.id] && <span className="ml-2 animate-pulse text-xs text-amber-400">berjalan…</span>}
                  {job.last_error && <span className="block truncate text-xs text-rose-400">{job.last_error}</span>}
                </td>
                <td className="py-3 pr-4">
                  <StateChip state={job.state} />
                </td>
                <td className="py-3 pr-4 text-zinc-400">{job.attempts}</td>
                <td className="py-3 pr-4 text-zinc-400">{job.updated_at}</td>
                <td className="py-3 text-right">
                  <Link
                    href={`/jobs/${job.id}`}
                    className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs hover:bg-zinc-800"
                  >
                    Buka
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs transition ${
        active ? "border-sky-600 bg-sky-950 text-sky-200" : "border-zinc-700 text-zinc-400 hover:bg-zinc-900"
      }`}
    >
      {label}
    </button>
  );
}
