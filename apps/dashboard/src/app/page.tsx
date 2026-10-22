'use client';

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { AgentId, ScheduleStatus, StudioHealth, StudioMode, ProductionSchedule } from '../lib/contracts';
import { StudioStream, approveJob, fetchSchedule, fetchSnapshot, rejectJob } from '../lib/api';
import { prefersEconomy } from '../lib/economy';
import { WORKSTATIONS, canAnimate, currentRole, projectAgents, videoPath } from '../lib/selectors';
import { initialState, studioReducer } from '../lib/state';
import { Inspector, Pipeline, Preview, QueuePanel, TopBar } from '../components/Panels';
import { Office } from '../components/Office';
import { SchedulePanel } from '../components/Schedule';

const PRODUCTION_KEY = 'studio:production';
const ECONOMY_KEY = 'studio:economy';
const OPERATOR_KEY = 'studio:operator';
const VIEW_KEY = 'studio:view';
const EMPTY_HEALTH: StudioHealth = { database: 'ok', hermes: 'not_connected', hermes_last_seen: null };

type StudioView = 'studio' | 'schedule';

export default function StudioPage() {
  const [state, dispatch] = useReducer(studioReducer, 'production' as StudioMode, initialState);
  const [economy, setEconomy] = useState(true);
  const [logs, setLogs] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [operator, setOperator] = useState('');
  const [deciding, setDeciding] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [view, setView] = useState<StudioView>('studio');
  const [schedule, setSchedule] = useState<ProductionSchedule | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleFilter, setScheduleFilter] = useState<ScheduleStatus | 'SEMUA'>('SEMUA');
  const streamRef = useRef<StudioStream | null>(null);

  useEffect(() => {
    const stored: StudioMode = localStorage.getItem(PRODUCTION_KEY) === 'demo' ? 'demo' : 'production';
    setEconomy(localStorage.getItem(ECONOMY_KEY) === 'off' ? false : prefersEconomy());
    setOperator(localStorage.getItem(OPERATOR_KEY) ?? '');
    setView(localStorage.getItem(VIEW_KEY) === 'schedule' ? 'schedule' : 'studio');
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

  const loadSchedule = useCallback(async () => {
    setScheduleLoading(true);
    setScheduleError(null);
    try {
      setSchedule(await fetchSchedule());
    } catch (cause) {
      setScheduleError(cause instanceof Error ? cause.message : 'Jadwal gagal dimuat.');
    } finally {
      setScheduleLoading(false);
    }
  }, []);

  // The schedule is a projection of persisted state, so it is re-read on view change,
  // on refresh, and whenever the live feed reports a new event.
  useEffect(() => {
    if (!ready || view !== 'schedule') return;
    void loadSchedule();
  }, [ready, view, loadSchedule, state.snapshot?.cursor]);

  function openSchedule() {
    setView('schedule');
    localStorage.setItem(VIEW_KEY, 'schedule');
  }

  function openStudio() {
    setView('studio');
    localStorage.setItem(VIEW_KEY, 'studio');
  }

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
  // The decision acts on whichever job is waiting, never on whatever the preview
  // happens to be showing: those two can differ when a render is still queued.
  const pendingJob = jobs.find(job => job.approval_required) ?? null;
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

  async function decide(decision: 'approve' | 'reject', reason?: string) {
    const target = pendingJob;
    if (!target) return;
    setDecisionError(null);
    if (!operator.trim()) {
      setDecisionError('Isi nama operator dulu; keputusan wajib menyebut siapa yang memutuskannya.');
      return;
    }
    if (decision === 'reject' && !(reason ?? '').trim()) {
      setDecisionError('Penolakan butuh alasan, supaya perbaikannya bisa ditindaklanjuti.');
      return;
    }
    setDeciding(true);
    try {
      if (decision === 'approve') await approveJob(target.id, operator.trim());
      else await rejectJob(target.id, reason!.trim(), operator.trim());
      // The studio stream repaints on its own, but the operator wants to see the
      // state change now rather than on the next poll.
      const snapshot = await fetchSnapshot(state.mode);
      dispatch({ type: 'snapshot', snapshot });
    } catch (cause) {
      setDecisionError(cause instanceof Error ? cause.message : 'Keputusan gagal dikirim.');
    } finally {
      setDeciding(false);
    }
  }

  return (
    <div className="shell">
      <TopBar health={snapshot?.health ?? EMPTY_HEALTH} mode={state.mode}
        connection={state.connection} economy={economy} onToggleEconomy={toggleEconomy}
        onReconnect={() => streamRef.current?.retry()} />

      <nav className="menu" aria-label="Menu studio" data-testid="studio-menu">
        <button className={view === 'studio' ? 'menu__item menu__item--on' : 'menu__item'}
          onClick={openStudio} data-testid="menu-studio" aria-current={view === 'studio' ? 'page' : undefined}>
          Studio produksi
          <span className="menu__n">{jobs.length}</span>
        </button>
        <button className={view === 'schedule' ? 'menu__item menu__item--on' : 'menu__item'}
          onClick={openSchedule} data-testid="menu-schedule" aria-current={view === 'schedule' ? 'page' : undefined}>
          Jadwal produksi
          <span className="menu__n">{schedule?.total ?? 0}</span>
        </button>
      </nav>

      {view === 'schedule' ? (
        <div className="schedule-wrap">
          <SchedulePanel schedule={schedule} error={scheduleError} filter={scheduleFilter}
            onFilter={setScheduleFilter} onRefresh={() => void loadSchedule()} loading={scheduleLoading}
            onSelectJob={jobId => {
              selectJob(jobId);
              openStudio();
            }} />
        </div>
      ) : (
        <>
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
            approval={approval} onToggleDemo={toggleMode} operator={operator} onDecide={decide}
            deciding={deciding} decisionError={decisionError} onOperatorChange={value => {
              setOperator(value);
              localStorage.setItem(OPERATOR_KEY, value);
            }} />

          <p className="empty">
            Mode {state.mode} menampilkan hasil nyata atau fixture lokal. Progres render berasal dari worker, bukan animasi.
            {canAnimate(selectedView, state.connection, economyActive)
              ? ' Karakter bergerak mengikuti status pekerjaan.'
              : ' Karakter diam agar tidak berpura-pura bekerja.'}
          </p>
        </>
      )}
    </div>
  );
}
