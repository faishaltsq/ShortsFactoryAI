import type { Connection, ProductionSchedule, StudioEvent, StudioSnapshot } from './contracts';

export type StreamHandlers = {
  onSnapshot(snapshot: StudioSnapshot): void;
  onEvent(event: StudioEvent): void;
  onConnection(connection: Connection, error?: string): void;
};

const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000, 30000];
const endpoint = (cursor: number) => `/api/studio/stream?after=${encodeURIComponent(cursor)}`;

/** Manual-cursor SSE reader: the browser's automatic retry cannot resume our cursor. */
export class StudioStream {
  private source: EventSource | null = null;
  private cursor = 0;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(private readonly handlers: StreamHandlers) {}

  start(): void {
    this.stopped = false;
    this.open();
  }

  /** Operator-driven reconnect: forget the backoff and reopen at the current cursor. */
  retry(): void {
    this.attempt = 0;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.source?.close();
    this.source = null;
    this.handlers.onConnection('connecting');
    this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.source?.close();
    this.source = null;
  }

  private open(): void {
    if (this.stopped) return;
    this.handlers.onConnection(this.attempt === 0 ? 'connecting' : 'reconnecting');
    const source = new EventSource(endpoint(this.cursor));
    this.source = source;

    source.addEventListener('snapshot', message => {
      const recovery = this.attempt;
      this.attempt = 0;
      const snapshot = JSON.parse((message as MessageEvent).data) as StudioSnapshot;
      this.cursor = Math.max(this.cursor, snapshot.cursor);
      this.handlers.onConnection('connected',
        recovery > 0 ? `stream: connected setelah ${recovery} percobaan ulang` : undefined);
      this.handlers.onSnapshot(snapshot);
    });
    source.addEventListener('studio', message => {
      const event = JSON.parse((message as MessageEvent).data) as StudioEvent;
      this.cursor = Math.max(this.cursor, event.event_id);
      this.handlers.onEvent(event);
    });
    source.onerror = () => {
      source.close();
      if (this.source === source) this.source = null;
      if (this.stopped) return;
      const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
      this.attempt += 1;
      this.handlers.onConnection(this.attempt >= BACKOFF_MS.length ? 'offline' : 'reconnecting',
        this.attempt >= BACKOFF_MS.length ? 'Feed terputus; state terakhir tetap ditampilkan.' : undefined);
      this.timer = setTimeout(() => this.open(), delay);
    };
  }
}

export async function fetchSnapshot(mode: string): Promise<StudioSnapshot> {
  const response = await fetch(`/api/studio/snapshot?mode=${encodeURIComponent(mode)}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Snapshot unavailable (${response.status})`);
  return (await response.json()) as StudioSnapshot;
}

/** Thrown when the studio refuses a decision, carrying the API's own wording. */
export class DecisionRefused extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function post<T>(path: string, body: object): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    // FastAPI puts the reason in { detail }; fall back to the status so a
    // refused decision still reads as something specific in the panel.
    const detail = (await response.json().catch(() => null))?.detail;
    throw new DecisionRefused(response.status,
      typeof detail === 'string' ? detail : `Permintaan ditolak (${response.status})`);
  }
  return (await response.json()) as T;
}

export function approveJob(jobId: string, operator: string): Promise<{ state: string }> {
  return post(`/api/jobs/${jobId}/approve`, { operator });
}

export function rejectJob(jobId: string, reason: string, operator: string): Promise<{ state: string }> {
  return post(`/api/jobs/${jobId}/reject`, { operator, reason });
}

export async function fetchSchedule(): Promise<ProductionSchedule> {
  const response = await fetch('/api/studio/schedule', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Jadwal tidak tersedia (${response.status})`);
  return (await response.json()) as ProductionSchedule;
}
