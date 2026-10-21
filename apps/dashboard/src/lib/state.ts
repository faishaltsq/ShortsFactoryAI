import type { AgentId, Connection, StudioEvent, StudioMode, StudioSnapshot } from './contracts';
export type StudioState = {
  mode: StudioMode; snapshot: StudioSnapshot | null; connection: Connection;
  selectedAgent: AgentId; selectedJob: string | null; error: string | null;
};
export type StudioAction = { type: 'snapshot'; snapshot: StudioSnapshot }
  | { type: 'connection'; connection: Connection; error?: string }
  | { type: 'mode'; mode: StudioMode }
  | { type: 'select_agent'; agent: AgentId }
  | { type: 'select_job'; job: string | null }
  | { type: 'event'; event: StudioEvent };
export function initialState(mode: StudioMode = 'production'): StudioState {
  return { mode, snapshot: null, connection: 'connecting', selectedAgent: 'ResearchAgent', selectedJob: null, error: null };
}
export function studioReducer(state: StudioState, action: StudioAction): StudioState {
  if (action.type === 'mode') return initialState(action.mode);
  if (action.type === 'select_agent') return { ...state, selectedAgent: action.agent };
  if (action.type === 'select_job') return { ...state, selectedJob: action.job };
  if (action.type === 'connection') return { ...state, connection: action.connection, error: action.error ?? null };
  if (action.type === 'event') {
    const prior = state.snapshot;
    const incoming = action.event;
    if (!prior || incoming.event_id <= prior.cursor) return state;
    const wanted = state.mode === 'demo' ? incoming.source === 'demo_fixture' : incoming.source !== 'demo_fixture';
    if (!wanted) return state;
    const agents = prior.agents.map(view => view.agent_id === incoming.agent_id && incoming.event_id > view.event_id
      ? { ...incoming, stale: false } : view);
    const events = [...prior.events.filter(item => item.event_id !== incoming.event_id), incoming]
      .sort((a, b) => a.event_id - b.event_id).slice(-200);
    return { ...state, snapshot: { ...prior, cursor: incoming.event_id, agents, events } };
  }
  if (action.snapshot.mode !== state.mode) return state;
  const prior = state.snapshot;
  if (prior && (action.snapshot.cursor < prior.cursor ||
    (action.snapshot.cursor === prior.cursor && Date.parse(action.snapshot.timestamp) <= Date.parse(prior.timestamp)))) return state;
  const events = [...new Map(action.snapshot.events.map(e => [e.event_id, e])).values()]
    .sort((a, b) => a.event_id - b.event_id).slice(-200);
  return { ...state, snapshot: { ...action.snapshot, events } };
}
