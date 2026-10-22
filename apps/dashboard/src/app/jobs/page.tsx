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

  const load = useCallback(async (quiet = false) => {
    // Polling biasa tidak boleh mengosongkan kartu yang sudah tampil.
    if (!quiet) setLoading(true);
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
    const timer = setInterval(() => void load(true), 2500);
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
      <header className="px-page-header">
        <div>
          <p className="px-eyebrow">ANTREAN PRODUKSI</p>
          <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
          <p className="text-sm text-zinc-400">
            Antrean produksi. Mode & stage berhenti mengikuti setelan Studio.
          </p>
        </div>
        <div className="px-create-job">
          <label className="block space-y-1">
            <span className="text-xs text-zinc-500">Judul video</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Judul minimal 3 karakter"
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
          </label>
          <button
            onClick={() => void create()}
            disabled={creating}
            className="px-button"
            data-primary="true"
          >
            {creating ? "Membuat…" : "Buat job"}
          </button>
        </div>
      </header>

      {notice && (
        <p role="status" className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-300">{notice}</p>
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
      {error && <ErrorState title="Daftar job tidak bisa dimuat" message={error} onRetry={() => void load()} />}

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
        <ul className="px-job-list" aria-label="Antrean produksi">
          {jobs.map((job) => (
            <li key={job.id} className="px-frame px-job-card">
              <div>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <StateChip state={job.state} />
                  {running[job.id] && <span className="px-chip">Run terpantau</span>}
                </div>
                <h2>{job.title}</h2>
                {job.last_error && <p className="mt-2 text-sm text-rose-300">{job.last_error}</p>}
                <dl className="mt-3">
                  <div>
                    <dt className="sr-only">ID</dt>
                    <dd>{job.id}</dd>
                  </div>
                  <div>
                    <dt className="inline">Upaya: </dt>
                    <dd className="inline">{job.attempts}</dd>
                  </div>
                  <div>
                    <dt className="inline">Diperbarui: </dt>
                    <dd className="inline">{job.updated_at}</dd>
                  </div>
                </dl>
              </div>
              <Link href={`/jobs/${job.id}`} className="px-button">
                Buka
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md border px-3 py-1 text-xs transition ${
        active ? "border-sky-600 bg-sky-950 text-sky-200" : "border-zinc-700 text-zinc-400 hover:bg-zinc-900"
      }`}
    >
      {label}
    </button>
  );
}
