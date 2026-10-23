import type { CSSProperties } from "react";

import type { JobDetail } from "@/lib/api";
import { agentStatus, type Member } from "@/lib/team";
import { PixelAvatar } from "./PixelAvatar";

/**
 * The studio floor: one workstation per role, grouped by zone.
 *
 * Stations are real buttons so every character is reachable by keyboard and
 * screen reader. Selecting a station only changes what the inspector shows; it
 * never starts, resumes, or configures anything.
 */
export function Office({
  members,
  selectedId,
  onSelect,
  detail,
  stale,
}: {
  members: Member[];
  selectedId: string;
  onSelect: (id: string) => void;
  detail: JobDetail | null;
  stale: boolean;
}) {
  const zones = [...new Set(members.map((p) => p.zone ?? "Tim studio"))];
  return (
    <section className="px-office" aria-label="Lantai studio">
      <header className="px-office-sign">
        <h2>Tim di balik cerita</h2>
        <span className="px-plant" aria-hidden="true" />
      </header>
      {zones.map((zone) => (
        <section className="px-zone" key={zone} aria-label={zone}>
          <h3>{zone}</h3>
          <div className="px-stations">
            {members
              .filter((p) => (p.zone ?? "Tim studio") === zone)
              .map((member) => {
                const state = agentStatus(member.id, detail, stale, member.available);
                return (
                  <button
                    key={member.id}
                    type="button"
                    className="px-station"
                    aria-pressed={selectedId === member.id}
                    aria-label={`${member.persona} · ${member.role} · ${state.label}`}
                    onClick={() => onSelect(member.id)}
                    style={{ "--agent-accent": member.accent } as CSSProperties}
                  >
                    <PixelAvatar member={member} kind={state.kind} size={80} />
                    <span className="px-desk" aria-hidden="true">
                      <span className="px-monitor">
                        {member.available ? (
                          "▰"
                        ) : (
                          <svg
                            viewBox="0 0 12 12"
                            width="12"
                            height="12"
                            aria-hidden="true"
                            shapeRendering="crispEdges"
                          >
                            <path fill="currentColor" d="M3 1h6v5H7V3H5v3H3z M2 6h8v6H2z" />
                          </svg>
                        )}
                      </span>
                      <span className="px-desk-note" />
                    </span>
                    <strong>{member.persona}</strong>
                    <small>{member.role}</small>
                    <span className="px-status" data-kind={state.kind}>
                      {state.label}
                    </span>
                  </button>
                );
              })}
          </div>
        </section>
      ))}
    </section>
  );
}
