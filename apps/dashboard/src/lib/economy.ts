/** Render economy: heavy Remotion work must never compete with the console. */
export function prefersEconomy(): boolean {
  if (typeof window === 'undefined') return true;
  const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } };
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
    || nav.connection?.saveData === true
    || (nav.deviceMemory ?? 8) <= 4
    || (nav.hardwareConcurrency ?? 8) <= 4;
}

export const STATUS_LABEL: Record<string, string> = {
  idle: 'Idle', working: 'Working', waiting: 'Waiting',
  blocked: 'Blocked', completed: 'Completed', failed: 'Failed',
};

export const STATUS_TONE: Record<string, string> = {
  idle: 'muted', working: 'teal', waiting: 'amber',
  blocked: 'amber', completed: 'ok', failed: 'red',
};
