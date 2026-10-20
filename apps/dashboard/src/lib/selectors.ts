import { AGENT_IDS, type AgentId, type AgentView, type Connection, type StudioMode, type StudioSnapshot } from './contracts';

const JOB_ID = /^[A-Za-z0-9_-]+$/;

/** Latest persisted task per canonical role, optionally confined to one job. */
export function projectAgents(data: StudioSnapshot, job: string | null): AgentView[] {
  if (!job) return data.agents;
  const latest = new Map<AgentId, AgentView>();
  for (const activity of data.events) {
    if (activity.job_id !== job) continue;
    const known = latest.get(activity.agent_id);
    if (!known || activity.event_id > known.event_id) {
      const current = data.agents.find(view => view.agent_id === activity.agent_id);
      latest.set(activity.agent_id, { ...activity, stale: current?.event_id === activity.event_id ? current.stale : false });
    }
  }
  return data.agents.map(view => latest.get(view.agent_id) ?? view);
}

/** A grouped character shows genuine working work before newer finished work. */
export function currentRole(ids: readonly AgentId[], agents: AgentView[]): AgentView | undefined {
  const candidates = agents.filter(view => ids.includes(view.agent_id));
  return candidates.find(view => view.status === 'working')
    ?? candidates.reduce<AgentView | undefined>((best, view) =>
      !best || view.event_id > best.event_id ? view : best, undefined);
}

/** Same-origin media only; a foreign or malformed job id produces no player. */
export function videoPath(job: string, mode: StudioMode): string | null {
  if (!JOB_ID.test(job)) return null;
  return `/api/jobs/${job}/video${mode === 'demo' ? '?demo=true' : ''}`;
}

/** Animation follows a live, non-stale, genuinely working event on an able device. */
export function canAnimate(agent: AgentView | undefined, connection: Connection, economy: boolean): boolean {
  return Boolean(agent && !agent.stale && agent.status === 'working' && connection === 'connected' && !economy);
}

/** Workstation grouping: 12 canonical roles rendered as six physical desks. */
export const WORKSTATIONS: readonly { id: string; label: string; roles: readonly AgentId[] }[] = [
  { id: 'control', label: 'Control desk', roles: ['FactoryOrchestrator', 'PublishAgent'] },
  { id: 'research', label: 'Research desk', roles: ['ResearchAgent', 'TopicSelectionAgent'] },
  { id: 'writing', label: 'Writing desk', roles: ['ScriptAgent', 'CreativeDirectorAgent'] },
  { id: 'board', label: 'Storyboard desk', roles: ['StoryboardAgent', 'AssetAgent'] },
  { id: 'audio', label: 'Audio bench', roles: ['AudioAgent'] },
  { id: 'render', label: 'Render rack', roles: ['RenderAgent', 'QualityAgent', 'MetadataAgent'] },
];

export const PIPELINE: readonly (readonly AgentId[])[] = WORKSTATIONS.map(station => station.roles);

export function agentIndex(agent: AgentId): number {
  return AGENT_IDS.indexOf(agent);
}
