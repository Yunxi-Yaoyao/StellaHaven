import { onBeforeUnmount, watch } from 'vue';
import { auth } from '../home/auth';

export type ImportCheck = (() => void) & { signal: AbortSignal };
export const importStoppedMessage = '导入已暂停：登录或窗口已变化，未确认结果保留原标识。请以原账号明确重试，不会自动继续。';
export function isImportAbort(error: unknown): boolean {
  return !!error && typeof error === 'object' && 'name' in error && error.name === 'AbortError';
}

export function importErrorMessage(error: unknown, fallback = '导入失败'): string {
  if (isImportAbort(error)) return importStoppedMessage;
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string') return error.message;
  return fallback;
}

/** A mounted queue belongs to one owner. Only an explicit action captures a new session. */
export function useImportSession() {
  const owner = auth.me?.id;
  let disposed = false, replaced = false, revision = 0;
  let controller: AbortController | undefined;
  watch(() => [auth.me?.id, auth.sessionGeneration, auth.requestEpoch, auth.suspended, auth.sessionClosing], (next, previous) => {
    // Silent refresh may replace the Me object without changing this session.
    if (next.every((value, index) => value === previous[index])) return;
    revision++;
    controller?.abort();
    if (auth.me?.id && auth.me.id !== owner) replaced = true;
  }, { flush: 'sync' });
  onBeforeUnmount(() => { disposed = true; revision++; controller?.abort(); });
  function capture(): ImportCheck {
    const generation = auth.sessionGeneration, epoch = auth.requestEpoch, capturedRevision = revision;
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    return Object.assign(() => {
      if (signal.aborted || !owner || disposed || replaced || auth.me?.id !== owner || auth.suspended || auth.sessionClosing
        || generation !== auth.sessionGeneration || epoch !== auth.requestEpoch || revision !== capturedRevision) {
        throw new DOMException(importStoppedMessage, 'AbortError');
      }
    }, { signal });
  }
  return { capture, alive: () => !disposed };
}
