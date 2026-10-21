'use client';

import type { AgentId, AgentView, Connection, JobView, StudioEvent, StudioHealth, StudioMode } from '../lib/contracts';
import { STATUS_LABEL, STATUS_TONE } from '../lib/economy';

const TONE: Record<string, string> = { muted: '#a6b5b9', teal: '#83c4b4', amber: '#e8bf7b', ok: '#9fd0a5', red: '#ef9d99' };

export function Dot({ value }: { value: string }) {
  return <span className="dot" style={{ background: TONE[value] ?? '#a6b5b9' }} aria-hidden />;
}

export function TopBar({ health, mode, connection, economy, onToggleEconomy, onReconnect }: {
  health: StudioHealth; mode: StudioMode; connection: Connection;
  economy: boolean; onToggleEconomy(): void; onReconnect(): void;
}) {
  const states: Array<[string, string]> = [
    ['DB', health.database], ['Hermes', health.hermes], ['Mode', mode], ['Stream', connection],
  ];
  return (
    <header className="topbar">
      <span className="brand">Shorts Factory <b>/ Studio</b></span>
      <div className="pills">
        {states.map(([label, value]) => (
          <span className="pill" key={label} data-testid={`pill-${label.toLowerCase()}`}>
            <Dot value={['ok', 'connected'].includes(value) ? 'teal'
              : ['stale', 'degraded', 'reconnecting'].includes(value) ? 'amber'
                : value === 'offline' ? 'red' : 'muted'} />
            {label}: {value}
          </span>
        ))}
        <button className="pill pill--btn" onClick={onToggleEconomy} aria-pressed={economy}
          data-testid="economy-toggle">
          <Dot value={economy ? 'amber' : 'muted'} />
          {economy ? 'Ekonomi render: aktif' : 'Ekonomi render: mati'}
        </button>
        {connection !== 'connected' && (
          <button className="pill pill--btn" onClick={onReconnect} data-testid="reconnect">Coba ulang</button>
        )}
      </div>
    </header>
  );
}

export function QueuePanel({ jobs, selectedJob, events, error, onSelectJob, onSelectAgent }: {
  jobs: JobView[]; selectedJob: string | null; events: StudioEvent[];
  error: string | null; onSelectJob(id: string | null): void; onSelectAgent(agent: AgentId): void;
}) {
  const recent = [...events].slice(-40).reverse();
  return (
    <section className="panel queue" aria-label="Antrean produksi">
      <div className="panel__head">
        <h2>Antrean produksi</h2>
        <span className="meta" data-testid="queue-count">{jobs.length} job</span>
      </div>
      {selectedJob && <button className="pill pill--btn" onClick={() => onSelectJob(null)}>Hapus filter job</button>}
      <ul className="jobs">
        {jobs.map(job => (
          <li key={job.id}>
            <button className={job.id === selectedJob ? 'job job--on' : 'job'}
              onClick={() => onSelectJob(job.id === selectedJob ? null : job.id)}>
              <span className="job__id">{job.id.slice(0, 8)}</span>
              <span className="job__stage" title={job.title}>{job.title || job.quality.verification}</span>
              <span className="job__state"><Dot value={job.state === 'FAILED' || job.state === 'REJECTED' ? 'red'
                : job.state === 'BLOCKED' ? 'amber' : job.state === 'PUBLISHED' ? 'ok' : 'teal'} />{job.state}</span>
            </button>
          </li>
        ))}
        {jobs.length === 0 && <li className="empty">Belum ada job di antrean.</li>}
      </ul>
      <div className="panel__head panel__head--sub">
        <h2>Riwayat aktivitas</h2>
        <span className="meta" data-testid="cursor">event #{recent[0]?.event_id ?? 0}</span>
      </div>
      <div className="history" data-testid="history">
        {recent.map(event => (
          <button key={event.event_id} className="row" onClick={() => onSelectAgent(event.agent_id)}>
            <span className="row__id">#{event.event_id}</span>
            <span className="row__agent">{event.agent_id}</span>
            <span className="row__task" title={event.description}>{event.description}</span>
            <span className="row__state"
              style={{ color: event.status === 'failed' ? TONE.red : TONE[STATUS_TONE[event.status] ?? 'muted'] }}>
              {STATUS_LABEL[event.status]}
            </span>
          </button>
        ))}
        {recent.length === 0 && <p className="empty">Belum ada aktivitas tercatat.</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>
    </section>
  );
}

export function Inspector({ view, roles, jobs, logs, connection }: {
  view?: AgentView; roles: readonly AgentId[]; jobs: JobView[]; logs: string[]; connection: Connection;
}) {
  const job = jobs.find(item => item.id === view?.job_id);
  return (
    <section className="panel inspector" aria-label="Inspector agen">
      <div className="panel__head"><h2>Inspector</h2></div>
      {!view && <p className="empty">Pilih karakter atau baris riwayat untuk melihat detail.</p>}
      {view && (
        <dl className="kv" data-testid="inspector">
          <dt>Role</dt><dd>{roles.length ? roles.join(' + ') : view.agent_id}</dd>
          <dt>Agent</dt><dd>{view.agent_id}</dd>
          <dt>Status</dt><dd style={{ color: TONE[STATUS_TONE[view.status] ?? 'muted'] }}>
            {STATUS_LABEL[view.status]}{view.stale ? ' · stale lease' : ''}
          </dd>
          <dt>Model</dt><dd>{view.model ?? '—'}</dd>
          <dt>Event</dt><dd>#{view.event_id} · {view.event_type}</dd>
          <dt>Job</dt><dd>{view.job_id ? `${view.job_id.slice(0, 10)}…` : '—'}</dd>
          <dt>Stage</dt><dd>{view.stage ?? job?.state ?? '—'}</dd>
          <dt>Progres</dt><dd data-testid="agent-progress">
            {view.progress != null
              ? `${view.progress}%`
              : view.status === 'completed' ? '100% (selesai tanpa progres numerik)' : '—'}
          </dd>
          <dt>Sumber</dt><dd>{view.source}</dd>
          <dt>Waktu</dt><dd>{new Date(view.timestamp).toLocaleString('id-ID')}</dd>
          <dt>Aktivitas</dt><dd className="wrap">{view.description}</dd>
        </dl>
      )}
      <div className="panel__head panel__head--sub"><h2>Log</h2></div>
      <ul className="logs" data-testid="logs">
        {logs.map((line, index) => <li key={index}>{line}</li>)}
        {logs.length === 0 && <li className="empty">Belum ada log operator.</li>}
        <li className={connection === 'connected' ? 'ok' : 'error'}>
          stream: {connection}
        </li>
      </ul>
    </section>
  );
}

export function Pipeline({ groups, jobs }: {
  groups: Array<{ station: { label: string }; view?: AgentView }>; jobs: JobView[];
}) {
  const active = jobs.find(job => job.state !== 'PUBLISHED') ?? jobs[0];
  return (
    <section className="pipeline" aria-label="Pipeline produksi" data-testid="pipeline">
      {groups.map((group, index) => {
        const stage = group.view?.status ?? 'idle';
        const progress = Math.max(0, group.view?.progress ?? (stage === 'completed' ? 100 : 0));
        return (
          <div className="stage" key={group.station.label} data-state={stage}>
            <span className="stage__n">{index + 1}</span>
            <span className="stage__name">{group.station.label}</span>
            <span className="stage__state">{STATUS_LABEL[stage]}</span>
            <div className="stage__bar"><i style={{ width: `${progress}%` }} /></div>
            <span className="stage__pct">{progress}%</span>
          </div>
        );
      })}
      <div className="stage stage--job" data-state={active ? 'working' : 'idle'} data-testid="job-active">
        <span className="stage__name">Job aktif</span>
        <span className="stage__state">{active ? `${active.id.slice(0, 8)} · ${active.state}` : 'antrean kosong'}</span>
        <span className="stage__pct">{active ? active.quality.verification : '—'}</span>
      </div>
    </section>
  );
}

export function Preview({ src, mode, view, job, approval, onToggleDemo }: {
  src: string | null; mode: StudioMode; view?: AgentView; job?: JobView; approval: boolean;
  onToggleDemo(): void;
}) {
  return (
    <section className="panel preview" aria-label="Preview render">
      <div className="panel__head">
        <h2>Preview</h2>
        <button className="pill pill--btn" onClick={onToggleDemo} data-testid="mode-toggle">
          {mode === 'demo' ? 'Ke production' : 'Ke demo'}
        </button>
      </div>
      <div className="frame" data-testid="video-frame">
        {src ? (
          <video key={src} src={src} controls playsInline muted loop preload="metadata"
            aria-label={`Preview ${view?.job_id ?? 'job'}`} />
        ) : (
          <p className="empty">Belum ada hasil render pada mode ini.</p>
        )}
      </div>
      <div className="preview__job">
        {job ? (
          <>
            <strong title={job.title}>{job.title || 'Tanpa judul'}</strong>
            <span className="meta">{job.id.slice(0, 10)} · {job.state} · sumber {job.source}</span>
            <span className="meta">
              QC teknis {job.quality.technical == null ? '—' : job.quality.technical ? 'lolos' : 'gagal'}
              {' · editorial '}{job.quality.editorial == null ? '—' : job.quality.editorial ? 'ada flag' : 'bersih'}
              {' · verifikasi '}{job.quality.verification}
            </span>
            <span className="meta">
              {job.video.available
                ? `MP4 ${job.video.duration_ms == null ? '—' : `${(job.video.duration_ms / 1000).toFixed(1)} detik`}`
                : 'Belum ada MP4 terverifikasi'}
              {job.approval_required ? ' · perlu approval operator' : ''}
            </span>
            {job.thumbnail?.available && job.thumbnail.url ? (
              <span className="meta meta--thumb">
                <img className="thumb" src={job.thumbnail.url} alt={`Thumbnail ${job.id.slice(0, 8)}`} loading="lazy" />
                Thumbnail 1080×1920 terverifikasi
              </span>
            ) : null}
            {job.approval?.blockers?.length ? (
              <span className="meta meta--blockers" data-testid="approval-blockers">
                Blocker: {job.approval.blockers.slice(0, 3).join(' · ')}
              </span>
            ) : null}
          </>
        ) : (
          <span className="meta">Tidak ada job dipilih pada mode ini.</span>
        )}
      </div>
      <div className="preview__meta">
        <span><Dot value={approval ? 'amber' : 'muted'} />
          Approval: {approval ? 'menunggu operator' : 'tidak ada'}</span>
        <span>Render: {view?.progress != null
          ? `${view.progress}%`
          : view?.status === 'completed' ? '100%' : '0%'} · {STATUS_LABEL[view?.status ?? 'idle']}</span>
        <span>Riwayat: <a href="/api/events?limit=200" target="_blank" rel="noreferrer">/api/events</a></span>
      </div>
    </section>
  );
}
