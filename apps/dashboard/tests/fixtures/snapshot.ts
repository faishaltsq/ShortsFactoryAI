import { AGENT_IDS, type StudioSnapshot, type StudioEvent } from '../../src/lib/contracts';

// Browser/unit fixtures only. Never imported by the application.
export function snapshot(overrides: Partial<StudioSnapshot> = {}): StudioSnapshot {
  return {
    cursor: 0, timestamp: '2026-10-20T10:00:00Z', mode: 'production',
    agents: AGENT_IDS.map(agent_id => ({
      event_id: 0, job_id: '', agent_id, event_type: 'idle', status: 'idle',
      timestamp: '2026-10-20T10:00:00Z', description: 'No task recorded.',
      progress: null, model: null, stage: null, run_id: null, source: 'production', stale: false
    })),
    jobs: [], events: [],
    health: { database: 'ok', hermes: 'not_connected', hermes_last_seen: null },
    ...overrides
  };
}
export function event(overrides: Partial<StudioEvent> = {}): StudioEvent {
  return { ...snapshot().agents[1], event_id: 1, job_id: 'job-fixture-a', event_type: 'stage_started',
    status: 'working', stage: 'research', description: 'Collecting candidate sources.', source: 'demo_fixture', ...overrides };
}
