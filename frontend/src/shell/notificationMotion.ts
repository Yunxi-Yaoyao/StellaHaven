/** One live surface; never clone notification content into a second DOM tree. */
export interface NotificationOrigin {
  element: HTMLElement;
  rect: Pick<DOMRectReadOnly, 'left' | 'top' | 'width' | 'height'>;
  panel: HTMLElement;
}
const DURATION = 240;
const easing = 'cubic-bezier(.22,.7,.2,1)';
type Box = NotificationOrigin['rect'];
type Appearance = {backdrop: string; panel: string; content: string};
function visibleOrigin(origin: NotificationOrigin): Box | undefined {
  if (!origin.element.isConnected || !origin.panel.isConnected) return;
  const r = origin.element.getBoundingClientRect(), p = origin.panel.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0 || r.left < 0 || r.right > innerWidth ||
      r.top < Math.max(0, p.top) || r.bottom > Math.min(innerHeight, p.bottom)) return;
  // A scroll/reflow must not send the surface back to a stale position.
  if ((['left', 'top', 'width', 'height'] as const).some(k => Math.abs(r[k] - origin.rect[k]) > 2)) return;
  return r;
}
function transform(from: Box, to: Box) {
  return `translate(${from.left-to.left}px, ${from.top-to.top}px) scale(${from.width/to.width}, ${from.height/to.height})`;
}
export function notificationMotion(surface: HTMLElement, mask: HTMLElement, content: HTMLElement, origin: NotificationOrigin) {
  // Static environments keep content and immediate close; no partial animation setup.
  if (!surface.animate || typeof matchMedia !== 'function' || typeof ResizeObserver !== 'function') {
    return {open() {}, close: async () => true, settle() {}, dispose() {}};
  }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const backdrop = getComputedStyle(mask).backgroundColor;
  let animations: Animation[] = [], opening: Animation | undefined;
  let generation = 0, closing = false;
  let base: Box = surface.getBoundingClientRect();
  function cancel() {
    generation++;
    opening = undefined;
    animations.forEach(a => a.cancel());
    animations = [];
  }
  function play(el: HTMLElement, frames: Keyframe[], duration: number) {
    const a = el.animate(frames, {duration, easing, fill:'both'});
    animations.push(a);
    return a;
  }
  function appearance(): Appearance {
    return {backdrop:getComputedStyle(mask).backgroundColor, panel:getComputedStyle(origin.panel).opacity, content:getComputedStyle(content).opacity};
  }
  function currentBox(): Box {
    // ResizeObserver precedes paint. Retain the last intrinsic box instead of
    // multiplying newly loaded content by the previous FLIP scale (a jump).
    const m = new DOMMatrixReadOnly(getComputedStyle(surface).transform);
    return {left:base.left+m.e, top:base.top+m.f, width:base.width*m.a, height:base.height*m.d};
  }
  function open(from = visibleOrigin(origin), duration = DURATION, current?: Appearance) {
    cancel();
    base = surface.getBoundingClientRect();
    const token = generation;
    const move = opening = play(surface, reduced.matches || !from
      ? [{opacity:.8}, {opacity:1}]
      : [{transform:transform(from, base), borderRadius:'8px'}, {transform:'none', borderRadius:'14px'}], duration);
    play(mask, [{backgroundColor:current?.backdrop ?? 'transparent'}, {backgroundColor:backdrop}], duration);
    play(content, [{opacity:current?.content ?? '.4'}, {opacity:1}], duration);
    play(origin.panel, [{opacity:current?.panel ?? '1'}, {opacity:0}], duration);
    void move.finished.then(() => {
      if (token !== generation) return;
      opening = undefined;
      move.cancel();
      base = surface.getBoundingClientRect();
    }, () => {});
  }
  const observer = new ResizeObserver(() => {
    // Use the actual WAAPI clock, not elapsed wall time: rendering can be
    // paused/throttled. A settled resize must never resurrect an opening.
    const active = opening;
    if (closing || !active || active.playState === 'finished') return;
    const remaining = Number(active.effect?.getTiming().duration) - Number(active.currentTime ?? 0);
    if (remaining <= 0) return;
    const r = surface.getBoundingClientRect();
    const m = new DOMMatrixReadOnly(getComputedStyle(surface).transform);
    if (Math.abs(r.width/m.a-base.width) < 1 && Math.abs(r.height/m.d-base.height) < 1) return;
    const from = currentBox(), current = appearance();
    open(from, remaining, current);
  });
  observer.observe(surface);
  async function close() {
    if (closing) return false;
    closing = true;
    observer.disconnect();
    // Capture every visible property before cancel removes the opening effect.
    const from = surface.getBoundingClientRect(), current = appearance();
    const opacity = getComputedStyle(surface).opacity, target = visibleOrigin(origin);
    cancel();
    base = surface.getBoundingClientRect();
    const token = generation;
    const move = play(surface, reduced.matches || !target
      ? [{opacity}, {opacity:0}]
      : [{transform:transform(from, base)}, {transform:transform(target, base), borderRadius:'8px'}], DURATION);
    play(mask, [{backgroundColor:current.backdrop}, {backgroundColor:'transparent'}], DURATION);
    play(content, [{opacity:current.content}, {opacity:0}], DURATION);
    play(origin.panel, [{opacity:current.panel}, {opacity:1}], DURATION);
    try { await move.finished; } catch { return false; }
    return token === generation;
  }
  function settle() {
    if (closing) animations.forEach(a => a.finish());
    else {
      cancel();
      base = surface.getBoundingClientRect();
      play(origin.panel, [{opacity:0}, {opacity:0}], 0);
    }
  }
  function dispose() {
    observer.disconnect();
    reduced.removeEventListener('change', settle);
    cancel();
  }
  reduced.addEventListener('change', settle);
  return {open, close, settle, dispose};
}
