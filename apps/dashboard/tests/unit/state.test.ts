import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, studioReducer } from '../../src/lib/state';
import { snapshot, event } from '../fixtures/snapshot';

test('accepts the real zero-cursor idle snapshot without inventing tasks', () => {
  const data = snapshot();
  const state = studioReducer(initialState(), { type: 'snapshot', snapshot: data });
  assert.deepEqual(state.snapshot, data);
  assert.equal(state.snapshot?.agents.length, 12);
  assert.ok(state.snapshot?.agents.every(a => a.status === 'idle' && a.event_id === 0));
});

test('rejects a regressing cursor and duplicate or older same-cursor snapshots', () => {
  const state = studioReducer(initialState(), { type: 'snapshot', snapshot: snapshot({ cursor: 8 }) });
  for (const data of [snapshot({ cursor: 7 }), snapshot({ cursor: 8 }), snapshot({ cursor: 8, timestamp: '2026-10-20T09:00:00Z' })]) {
    assert.equal(studioReducer(state, { type: 'snapshot', snapshot: data }), state);
  }
});

test('same-cursor newer lease projection replaces working with stale waiting', () => {
  const first = snapshot({ cursor: 2 });
  first.agents[1] = { ...event({ event_id: 2 }), stale: false };
  const before = studioReducer(initialState(), { type: 'snapshot', snapshot: first });
  const fresh = structuredClone(first);
  fresh.timestamp = '2026-10-20T10:02:00Z';
  fresh.agents[1] = { ...fresh.agents[1], status: 'waiting', stale: true };
  assert.equal(studioReducer(before, { type: 'snapshot', snapshot: fresh }).snapshot?.agents[1].status, 'waiting');
});

test('disconnect preserves accepted snapshot and cursor for manual reconnect', () => {
  const live = studioReducer(initialState(), { type: 'snapshot', snapshot: snapshot({ cursor: 9 }) });
  const lost = studioReducer(live, { type: 'connection', connection: 'offline', error: 'Feed unavailable.' });
  assert.equal(lost.snapshot, live.snapshot);
  assert.equal(lost.connection, 'offline');
  assert.equal(lost.error, 'Feed unavailable.');
  assert.equal(lost.snapshot?.cursor, 9);
});

test('mode switch clears all production evidence and rejects late old-mode payloads', () => {
  const live = studioReducer(initialState(), { type: 'snapshot', snapshot: snapshot({ cursor: 9 }) });
  const demo = studioReducer(live, { type: 'mode', mode: 'demo' });
  assert.equal(demo.snapshot, null);
  assert.equal(demo.mode, 'demo');
  assert.equal(studioReducer(demo, { type: 'snapshot', snapshot: snapshot() }), demo);
});

test('authoritative history is ordered, deduplicated, bounded and retains separate jobs', () => {
  const events = Array.from({ length: 240 }, (_, i) => event({ event_id: i + 1, job_id: i % 2 ? 'job-b' : 'job-a' }));
  const data = snapshot({ cursor: 240, events: [...events.reverse(), events[0]] });
  const state = studioReducer(initialState(), { type: 'snapshot', snapshot: data });
  assert.equal(state.snapshot?.events.length, 200);
  assert.equal(state.snapshot?.events[0].event_id, 41);
  assert.equal(new Set(state.snapshot?.events.map(e => e.job_id)).size, 2);
});

test('operator can select canonical roles and filter a job without mutating evidence', () => {
  const state = studioReducer(initialState(), { type: 'snapshot', snapshot: snapshot() });
  const agent = studioReducer(state, { type: 'select_agent', agent: 'RenderAgent' });
  assert.equal(agent.selectedAgent, 'RenderAgent');
  const job = studioReducer(agent, { type: 'select_job', job: 'job-a' });
  assert.equal(job.selectedJob, 'job-a');
  assert.equal(job.snapshot, state.snapshot);
});

test('live event advances one role, one job and the cursor, and ignores replays', () => {
  const base = studioReducer(initialState(), { type: 'snapshot', snapshot: snapshot({ cursor: 5 }) });
  const incoming = event({ event_id: 6, job_id: 'job-a', source: 'production', progress: 40 });
  const after = studioReducer(base, { type: 'event', event: incoming });
  assert.equal(after.snapshot?.cursor, 6);
  assert.equal(after.snapshot?.events.at(-1)?.event_id, 6);
  const view = after.snapshot?.agents.find(a => a.agent_id === incoming.agent_id);
  assert.equal(view?.status, 'working');
  assert.equal(view?.progress, 40);
  assert.equal(studioReducer(after, { type: 'event', event: { ...incoming, event_id: 6 } }), after);
  assert.equal(studioReducer(after, { type: 'event', event: { ...incoming, event_id: 4 } }), after);
});

test('live event carries the wrong mode source without touching accepted evidence', () => {
  const production = studioReducer(initialState(), { type: 'snapshot', snapshot: snapshot({ cursor: 5 }) });
  const demoEvent = { ...event({ event_id: 6, source: 'demo_fixture' as const }) };
  assert.equal(studioReducer(production, { type: 'event', event: demoEvent }), production);

  const demo = studioReducer(initialState('demo'),
    { type: 'snapshot', snapshot: snapshot({ mode: 'demo', cursor: 5 }) });
  assert.equal(studioReducer(demo, { type: 'event', event: { ...event({ event_id: 6, source: 'production' as const }) } }), demo);
  assert.notEqual(studioReducer(demo, { type: 'event', event: demoEvent }), demo);
});
