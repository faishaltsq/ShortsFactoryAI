import type { JobDetail, PersonaInfo, StudioResponse } from "./api";

export type Member = PersonaInfo & { id: string; editable: boolean; available: boolean };
export type ActivityKind =
  | "idle"
  | "working"
  | "validating"
  | "done"
  | "failed"
  | "blocked"
  | "unknown"
  | "unavailable";
export type AgentStatus = { kind: ActivityKind; label: string };

const LABELS: Record<ActivityKind, string> = {
  idle: "Siap membantu",
  working: "Sedang bekerja",
  validating: "Memeriksa hasil",
  done: "Selesai pada run ini",
  failed: "Perlu diperiksa",
  blocked: "Terhambat",
  unknown: "Tidak terpantau",
  unavailable: "Belum tersedia",
};

export const status = (kind: ActivityKind): AgentStatus => ({ kind, label: LABELS[kind] });

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const PHASES = ["running", "validating", "ready", "done", "failed", "blocked", "stopped", "interrupted"];

/** Every role the API knows about, falling back to the configurable subset. */
export function roster(meta: StudioResponse | null): Member[] {
  if (!meta) return [];
  const source = meta.team ?? meta.personas ?? {};
  const keys = Array.isArray(meta.agent_keys) ? meta.agent_keys : [];
  return Object.entries(source).map(([id, p]) => ({
    ...p,
    id,
    editable: keys.includes(id),
    available: p.available !== false,
  }));
}

/**
 * Status derived only from persisted runner telemetry.
 *
 * A lifecycle state is never enough to claim an agent is working: that requires
 * a snapshot whose token matches the run this API process currently owns. A
 * snapshot left behind by a previous process, a rejected token, or an
 * unrecognised phase all degrade to "unknown" rather than inventing activity.
 */
export function agentStatus(
  id: string,
  detail: JobDetail | null,
  stale: boolean,
  available = true,
): AgentStatus {
  if (!available) return status("unavailable");
  if (stale) return status("unknown");
  if (!detail) return status("idle");

  const a = object(detail.record.payload.studio_activity);
  if (
    typeof a.token !== "string" ||
    !/^[0-9a-f]{32}$/.test(a.token) ||
    typeof a.agent !== "string" ||
    typeof a.phase !== "string" ||
    !PHASES.includes(a.phase)
  ) {
    return status("unknown");
  }

  const live = detail.run.running && detail.run.activity_token === a.token;
  if (detail.run.running && !live) return status("unknown");

  if (id === "FactoryOrchestrator") {
    if (live && ["running", "validating", "ready"].includes(a.phase)) return status("working");
    if (a.phase === "blocked") return status("blocked");
    if (a.phase === "failed" || a.phase === "interrupted") return status("failed");
    return status(["running", "validating", "ready"].includes(a.phase) ? "unknown" : "idle");
  }

  if (a.agent === id) {
    if (a.phase === "running" || a.phase === "validating") {
      return status(live ? (a.phase === "running" ? "working" : "validating") : "unknown");
    }
    if (a.phase === "failed" || a.phase === "interrupted") return status("failed");
    if (a.phase === "blocked") return status("blocked");
  }

  if (typeof object(a.completed)[id] === "string") return status("done");
  return status("idle");
}
