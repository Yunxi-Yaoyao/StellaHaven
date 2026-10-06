// Abortable single-flight lanes; polling counts time from completion, not start.
export function createRequestLane() {
  let controller = new AbortController();
  let pending: Promise<void> | undefined;
  return {
    run(work: (signal: AbortSignal) => Promise<void>): Promise<void> {
      if (pending) return pending;
      const signal = controller.signal;
      const task = Promise.resolve().then(() => { if (!signal.aborted) return work(signal); });
      pending = task;
      void task.finally(() => { if (pending === task) pending = undefined; }).catch(() => {});
      return task;
    },
    reset() { controller.abort(); controller = new AbortController(); pending = undefined; },
  };
}

export function createPoller(work: (signal: AbortSignal) => Promise<void>, intervalMs: number) {
  const lane = createRequestLane();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  let running = false;
  const run = () => lane.run(work).catch(() => { /* retry on next scheduled tick */ });
  const tick = async (g: number) => {
    await run();
    if (running && g === generation) timer = setTimeout(() => void tick(g), intervalMs);
  };
  const stop = () => {
    running = false; generation++;
    if (timer) clearTimeout(timer);
    timer = undefined; lane.reset();
  };
  return {
    run,
    start() { if (running) return; running = true; void tick(++generation); },
    stop,
    reset() { const wasRunning = running; stop(); if (wasRunning) this.start(); },
  };
}

export async function mapBounded<T, R>(items: readonly T[], concurrency: number,
  work: (item: T) => Promise<R>, signal: AbortSignal): Promise<R[]> {
  if (!Number.isInteger(concurrency) || concurrency < 1) throw new RangeError('concurrency must be positive');
  const results: R[] = [];
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (!signal.aborted && cursor < items.length) {
      const index = cursor++;
      results[index] = await work(items[index]!);
    }
  }));
  return results;
}
