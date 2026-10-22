"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type StudioResponse, type UsageResponse } from "@/lib/api";
import { EmptyState, ErrorState } from "@/components/states";
import { roster } from "@/lib/team";
import { PixelAvatar } from "@/components/pixel/PixelAvatar";

export default function UsagePage() {
  const [data, setData] = useState<UsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<StudioResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Roster yang gagal dimuat tidak boleh menyembunyikan angka pemakaian.
      const [usage, studio] = await Promise.all([api.usage(), api.getStudio().catch(() => null)]);
      setData(usage);
      setMeta(studio);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memuat pemakaian");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="text-sm text-zinc-500" role="status">Memuat pemakaian…</p>;
  if (error) return <ErrorState title="Pemakaian tidak bisa dimuat" message={error} onRetry={() => void load()} />;
  if (!data) return null;

  const tokenPct = data.budget.max_daily_tokens ? (data.tokens / data.budget.max_daily_tokens) * 100 : 0;
  const costPct = data.budget.max_daily_cost_usd ? (data.cost / data.budget.max_daily_cost_usd) * 100 : 0;

  return (
    <div className="space-y-6">
      <header className="px-page-header">
        <div>
          <p className="px-eyebrow">BUKU PRODUKSI</p>
          <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
          <p className="text-sm text-zinc-400">Pemakaian model hari ini (UTC) dan sisa budget.</p>
        </div>
      </header>

      <section className="px-frame space-y-4">
        <Bar label="Token" used={data.tokens} limit={data.budget.max_daily_tokens} pct={tokenPct} />
        <Bar label="Biaya (USD)" used={data.cost} limit={data.budget.max_daily_cost_usd} pct={costPct} money />
        <p className="text-xs text-zinc-500">{Math.round(data.calls)} panggilan model hari ini.</p>
      </section>

      <section className="px-frame" data-motion="paused">
        <h2 className="mb-4 text-lg font-medium">Per agent</h2>
        {data.by_agent.length === 0 ? (
          <EmptyState
            title="Belum ada panggilan model hari ini"
            description="Jalankan job dengan mode mock untuk menguji alur tanpa biaya; mode live akan mengisi tabel ini."
          />
        ) : (
          <div
            role="region"
            aria-label="Rincian pemakaian per agent"
            tabIndex={0}
            className="px-table-scroll"
          >
            <table className="w-full min-w-[680px] text-sm">
              <caption className="sr-only">Pemakaian model per agent hari ini, UTC</caption>
              <thead>
                <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wide text-zinc-500">
                  <th scope="col" className="py-2">Agent</th>
                  <th scope="col">Provider</th>
                  <th scope="col">Model</th>
                  <th scope="col">Panggilan</th>
                  <th scope="col">Token</th>
                  <th scope="col" className="text-right">Biaya</th>
                </tr>
              </thead>
              <tbody>
                {data.by_agent.map((row, index) => {
                  // Baris historis dengan agent yang tidak ada di roster tetap tampil.
                  const member = roster(meta).find((p) => p.id === String(row.agent));
                  return (
                    <tr key={index} className="border-b border-zinc-900">
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-3">
                          {member && <PixelAvatar member={member} kind="idle" size={32} />}
                          <div>
                            <p className="font-medium">{member?.persona ?? String(row.agent)}</p>
                            {member && (
                              <code className="text-xs text-zinc-400">{String(row.agent)}</code>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="py-2 pr-4 text-zinc-400">{String(row.provider)}</td>
                      <td className="py-2 pr-4 font-mono text-xs text-zinc-400">{String(row.model)}</td>
                      <td className="py-2 pr-4 text-zinc-400">{String(row.calls)}</td>
                      <td className="py-2 pr-4 text-zinc-400">{String(row.tokens)}</td>
                      <td className="py-2 text-right text-zinc-400">${Number(row.cost).toFixed(5)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-4 text-xs text-zinc-500">Estimasi USD, bukan tagihan resmi provider.</p>
      </section>
    </div>
  );
}

function Bar({
  label,
  used,
  limit,
  pct,
  money = false,
}: {
  label: string;
  used: number;
  limit: number;
  pct: number;
  money?: boolean;
}) {
  const tone = pct >= 100 ? "bg-rose-500" : pct >= 80 ? "bg-amber-500" : "bg-sky-500";
  const fmt = (n: number) => (money ? `$${n.toFixed(4)}` : String(Math.round(n)));
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <span className="text-zinc-300">{label}</span>
        <span className="text-zinc-400">
          {fmt(used)} / {fmt(limit)} ({Math.round(pct)}%)
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>
    </div>
  );
}
