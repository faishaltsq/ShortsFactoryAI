export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type AgentOverride = {
  model?: string | null;
  temperature?: number | null;
  prompt?: string | null;
};

export type StudioPayload = {
  version: number;
  agents: Record<string, AgentOverride>;
  budget: {
    unlimited?: boolean | null;
    max_daily_tokens?: number | null;
    max_daily_cost_usd?: number | null;
    max_retries?: number | null;
  };
  /** Jadwal produksi otomatis. Absen pada payload API lama. */
  schedule?: {
    enabled?: boolean | null;
    interval_hours?: number | null;
    max_per_day?: number | null;
    gap_minutes?: number | null;
    mode?: "mock" | "live" | null;
    stop?: string | null;
    topics?: string[] | null;
    quiet_hours?: number[] | null;
  };
  production: {
    fps?: number | null;
    target_duration_s?: number | null;
    videos_per_day?: number | null;
    tts_voice?: string | null;
    tts_rate?: string | null;
  };
  /** Setelan provider non-rahasia. Absen pada payload API lama. */
  providers?: {
    worker?: ProviderField;
    strategist_http?: ProviderField;
  };
  runner: { default_mode: "mock" | "live"; default_stop: string };
};

export type EffectiveConfig = {
  budget: Record<string, number | boolean | null>;
  production: Record<string, number | string>;
};

export type StudioResponse = {
  saved: StudioPayload;
  effective: EffectiveConfig;
  agent_keys: string[];
  default_prompts: Record<string, string>;
  runner_stops: string[];
  personas: Record<string, PersonaInfo>;
  /** Full 12-role roster. Absent on older API builds. */
  team?: Record<string, PersonaInfo>;
  studio_path: string;
  studio_exists: boolean;
};

export type PersonaInfo = {
  persona: string;
  role: string;
  description: string;
  stage: string;
  tier: string;
  accent: string;
  personality?: string;
  motto?: string;
  zone?: string;
  accessory?: string;
  hair?: string;
  skin?: string;
  /** False for deterministic stages with no editable system prompt. */
  editable?: boolean;
  /** False for roles this workspace does not implement yet. */
  available?: boolean;
};

export type HistoryEntry = { name: string; mtime: number; config: StudioPayload };

export type JobRow = {
  id: string;
  title: string;
  state: string;
  attempts: number;
  created_at: string;
  updated_at: string;
  last_error: string | null;
};

export type JobDetail = {
  record: JobRow & { payload: Record<string, unknown> };
  events: { from_state: string | null; to_state: string; detail: string; created_at: string }[];
  artifacts: string[];
  run: {
    running: boolean;
    mode?: string;
    stop?: string;
    report?: unknown;
    error?: string | null;
    /** Present only while this API process owns the run. */
    activity_token?: string;
  };
};

export type UsageResponse = {
  tokens: number;
  cost: number;
  calls: number;
  budget: {
    max_daily_tokens?: number | null;
    max_daily_cost_usd?: number | null;
    unlimited?: boolean;
  };
  by_agent: Record<string, string | number>[];
};

export type ProviderField = {
  enabled?: boolean | null;
  base_url?: string | null;
  model?: string | null;
  temperature?: number | null;
};

export type EditableProvider = ProviderField & {
  effective_base_url?: string | null;
  effective_model?: string | null;
  has_key?: boolean;
  /** base_url diarahkan ke origin lain, jadi kunci env sengaja tidak dikirim. */
  key_origin_mismatch?: boolean;
  configured?: boolean;
  binary?: string;
};

export type ProvidersResponse = {
  health: { ref: string; healthy: boolean; model: string }[];
  mode: Record<string, unknown>;
  /** Setelan yang bisa diedit. Absen pada API lama. */
  editable?: {
    worker: EditableProvider;
    strategist_http: EditableProvider;
  };
};

export type ScheduleStatus = {
  enabled: boolean;
  running: boolean;
  interval_hours: number;
  max_per_day: number;
  gap_minutes: number;
  mode: string;
  stop: string;
  topics: string[];
  quiet_hours: number[];
  last_plan: { due: boolean; reason: string; title: string | null } | null;
  last_error: string | null;
  created: string[];
};

export type ModelCatalog = { models: string[]; source: string | null; error: string | null };

export type FieldError = { loc: (string | number)[]; msg: string };

/** Terjemahkan 422 FastAPI menjadi error ber-field yang bisa dipetakan ke input. */
export function parseFieldErrors(detail: unknown): FieldError[] {
  if (!Array.isArray(detail)) return [];
  return detail.map((item: { loc?: (string | number)[]; msg?: string }) => ({
    loc: item.loc ?? [],
    msg: item.msg ?? "nilai tidak valid",
  }));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = null;
    }
    if (res.status === 422) {
      const first = parseFieldErrors(detail)[0];
      throw new ApiError(
        422,
        first ? `${first.loc.slice(1).join(".")}: ${first.msg}` : "validasi gagal",
        detail,
      );
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  getStudio: () => request<StudioResponse>("/api/studio"),
  putStudio: (payload: StudioPayload) =>
    request<{ saved: StudioPayload; effective: EffectiveConfig }>("/api/studio", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  listHistory: async () =>
    (await request<{ history: HistoryEntry[] }>("/api/studio/history")).history,
  rollback: (name: string) =>
    request<{ restored: StudioPayload; effective: EffectiveConfig }>("/api/studio/rollback", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  getModels: () =>
    request<{ models: string[]; source: string | null; error: string | null }>("/api/studio/models"),
  listJobs: (state?: string, signal?: AbortSignal) =>
    request<{ jobs: JobRow[]; states: string[]; running: Record<string, boolean> }>(
      state ? `/api/jobs?state=${encodeURIComponent(state)}` : "/api/jobs",
      { signal },
    ),
  getJob: (id: string, signal?: AbortSignal) => request<JobDetail>(`/api/jobs/${id}`, { signal }),
  createJob: (body: { title: string; mode?: string; stop?: string }) =>
    request<{ job_id: string; mode: string; stop: string }>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runJob: (id: string, body: { mode: string; stop: string }) =>
    request<{ job_id: string }>(`/api/jobs/${id}/run`, { method: "POST", body: JSON.stringify(body) }),
  cancelJob: (id: string) =>
    request<{ ok: boolean; status: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  getArtifact: <T,>(id: string, name: string) => request<T>(`/api/jobs/${id}/artifact/${name}`),
  usage: () => request<UsageResponse>("/api/usage/today"),
  schedule: () => request<ScheduleStatus>("/api/schedule"),
  scheduleTick: () =>
    request<{ due: boolean; reason: string; title: string | null }>("/api/schedule/tick", {
      method: "POST",
    }),
  scheduleApply: () =>
    request<ScheduleStatus>("/api/schedule/apply", { method: "POST" }),
  providers: () => request<ProvidersResponse>("/api/providers"),
  providerModels: (target: "worker" | "strategist_http") =>
    request<ModelCatalog>(`/api/providers/models?target=${target}`),
};
