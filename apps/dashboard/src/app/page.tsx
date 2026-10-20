'use client';

import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { AgentId, StudioHealth, StudioMode } from '../lib/contracts';
import { StudioStream, fetchSnapshot } from '../lib/api';
import { prefersEconomy } from '../lib/economy';
import { WORKSTATIONS, canAnimate, currentRole, projectAgents, videoPath } from '../lib/selectors';
import { initialState, studioReducer } from '../lib/state';
import { Inspector, Pipeline, Preview, QueuePanel, TopBar } from '../components/Panels';
import { Office } from '../components/Office';

const PRODUCTION_KEY = 'studio:production';
const ECONOMY_KEY = 'studio:economy';
const EMPTY_HEALTH: StudioHealth = { database: 'ok', hermes: 'not_connected', hermes_last_seen: null };

export default function StudioPage() {
  const [state, dispatch] = useReducer(studioReducer, 'production' as StudioMode, initialState);
  const [economy, setEconomy] = useState(true);
  const [logs, setLogs] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const streamRef = useRef<StudioStream | null>(null);

  useEffect(() => {
    const stored: StudioMode = localStorage.getItem(PRODUCTION_KEY) === 'demo' ? 'demo' : 'production';
    setEconomy(localStorage.getItem(ECONOMY_KEY) === 'off' ? false : prefersEconomy());
    if (stored !== 'production') dispatch({ type: 'mode', mode: stored });
    setReady(true);
  }, []);

  useEffect(() => {
    document.body.classList.toggle('economy', economy);
    return () => { document.body.classList.remove('economy'); };
  }, [economy]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      try {
        const snapshot = await fetchSnapshot(state.mode);
        if (!cancelled) dispatch({ type: 'snapshot', snapshot });
      } catch (cause) {
        if (!cancelled) dispatch({
          type: 'connection', connection: 'offline',
          error: cause instanceof Error ? cause.message : 'Snapshot gagal dimuat.',
        });
      }
    })();
    return () => { cancelled = true; };
  }, [ready, state.mode]);

  useEffect(() => {
    if (!ready) return;
    const stream = new StudioStream({
      onSnapshot: snapshot => dispatch({ type: 'snapshot', snapshot }),
      onEvent: event => dispatch({ type: 'event', event }),
      onConnection: (connection, message) => {
        dispatch({ type: 'connection', connection });
        if (message) setLogs(previous => [message, ...previous].slice(0, 20));
      },
    });
    streamRef.current = stream;
    stream.start();
    return () => { streamRef.current = null; stream.stop(); };
  }, [ready]);

  const snapshot = state.snapshot;
  const agents = useMemo(
    () => (snapshot ? projectAgents(snapshot, state.selectedJob) : []),
    [snapshot, state.selectedJob],
  );

  const groups = WORKSTATIONS.map(station => {
    const view = currentRole(station.roles, agents);
    return { station, view, connection: state.connection };
  });

  const selectedRoles = WORKSTATIONS.find(station => station.roles.includes(state.selectedAgent))?.roles
    ?? [state.selectedAgent];
  const selectedView = currentRole(selectedRoles, agents);
  const renderView = currentRole(['RenderAgent', 'QualityAgent'], agents);
  const jobs = snapshot?.jobs ?? [];
  const approval = jobs.some(job => job.approval_required);
  const previewJob = jobs.find(job => job.id === state.selectedJob) ?? jobs.find(job => job.video.available);
  const previewSrc = previewJob?.video.available
    ? (previewJob.video.url ?? videoPath(previewJob.id, state.mode))
    : null;
  const economyActive = economy || (renderView?.status === 'working' && (renderView.progress ?? 0) > 0);

  function selectJob(jobId: string | null) {
    dispatch({ type: 'select_job', job: jobId });
    const linked = snapshot?.events.find(event => event.job_id === jobId);
    if (linked) dispatch({ type: 'select_agent', agent: linked.agent_id });
  }

  function toggleMode() {
    const next: StudioMode = state.mode === 'demo' ? 'production' : 'demo';
    localStorage.setItem(PRODUCTION_KEY, next);
    dispatch({ type: 'mode', mode: next });
  }

  function toggleEconomy() {
    const next = !economy;
    setEconomy(next);
    localStorage.setItem(ECONOMY_KEY, next ? 'on' : 'off');
  }

  return (
    <div className="shell">
      <TopBar health={snapshot?.health ?? EMPTY_HEALTH} mode={state.mode}
        connection={state.connection} economy={economy} onToggleEconomy={toggleEconomy}
        onReconnect={() => streamRef.current?.retry()} />

      <div className="main">
        <div className="queue-wrap">
          <QueuePanel jobs={jobs} selectedJob={state.selectedJob}
            events={snapshot?.events ?? []} error={state.error}
            onSelectJob={selectJob} onSelectAgent={agent => dispatch({ type: 'select_agent', agent })} />
        </div>

        <div className="stage-wrap">
          <Office groups={groups} economy={economyActive} selected={state.selectedAgent} approval={approval}
            onSelect={agent => dispatch({ type: 'select_agent', agent })} />
          <Pipeline groups={groups} jobs={jobs} />
        </div>

        <div className="inspector-wrap">
          <Inspector view={selectedView} roles={selectedRoles}
            jobs={jobs} logs={logs} connection={state.connection} />
        </div>
      </div>

      <Preview src={previewSrc} mode={state.mode} view={renderView} job={previewJob}
        approval={approval} onToggleDemo={toggleMode} />

      <p className="empty">
        Mode {state.mode} menampilkan hasil nyata atau fixture lokal. Progres render berasal dari worker, bukan animasi.
        {canAnimate(selectedView, state.connection, economyActive)
          ? ' Karakter bergerak mengikuti status pekerjaan.'
          : ' Karakter diam agar tidak berpura-pura bekerja.'}
      </p>
    </div>
  );
}
