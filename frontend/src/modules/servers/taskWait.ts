/** A page timeout does not imply that the remote task failed or stopped. */
export class TaskWaitTimeoutError extends Error {
  constructor() { super('页面等待超时；任务可能仍在运行，请稍后查看'); this.name = 'TaskWaitTimeoutError'; }
}

/** Finite tasks only. A timed-out request is aborted and never retried, so even
 * an uncooperative transport cannot overlap another request from this waiter. */
export async function waitForTask<T extends { status: string }>(
  read: (signal: AbortSignal) => Promise<T | undefined>,
  options: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number; requestTimeoutMs?: number; maxTransientErrors?: number } = {},
): Promise<T> {
  const deadline = performance.now() + (options.timeoutMs ?? 40000);
  const signal = options.signal;
  let errors = 0;
  const check = () => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (performance.now() >= deadline) throw new TaskWaitTimeoutError();
  };
  const bounded = async <R>(operation: (s: AbortSignal) => Promise<R>, ms: number): Promise<R> => {
    check();
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let abort = () => {};
    try {
      return await Promise.race([
        new Promise<never>((_, reject) => {
          abort = () => { controller.abort(); reject(new DOMException('Aborted', 'AbortError')); };
          signal?.addEventListener('abort', abort, { once: true });
          timer = setTimeout(() => { controller.abort(); reject(new TaskWaitTimeoutError()); }, Math.max(0, Math.min(ms, deadline - performance.now())));
        }),
        Promise.resolve().then(() => { check(); return operation(controller.signal); }),
      ]);
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  };
  for (;;) {
    check();
    let task: T | undefined;
    try { task = await bounded(read, options.requestTimeoutMs ?? 15000); }
    catch (e) {
      check();
      const status = (e as { status?: number })?.status;
      if (e instanceof TaskWaitTimeoutError || (e as Error)?.name === 'AbortError' ||
        (status != null && status >= 400 && status < 500 && status !== 408 && status !== 429) ||
        ++errors > (options.maxTransientErrors ?? 2)) throw e;
    }
    check();
    if (task && ['done', 'failed', 'cancelled'].includes(task.status)) return task;
    // Bounded, abortable delay, with no timer or listener left on cancellation.
    await bounded(s => new Promise<void>((resolve) => {
      const timer = setTimeout(() => { s.removeEventListener('abort', cancel); resolve(); }, options.intervalMs ?? 2000);
      const cancel = () => clearTimeout(timer);
      s.addEventListener('abort', cancel, { once: true });
    }), deadline - performance.now());
  }
}
