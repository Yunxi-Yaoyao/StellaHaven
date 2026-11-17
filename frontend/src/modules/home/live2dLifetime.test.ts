// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLive2dLifetime } from './live2dLifetime';

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('Live2D per-owner lifetime', () => {
  it('releases in reverse order exactly once, including arrivals after disposal', () => {
    const life = createLive2dLifetime(), calls: string[] = [];
    life.defer(() => calls.push('app'));
    life.defer(() => calls.push('model'));
    const cancel = life.defer(() => calls.push('ticker'));
    cancel(); cancel(); life.dispose(); life.dispose();
    life.defer(() => calls.push('late model'));
    expect(life.disposed).toBe(true);
    expect(calls).toEqual(['ticker', 'model', 'app', 'late model']);
  });
  it('still releases model and app if a subscription cleanup throws', () => {
    const life = createLive2dLifetime(), destroy = vi.fn();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    life.defer(destroy); life.defer(() => { throw new Error('observer'); });
    life.dispose(); life.dispose();
    expect(destroy).toHaveBeenCalledTimes(1); expect(warn).toHaveBeenCalledTimes(1);
  });
  it('cancels pending fit frames, fallback timers, long presses and debug intervals', () => {
    vi.useFakeTimers();
    const life = createLive2dLifetime(), callback = vi.fn();
    life.frame(callback); life.timeout(callback, 800); life.timeout(callback, 500); life.interval(callback, 500);
    expect(vi.getTimerCount()).toBe(4);
    life.dispose(); vi.runAllTimers();
    expect(callback).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
  it('forgets completed timers while allowing normal repeated intervals', () => {
    vi.useFakeTimers();
    const life = createLive2dLifetime(), timeout = vi.fn(), frame = vi.fn(), interval = vi.fn();
    life.frame(frame); life.timeout(timeout, 10); life.interval(interval, 50);
    vi.advanceTimersByTime(100);
    expect(frame).toHaveBeenCalledTimes(1); expect(timeout).toHaveBeenCalledTimes(1); expect(interval).toHaveBeenCalledTimes(2);
    life.dispose(); expect(vi.getTimerCount()).toBe(0);
  });
  it('fences already-queued callbacks and refuses scheduling after unmount', () => {
    const life = createLive2dLifetime(), callback = vi.fn();
    let queued!: TimerHandler;
    vi.spyOn(window, 'setTimeout').mockImplementation(fn => { queued = fn; return 7 as unknown as ReturnType<typeof window.setTimeout>; });
    vi.spyOn(window, 'clearTimeout').mockImplementation(() => {});
    life.timeout(callback, 1); life.dispose();
    (queued as () => void)();
    life.timeout(callback, 1); life.interval(callback, 1); life.frame(callback);
    expect(callback).not.toHaveBeenCalled(); expect(window.setTimeout).toHaveBeenCalledTimes(1);
  });
  it('observes outside clicks even when a control stops bubbling, then releases capture', () => {
    const life = createLive2dLifetime(), observed = vi.fn();
    const control = document.createElement('button'); document.body.append(control);
    control.addEventListener('click', event => event.stopPropagation());
    life.listen(window, 'click', observed, true);
    control.click(); expect(observed).toHaveBeenCalledTimes(1);
    life.dispose(); control.click(); expect(observed).toHaveBeenCalledTimes(1);
    control.remove();
  });
  it('detaches listeners from retained canvas and window without touching another owner', () => {
    const first = createLive2dLifetime(), second = createLive2dLifetime();
    const canvas = document.createElement('canvas'), old = vi.fn(), current = vi.fn();
    first.listen(canvas, 'click', old); first.listen(window, 'pointermove', old);
    second.listen(canvas, 'click', current);
    canvas.dispatchEvent(new MouseEvent('click')); expect(old).toHaveBeenCalledTimes(1);
    first.dispose(); canvas.dispatchEvent(new MouseEvent('click')); window.dispatchEvent(new Event('pointermove'));
    expect(old).toHaveBeenCalledTimes(1); expect(current).toHaveBeenCalledTimes(2);
    first.listen(canvas, 'click', old); canvas.dispatchEvent(new MouseEvent('click'));
    expect(old).toHaveBeenCalledTimes(1); second.dispose();
  });
});
