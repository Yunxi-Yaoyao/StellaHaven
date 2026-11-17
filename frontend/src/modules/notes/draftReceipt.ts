import type { ConsumedDraft } from '../../api/notes';

/** Preserve the server timestamp verbatim: Date roundtrips lose microseconds. */
export async function draftReceipt(content: string, timestamp: string): Promise<ConsumedDraft | undefined> {
  try {
    if (!timestamp || !globalThis.crypto?.subtle) return undefined;
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
    return { draft_updated_at: timestamp, content_hash: Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('') };
  } catch {
    // An unavailable digest must never turn into permission to clear a slot.
    return undefined;
  }
}
