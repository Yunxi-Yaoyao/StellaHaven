/** A single deadline clock: activity holds the current child for ten quiet seconds. */
export function createMonitorRotation(period: () => number, advance: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let due = Date.now() + period(), idleUntil = 0;
  let blocked = false, suspended = true, disposed = false;
  const clear = () => { if (timer !== undefined) clearTimeout(timer); timer = undefined; };
  function schedule() {
    clear();
    if (disposed || suspended || blocked || period() <= 0) return;
    timer = setTimeout(() => {
      timer = undefined;
      advance();
      idleUntil = 0;
      due = Date.now() + period();
      schedule();
    }, Math.max(0, Math.max(due, idleUntil) - Date.now()));
  }
  return {
    activity() { idleUntil = due = Date.now() + 10_000; schedule(); },
    menu(open: boolean) { blocked = open; schedule(); },
    suspend(value: boolean) {
      if (suspended === value) return;
      suspended = value;
      if (!value) due = Math.max(Date.now() + period(), idleUntil);
      schedule();
    },
    reset() { due = Date.now() + period(); schedule(); },
    dispose() { disposed = true; clear(); },
  };
}
