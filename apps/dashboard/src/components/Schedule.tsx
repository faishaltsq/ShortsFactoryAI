'use client';

import type { ProductionSchedule, ScheduleEntry, ScheduleStatus } from '../lib/contracts';

const TONE: Record<ScheduleStatus, string> = {
  'ON GOING': '#83c4b4', RESEARCHING: '#e8bf7b', UPCOMING: '#a6b5b9',
  SELESAI: '#9fd0a5', GAGAL: '#ef9d99', TERTAHAN: '#e8bf7b',
};

const HINT: Record<ScheduleStatus, string> = {
  'ON GOING': 'sedang dikerjakan',
  RESEARCHING: 'riset & penulisan',
  UPCOMING: 'belum dijadwalkan mulai',
  SELESAI: 'sudah terbit',
  GAGAL: 'berhenti karena error',
  TERTAHAN: 'menunggu operator',
};

function when(entry: ScheduleEntry): string {
  if (entry.due_at) {
    const due = new Date(entry.due_at);
    if (!Number.isNaN(due.getTime())) {
      return `jadwal ${due.toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}`;
    }
  }
  const stamp = new Date(entry.updated_at);
  if (Number.isNaN(stamp.getTime())) return '—';
  return `diperbarui ${stamp.toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}`;
}

function content(entry: ScheduleEntry): string {
  const parts: string[] = [];
  if (entry.genre) parts.push(entry.genre);
  if (entry.content_type) parts.push(entry.content_type);
  if (entry.scene_count) parts.push(`${entry.scene_count} scene`);
  if (entry.duration_ms) parts.push(`${(entry.duration_ms / 1000).toFixed(1)} dtk`);
  if (entry.templates.length) parts.push(entry.templates.join(' + '));
  return parts.join(' · ') || 'belum ada artefak konten';
}

export function SchedulePanel({ schedule, error, filter, onFilter, onSelectJob, onRefresh, loading }: {
  schedule: ProductionSchedule | null; error: string | null;
  filter: ScheduleStatus | 'SEMUA'; onFilter(status: ScheduleStatus | 'SEMUA'): void;
  onSelectJob(jobId: string): void; onRefresh(): void; loading: boolean;
}) {
  const entries = schedule?.entries ?? [];
  const visible = filter === 'SEMUA' ? entries : entries.filter(entry => entry.status === filter);
  const counts = schedule?.counts;
  const chips: Array<ScheduleStatus | 'SEMUA'> = ['SEMUA', 'ON GOING', 'RESEARCHING', 'UPCOMING', 'SELESAI', 'GAGAL', 'TERTAHAN'];

  return (
    <section className="panel schedule" aria-label="Jadwal produksi">
      <div className="panel__head">
        <h2>Jadwal produksi</h2>
        <span className="meta" data-testid="schedule-total">
          {loading ? 'memuat…' : `${schedule?.total ?? 0} konten`}
        </span>
      </div>

      <div className="schedule__chips" role="group" aria-label="Filter status jadwal">
        {chips.map(status => (
          <button key={status} className={status === filter ? 'chip chip--on' : 'chip'}
            onClick={() => onFilter(status)} data-testid={`schedule-filter-${status.replace(/\s+/g, '-').toLowerCase()}`}
            aria-pressed={status === filter}>
            {status !== 'SEMUA' && <span className="chip__dot" style={{ background: TONE[status] }} aria-hidden />}
            {status === 'SEMUA' ? 'Semua' : status}
            <span className="chip__n">
              {status === 'SEMUA' ? schedule?.total ?? 0 : counts?.[status] ?? 0}
            </span>
          </button>
        ))}
      </div>

      {error && <p className="error" role="alert" data-testid="schedule-error">{error}</p>}

      <ol className="schedule__list" data-testid="schedule-list">
        {visible.map(entry => (
          <li key={entry.job_id}>
            <button className="sched" onClick={() => onSelectJob(entry.job_id)}
              data-testid={`schedule-row-${entry.job_id}`} data-status={entry.status}>
              <span className="sched__status" style={{ color: TONE[entry.status] }}>
                <span className="sched__dot" style={{ background: TONE[entry.status] }} aria-hidden />
                {entry.status}
              </span>
              <span className="sched__title" title={entry.title}>{entry.title}</span>
              <span className="sched__stage">{entry.stage_label} · {entry.progress}%</span>
              <span className="sched__bar" aria-hidden>
                <i style={{ width: `${entry.progress}%`, background: TONE[entry.status] }} />
              </span>
              <span className="sched__content">{content(entry)}</span>
              <span className="sched__next">
                {entry.next_action} · {when(entry)}
                {entry.approval_required ? ' · perlu approval' : ''}
                {entry.verification !== 'unverified' ? ` · verifikasi ${entry.verification}` : ''}
              </span>
            </button>
          </li>
        ))}
        {visible.length === 0 && !loading && (
          <li className="empty">
            {entries.length === 0 ? 'Belum ada konten pada jadwal.' : `Tidak ada konten berstatus ${filter}.`}
          </li>
        )}
      </ol>

      <div className="schedule__foot">
        <span className="meta">
          {(['ON GOING', 'RESEARCHING', 'UPCOMING'] as ScheduleStatus[])
            .map(status => `${HINT[status]}: ${counts?.[status] ?? 0}`).join(' · ')}
        </span>
        <button className="pill pill--btn" onClick={onRefresh} disabled={loading} data-testid="schedule-refresh">
          Muat ulang
        </button>
      </div>
    </section>
  );
}
