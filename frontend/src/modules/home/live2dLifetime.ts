// One widget owns only its subscriptions/resources, never the shared Pixi ticker.
export function createLive2dLifetime() {
  let disposed = false;
  const cleanups = new Set<() => void>();
  const defer = (cleanup: () => void) => {
    let pending = true;
    const release = () => {
      if (!pending) return;
      pending = false;
      cleanups.delete(release);
      cleanup();
    };
    if (disposed) release();
    else cleanups.add(release);
    return release;
  };
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    // Remove subscriptions before destroying model/app (reverse acquisition order).
    const errors: unknown[] = [];
    for (const release of [...cleanups].reverse()) {
      try { release(); } catch (error) { errors.push(error); }
    }
    if (errors.length) console.warn('Live2D cleanup failed', errors);
  };
  const timeout = (callback: () => void, delay: number) => {
    if (disposed) return () => {};
    const id = window.setTimeout(() => { cancel(); if (!disposed) callback(); }, delay);
    const cancel = defer(() => window.clearTimeout(id));
    return cancel;
  };
  const interval = (callback: () => void, delay: number) => {
    if (disposed) return;
    const id = window.setInterval(() => { if (!disposed) callback(); }, delay);
    defer(() => window.clearInterval(id));
  };
  const frame = (callback: () => void) => {
    if (disposed) return;
    const id = window.requestAnimationFrame(() => { cancel(); if (!disposed) callback(); });
    const cancel = defer(() => window.cancelAnimationFrame(id));
  };
  const listen = <K extends keyof HTMLElementEventMap>(
    target: HTMLElement | Window, type: K, callback: (event: HTMLElementEventMap[K]) => void, capture = false,
  ) => {
    if (disposed) return;
    const listener = ((event: Event) => { if (!disposed) callback(event as HTMLElementEventMap[K]); }) as EventListener;
    target.addEventListener(type, listener, capture);
    defer(() => target.removeEventListener(type, listener, capture));
  };
  return { get disposed() { return disposed; }, defer, dispose, timeout, interval, frame, listen };
}
