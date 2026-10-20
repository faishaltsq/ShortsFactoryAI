import test from 'node:test';
import assert from 'node:assert/strict';
import { projectAgents, currentRole, videoPath, canAnimate } from '../../src/lib/selectors';
import { snapshot, event } from '../fixtures/snapshot';

test('selected-job projection prefers that jobs latest task and does not borrow another job', () => {
  const data = snapshot({ cursor: 4, events: [event({ event_id: 1, job_id: 'a' }), event({ event_id: 2, job_id: 'a', status: 'completed' }), event({ event_id: 4, job_id: 'b' })] });
  data.agents[1] = { ...event({ event_id: 4, job_id: 'b' }), stale: false };
  const filtered = projectAgents(data, 'a');
  assert.equal(filtered.find(a => a.agent_id === 'ResearchAgent')?.status, 'completed');
  assert.equal(filtered.find(a => a.agent_id === 'RenderAgent')?.status, 'idle');
  assert.equal(projectAgents(data, null), data.agents);
});

test('a grouped character selects genuine active work before newer completed work', () => {
  const data = snapshot();
  data.agents[1] = { ...event(), stale: false };
  data.agents[2] = { ...event({ agent_id: 'TopicSelectionAgent', event_id: 9, status: 'completed' }), stale: false };
  assert.equal(currentRole(['ResearchAgent', 'TopicSelectionAgent'], data.agents)?.agent_id, 'ResearchAgent');
});

test('video path is confined to the relative job endpoint and explicit mode', () => {
  assert.equal(videoPath('job-a', 'production'), '/api/jobs/job-a/video');
  assert.equal(videoPath('job-a', 'demo'), '/api/jobs/job-a/video?demo=true');
  assert.equal(videoPath('../escape', 'demo'), null);
  assert.equal(videoPath('https://evil.invalid', 'production'), null);
});

test('work animation is disabled for disconnected, stale, idle and render-economy states', () => {
  const active = { ...event(), stale: false };
  assert.equal(canAnimate(active, 'connected', false), true);
  assert.equal(canAnimate(active, 'offline', false), false);
  assert.equal(canAnimate({ ...active, stale: true }, 'connected', false), false);
  assert.equal(canAnimate({ ...active, status: 'idle' }, 'connected', false), false);
  assert.equal(canAnimate(active, 'connected', true), false);
});
