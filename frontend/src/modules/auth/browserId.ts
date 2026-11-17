/** Per-origin/profile grouping hint, never an authentication credential or fingerprint. */
const key = 'stella_browser_id';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
let memoryId: string | undefined;
export function getBrowserId(): string | undefined {
  if (memoryId) return memoryId;
  try {
    const saved = localStorage.getItem(key);
    if (saved && uuid.test(saved)) return memoryId = saved;
  } catch { /* Storage can be disabled in private/embedded contexts. */ }
  const secure = globalThis.crypto;
  if (typeof secure?.randomUUID === 'function') memoryId = secure.randomUUID();
  else if (typeof secure?.getRandomValues === 'function') {
    const bytes = secure.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6]! & 0x0f) | 0x40;
    bytes[8] = (bytes[8]! & 0x3f) | 0x80;
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    memoryId = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  // Older contexts without secure randomness keep working without a grouping hint.
  if (memoryId) try { localStorage.setItem(key, memoryId); } catch { /* Memory fallback. */ }
  return memoryId;
}
