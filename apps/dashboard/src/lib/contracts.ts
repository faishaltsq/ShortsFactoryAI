export const AGENT_IDS = [
  'FactoryOrchestrator', 'ResearchAgent', 'TopicSelectionAgent', 'ScriptAgent',
  'CreativeDirectorAgent', 'StoryboardAgent', 'AssetAgent', 'AudioAgent',
  'RenderAgent', 'QualityAgent', 'MetadataAgent', 'PublishAgent'
] as const;
export type AgentId = typeof AGENT_IDS[number];
export type AgentStatus = 'idle' | 'working' | 'waiting' | 'blocked' | 'completed' | 'failed';
export type EventSource = 'production' | 'mock' | 'demo_fixture';
export type StudioMode = 'production' | 'demo';
export type StudioEvent = {
  event_id: number; job_id: string; agent_id: AgentId;
  event_type: string; status: AgentStatus; timestamp: string;
  description: string; progress: number | null; model: string | null;
  stage: string | null; run_id: string | null; source: EventSource;
};
export type AgentView = StudioEvent & { stale: boolean };
export type JobView = {
  id: string; title: string; state: string; source: EventSource;
  created_at: string; updated_at: string; approval_required: boolean;
  approval: { eligible: boolean | null; blockers: string[] };
  thumbnail: { available: boolean; url: string | null };
  video: { available: boolean; url: string | null; duration_ms: number | null };
  quality: { technical: boolean | null; editorial: boolean | null; verification: string; checks: Record<string, boolean> };
};
export type StudioSnapshot = {
  cursor: number; timestamp: string; mode: StudioMode;
  agents: AgentView[]; jobs: JobView[]; events: StudioEvent[];
  health: { database: 'ok'; hermes: 'not_connected' | 'connected' | 'stale'; hermes_last_seen: string | null };
};
export type Connection = 'connecting' | 'connected' | 'reconnecting' | 'offline' | 'error';
export type StudioHealth = StudioSnapshot['health'];

/** Operator-facing production status. Mirrors packages/core/observability/schedule.py. */
export const SCHEDULE_STATUSES = ['ON GOING', 'RESEARCHING', 'UPCOMING', 'SELESAI', 'GAGAL', 'TERTAHAN'] as const;
export type ScheduleStatus = typeof SCHEDULE_STATUSES[number];
export type ScheduleEntry = {
  job_id: string; title: string; status: ScheduleStatus; state: string;
  stage_label: string; next_action: string;
  genre: string | null; content_type: string | null; templates: string[];
  scene_count: number; duration_ms: number | null; verification: string; sources: number;
  progress: number; due_at: string | null; plan_id: string | null; slot_status: string | null;
  attempts: number; source: EventSource; approval_required: boolean;
  created_at: string; updated_at: string;
};
export type ProductionSchedule = {
  generated_at: string; total: number;
  counts: Record<ScheduleStatus, number>;
  entries: ScheduleEntry[];
};
