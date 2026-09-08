/** Local UI identity, not an auth token. Works on LAN HTTP as well as HTTPS. */
let sequence = 0;
export function localId(): string {
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  }
  return `${Date.now().toString(36)}-${(++sequence).toString(36)}`;
}
