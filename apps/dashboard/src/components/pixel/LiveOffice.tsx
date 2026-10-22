"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import type { StudioResponse } from "@/lib/api";
import { agentStatus, roster, type AgentStatus, type Member } from "@/lib/team";
import { useStudioLive } from "@/lib/useStudioLive";
import { Office } from "./Office";

/**
 * Live studio view. Animation reflects persisted runner telemetry only; when the
 * API cannot confirm a run, the floor says so instead of pretending to be busy.
 */
export function LiveOffice({
  meta,
  renderInspector,
}: {
  meta: StudioResponse | null;
  renderInspector?: (member: Member, state: AgentStatus) => ReactNode;
}) {
  const live = useStudioLive();
  const members = roster(meta);
  const [selectedId, setSelectedId] = useState("");
  const [paused, setPaused] = useState(false);
  const selected = members.find((m) => m.id === selectedId) ?? members[0];

  if (!members.length) return <p role="status">Daftar tim belum tersedia.</p>;

  const pick = (id: string) => {
    setSelectedId(id);
    if (renderInspector && window.matchMedia("(max-width: 1199px)").matches) {
      document.getElementById("agent-inspector")?.scrollIntoView({ block: "start", behavior: "auto" });
    }
  };

  return (
    <section aria-label="Studio hidup" data-motion={paused ? "paused" : "playing"}>
      <div className="px-toolbar">
        <label>
          Pantau job terbaru
          <select
            value={live.focusId}
            onChange={(e) => live.selectJob(e.target.value)}
            disabled={!live.jobs.length}
          >
            {!live.jobs.length && (
              <option value="">{live.loading ? "Memuat aktivitas…" : "Belum ada job"}</option>
            )}
            {live.jobs.map((job) => (
              <option key={job.id} value={job.id}>
                {job.title} · {job.state}
              </option>
            ))}
          </select>
        </label>
        <button
          className="px-button"
          type="button"
          aria-pressed={paused}
          onClick={() => setPaused((v) => !v)}
        >
          Jeda animasi
        </button>
      </div>
      {live.error && (
        <div className="px-stale" role="status">
          <p>{live.error}</p>
          <button className="px-button" onClick={live.retry}>
            Coba lagi aktivitas
          </button>
        </div>
      )}
      {!live.error &&
        live.detail &&
        members.some(
          (m) => agentStatus(m.id, live.detail, false, m.available).kind === "unknown",
        ) && (
          <p className="px-stale" role="status">
            Run ini tidak terpantau API; aktivitas terakhir bukan bukti bahwa agent masih bekerja.
          </p>
        )}
      {live.detail && (
        <p className="mb-3 text-xs text-zinc-400">
          Job {live.detail.record.id} · mode{" "}
          {String(live.detail.record.payload.provider_mode ?? "tidak diketahui")} · status terakhir{" "}
          {live.detail.record.state}
        </p>
      )}
      <div className="px-studio-grid" data-inspector={Boolean(renderInspector)}>
        <Office
          members={members}
          selectedId={selected?.id ?? ""}
          onSelect={pick}
          detail={live.detail}
          stale={live.stale}
        />
        {selected &&
          renderInspector?.(
            selected,
            agentStatus(selected.id, live.detail, live.stale, selected.available),
          )}
      </div>
      {!renderInspector && selected && (
        <p className="mt-4 text-sm">
          {selected.persona} — {selected.role}.{" "}
          <Link href="/studio" className="text-sky-400 underline">
            Kenali tim & atur studio
          </Link>
        </p>
      )}
      <p className="mt-3 text-xs text-zinc-400">
        Animasi adalah tampilan status, bukan percakapan antar-agent. Aktivitas CLI yang tidak
        terpantau API ditandai apa adanya.
      </p>
    </section>
  );
}
