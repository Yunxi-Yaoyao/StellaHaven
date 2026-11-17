import { watch, onActivated, onDeactivated, onBeforeUnmount, type Ref } from 'vue';
import { auth } from '../home/auth';
import type { ConsumedDraft } from '../../api/notes';
import { localId } from './localId';
import { draftReceipt } from './draftReceipt';

/** Notes-specific ACK channel. The legacy socket has no request/receipt contract. */
export function useNoteDraftChannel(
  docId: Ref<string>, workspaceId: Ref<string>, device: Ref<string>,
  onSaved: () => void,
  onReceipt: (receipt: ConsumedDraft, lineage: number, sequence: number) => void,
) {
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active = true, dead = false, sequence = 0;
  const owner = auth.me?.id, generation = auth.sessionGeneration;
  type Pending = { base: string; lineage: number; sequence: number; digest: Promise<ConsumedDraft | undefined> };
  const pending = new Map<string, Pending>();
  const allowed = () => active && !dead && !!owner && auth.me?.id === owner && auth.sessionGeneration === generation && !auth.suspended && !auth.sessionClosing;
  function invalidate() { pending.clear(); }
  function disconnect() {
    clearTimeout(timer); timer = undefined; invalidate();
    if (socket) { socket.onmessage = socket.onclose = socket.onerror = socket.onopen = null; socket.close(); }
    socket = null;
  }
  function connect() {
    disconnect();
    if (!allowed() || !docId.value || !workspaceId.value) return;
    const id = docId.value, workspace = workspaceId.value, epoch = auth.requestEpoch;
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/${id}?device=${encodeURIComponent(device.value)}`);
    socket = ws;
    const current = () => allowed() && socket === ws && docId.value === id && workspaceId.value === workspace && auth.requestEpoch === epoch;
    ws.onmessage = async ev => {
      if (!current()) return;
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'doc_saved') { onSaved(); return; }
        if (msg.type !== 'draft_ack' || typeof msg.request_id !== 'string') return;
        const sent = pending.get(msg.request_id);
        if (!sent || msg.base_updated_at !== sent.base || typeof msg.draft_updated_at !== 'string' || !msg.draft_updated_at || !/^[0-9a-f]{64}$/.test(msg.content_hash)) return;
        const digest = await sent.digest;
        if (!current() || pending.get(msg.request_id) !== sent) return;
        pending.delete(msg.request_id);
        if (digest?.content_hash === msg.content_hash) onReceipt({draft_updated_at: msg.draft_updated_at, content_hash: msg.content_hash}, sent.lineage, sent.sequence);
      } catch { /* Malformed frames cannot authorize draft consumption. */ }
    };
    ws.onclose = () => {
      if (!current()) return;
      invalidate(); socket = null;
      timer = setTimeout(connect, 3000);
    };
  }
  function sendDraft(content: string, base: string, lineage: number): boolean {
    if (!allowed() || socket?.readyState !== WebSocket.OPEN) return false;
    const request_id = localId();
    pending.set(request_id, {base, lineage, sequence: ++sequence, digest: draftReceipt(content, 'pending')});
    // Bound memory during a long offline/old-server session; absent ACK is safe.
    if (pending.size > 64) pending.delete(pending.keys().next().value!);
    try { socket.send(JSON.stringify({type:'draft',content,request_id})); return true; }
    catch { pending.delete(request_id); return false; }
  }
  watch(() => [docId.value, workspaceId.value, auth.me?.id, auth.sessionGeneration, auth.requestEpoch, auth.suspended, auth.sessionClosing], connect, {immediate:true,flush:'sync'});
  onDeactivated(() => {active = false; disconnect();});
  onActivated(() => {if (!active && !dead) {active = true; connect();}});
  onBeforeUnmount(() => {dead = true; active = false; disconnect();});
  return {sendDraft, invalidate};
}
