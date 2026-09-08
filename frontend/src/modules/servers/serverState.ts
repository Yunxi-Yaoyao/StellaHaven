type Heartbeat = { status: string; last_seen_at: string | null };
export function reachable(n: Heartbeat, now = Date.now()): boolean {
  const age = now - new Date(n.last_seen_at || '').getTime();
  return n.status === 'online' && age >= 0 && age <= 120000;
}
export function componentTone(n: Heartbeat, installed: boolean | null, now = Date.now()): string {
  if (!reachable(n, now)) return 'off';
  return installed === true ? 'ok' : installed === false ? 'bad' : 'unknown';
}
export function errorDetail(e: unknown, fallback: string): string {
  const err = e as {detail?: unknown; message?: string};
  return typeof err?.detail === 'string' ? err.detail : err?.message || fallback;
}
