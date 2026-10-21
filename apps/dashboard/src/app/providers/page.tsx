"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type ProvidersResponse } from "@/lib/api";
import { ErrorState } from "@/components/states";

export default function ProvidersPage() {
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [providers, models] = await Promise.all([api.providers(), api.getModels()]);
      setData(providers);
      setModelsError(models.error);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memeriksa provider");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Providers</h1>
          <p className="text-sm text-zinc-400">
            Kesehatan model worker dan strategist. Provider yang tidak sehat otomatis dilewati router.
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="rounded-md border border-zinc-700 px-4 py-2 text-sm hover:bg-zinc-800 disabled:opacity-50"
        >
          {loading ? "Memeriksa…" : "Periksa ulang"}
        </button>
      </header>

      {error && <ErrorState title="Provider tidak bisa diperiksa" message={error} onRetry={load} />}

      {loading && !data && (
        <p className="text-sm text-zinc-500" role="status">
          Memeriksa provider…
        </p>
      )}

      {data && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {data.health.map((item) => (
              <div
                key={item.ref}
                className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/40 p-5"
              >
                <div>
                  <p className="font-mono text-sm">{item.ref}</p>
                  <p className="text-xs text-zinc-500">model {item.model}</p>
                </div>
                <span className="flex items-center gap-2 text-xs">
                  <span className={`h-2.5 w-2.5 rounded-full ${item.healthy ? "bg-emerald-500" : "bg-rose-500"}`} />
                  {item.healthy ? "sehat" : "tidak sehat"}
                </span>
              </div>
            ))}
          </div>

          <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 text-sm text-zinc-300">
            <h2 className="mb-2 text-lg font-medium">Mode</h2>
            <p className="text-zinc-400">Worker base URL: {String(data.mode.worker_base_url ?? "belum dikonfigurasi")}</p>
            <p className="text-zinc-400">Worker configured: {String(data.mode.worker_configured)}</p>
            <p className="text-zinc-400">Strategist model: {String(data.mode.strategist_model)}</p>
            {modelsError && <p className="mt-3 text-xs text-amber-400">Daftar model tidak tersedia: {modelsError}</p>}
          </section>
        </>
      )}
    </div>
  );
}
