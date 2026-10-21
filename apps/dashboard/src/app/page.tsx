"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type JobRow, type UsageResponse } from "@/lib/api";
import { EmptyState, ErrorState, StateChip } from "@/components/states";

export default function OverviewPage() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [jobsRes, usageRes] = await Promise.all([api.listJobs(), api.usage()]);
      setJobs(jobsRes.jobs);
      setRunning(jobsRes.running);
      setUsage(usageRes);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat ringkasan");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="text-sm text-zinc-500" role="status">Memuat ringkasan…</p>;
  if (error) return <ErrorState title="Ringkasan tidak bisa dimuat" message={error} onRetry={load} />;

  const today = new Date().toISOString().slice(0, 10);
  const todayCount = jobs.filter((j) => j.updated_at.startsWith(today)).length;
  const runningCount = Object.values(running).filter(Boolean).length;
  const tokenPct = usage && usage.budget.max_daily_tokens ? (usage.tokens / usage.budget.max_daily_tokens) * 100 : 0;
  const costPct = usage && usage.budget.max_daily_cost_usd ? (usage.cost / usage.budget.max_daily_cost_usd) * 100 : 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="text-sm text-zinc-400">Ringkasan produksi hari ini. Semua angka dari DB lokal.</p>
      </header>

      {(tokenPct >= 90 || costPct >= 90) && (
        <p className="rounded-md border border-amber-800 bg-amber-950/50 px-3 py-2 text-sm text-amber-200">
          Hampir mencapai budget harian; run berikutnya akan jadi BLOCKED.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <Card label="Job hari ini" value={String(todayCount)} />
        <Card label="Sedang berjalan" value={String(runningCount)} />
        <Card
          label="Token hari ini"
          value={`${Math.round(usage?.tokens ?? 0)} / ${usage?.budget.max_daily_tokens ?? "-"}`}
          pct={tokenPct}
        />
        <Card
          label="Biaya hari ini"
          value={`$${(usage?.cost ?? 0).toFixed(4)} / $${usage?.budget.max_daily_cost_usd ?? "-"}`}
          pct={costPct}
        />
      </div>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-medium">Job terbaru</h2>
          <Link href="/jobs" className="text-xs text-sky-400 hover:text-sky-300">
            Lihat semua →
          </Link>
        </div>
        {jobs.length === 0 ? (
          <EmptyState
            title="Belum ada job"
            description="Buat job pertama dari halaman Jobs. Mode mock tidak memakai biaya."
            action={
              <Link href="/jobs" className="rounded-md bg-sky-500 px-3 py-1.5 text-sm font-medium text-white">
                Buka Jobs
              </Link>
            }
          />
        ) : (
          <ul className="space-y-2">
            {jobs.slice(0, 5).map((job) => (
              <li key={job.id} className="flex items-center justify-between border-b border-zinc-900 pb-2 text-sm">
                <Link href={`/jobs/${job.id}`} className="max-w-[520px] truncate hover:text-sky-300">
                  {job.title}
                </Link>
                <span className="flex items-center gap-3 text-xs text-zinc-500">
                  <StateChip state={job.state} />
                  {job.updated_at}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Card({ label, value, pct }: { label: string; value: string; pct?: number }) {
  const tone = pct === undefined ? "" : pct >= 100 ? "bg-rose-500" : pct >= 80 ? "bg-amber-500" : "bg-sky-500";
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-2 text-xl font-semibold">{value}</p>
      {pct !== undefined && (
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
          <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
        </div>
      )}
    </div>
  );
}
