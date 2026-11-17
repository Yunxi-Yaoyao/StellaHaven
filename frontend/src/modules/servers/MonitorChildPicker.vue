<script setup lang="ts">
// Reuses TemplatePicker's roving-focus listbox interaction, scoped to monitoring.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue';
import type { Monitor } from '../../api/servers';
import {monitorStatusLabel,monitorStatusReason} from './monitorStatusLabel';
import { createMonitorRotation } from './monitorRotation';
const props = defineProps<{ modelValue: number; children: Monitor[]; seconds: number; parentName: string; compact?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [id: number] }>();
const open = ref(false), root = ref<HTMLElement>(), trigger = ref<HTMLButtonElement>(), list = ref<HTMLElement>();
const layer = ref<HTMLElement>();
const id = useId();
const selected = computed(() => props.children.find(c => c.id === props.modelValue));
const others = computed(() => props.children.filter(c => c.id !== props.modelValue));
const rotation = createMonitorRotation(() => props.children.length > 1 ? props.seconds * 1000 : 0, () => {
  const index = props.children.findIndex(c => c.id === props.modelValue);
  const child = props.children[(index + 1) % props.children.length];
  if (child) emit('update:modelValue', child.id);
});
function activity() { rotation.activity(); }
// Measure a known-size portal, not the card: CSS zoom on body/html changes the
// mapping between fixed CSS coordinates and getBoundingClientRect's viewport.
function position() {
  const menu = list.value, anchor = trigger.value, portal = layer.value;
  if (!open.value || !menu || !anchor || !portal) return;
  const origin = portal.getBoundingClientRect(), scale = origin.width / 100 || 1;
  const viewport = window.visualViewport;
  const left = (viewport?.offsetLeft || 0) + 8, top = (viewport?.offsetTop || 0) + 8;
  const right = left + (viewport?.width || window.innerWidth) - 16;
  const bottom = top + (viewport?.height || window.innerHeight) - 16;
  Object.assign(menu.style, { maxWidth: `${Math.min(340, Math.max(0, right - left) / scale)}px`, maxHeight: '260px' });
  const a = anchor.getBoundingClientRect(), m = menu.getBoundingClientRect();
  const below = Math.max(0, bottom - a.bottom - 4), above = Math.max(0, a.top - top - 4);
  const up = below < m.height && above > below;
  menu.style.maxHeight = `${Math.min(260, (up ? above : below) / scale)}px`;
  const height = menu.getBoundingClientRect().height;
  const x = Math.max(left, Math.min(a.left, right - m.width));
  const y = Math.max(top, Math.min(up ? a.top - 4 - height : a.bottom + 4, bottom - height));
  Object.assign(menu.style, { left: `${(x - origin.left) / scale}px`, top: `${(y - origin.top) / scale}px`, visibility: 'visible' });
}
let frame = 0, outsideFrame = 0;
let lastGeometry = '';
function trackPosition() {
  frame = 0;
  if (!open.value || !trigger.value || !layer.value) return;
  const a = trigger.value.getBoundingClientRect(), p = layer.value.getBoundingClientRect();
  const geometry = [a.x, a.y, a.width, a.height, p.x, p.y, p.width].join(',');
  // Size observers miss position-only shifts (e.g. a sibling chart resolving).
  // Read only while open; write layout only when geometry actually changes.
  if (geometry !== lastGeometry) { lastGeometry = geometry; position(); }
  frame = requestAnimationFrame(trackPosition);
}
function reposition() {
  lastGeometry = '';
  if (open.value && !frame) frame = requestAnimationFrame(trackPosition);
}
function close(focus = false) {
  if (!open.value) return;
  open.value = false; rotation.menu(false); activity();
  cancelAnimationFrame(frame); frame = 0;
  if (focus) trigger.value?.focus({ preventScroll: true });
}
function focusItem(item?: HTMLButtonElement) {
  if (!item || !list.value) return;
  item.focus({ preventScroll: true });
  const menu = list.value;
  if (item.offsetTop < menu.scrollTop) menu.scrollTop = item.offsetTop;
  else if (item.offsetTop + item.offsetHeight > menu.scrollTop + menu.clientHeight)
    menu.scrollTop = item.offsetTop + item.offsetHeight - menu.clientHeight;
}
async function show(last = false) {
  if (!others.value.length) return;
  cancelAnimationFrame(outsideFrame); outsideFrame = 0;
  activity(); open.value = true; rotation.menu(true); await nextTick();
  if (!open.value) return;
  position(); reposition();
  const items = list.value?.querySelectorAll<HTMLButtonElement>('button');
  focusItem(items?.[last ? items.length - 1 : 0]);
}
function pick(value: number) { emit('update:modelValue', value); close(true); }
function key(event: KeyboardEvent) {
  activity();
  if (event.isComposing) return;
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close(true); return; }
  if (event.key === 'Tab' && open.value) {
    // The portal is last in body, but Tab must follow the trigger's original
    // document order. Shift+Tab returns to the trigger, never into the portal.
    if (list.value?.contains(event.target as Node)) {
      const items = [...document.querySelectorAll<HTMLElement>('a[href],button,input,select,textarea,[tabindex]')]
        .filter(el => el.tabIndex >= 0 && !el.matches(':disabled') && !el.closest('[inert],[hidden]') && !layer.value?.contains(el) && el.getClientRects().length);
      const next = event.shiftKey ? trigger.value : items[items.indexOf(trigger.value!) + 1];
      if (next) { event.preventDefault(); next.focus({ preventScroll: true }); }
    }
    close(); return;
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  if (!open.value) { void show(event.key === 'ArrowUp' || event.key === 'End'); return; }
  const items = [...(list.value?.querySelectorAll<HTMLButtonElement>('button') || [])];
  const index = items.indexOf(document.activeElement as HTMLButtonElement);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
  focusItem(items[next]);
}
function contains(target: EventTarget | null) { return target instanceof Node && (root.value?.contains(target) || layer.value?.contains(target)); }
function outside(event: PointerEvent) {
  if (!open.value || contains(event.target)) return;
  close(true);
  // A blank-area pointer's default action can blur the restored trigger after
  // pointerdown. Restore after that action, but never steal another control's focus.
  outsideFrame = requestAnimationFrame(() => {
    outsideFrame = 0;
    if (document.activeElement === document.body) trigger.value?.focus({ preventScroll: true });
  });
}
function focusout(event: FocusEvent) { if (!contains(event.relatedTarget)) close(); }
let visible = true, observer: IntersectionObserver | undefined, resizeObserver: ResizeObserver | undefined, card: HTMLElement | null = null;
function visibility() { if (document.hidden) close(); rotation.suspend(document.hidden || !visible); }
function scroll(event: Event) {
  // The list may scroll internally without closing; an ancestor scroll invalidates its anchor.
  if (contains(event.target)) { activity(); return; }
  close();
}
const activityEvents = ['pointerdown', 'pointermove', 'keydown', 'touchstart', 'touchmove', 'focusin'] as const;
onMounted(() => {
  card = root.value?.closest('.mon-card') || root.value || null;
  for (const event of activityEvents) card?.addEventListener(event, activity, { passive: true });
  document.addEventListener('pointerdown', outside);
  document.addEventListener('visibilitychange', visibility);
  window.addEventListener('scroll', scroll, true);
  window.addEventListener('resize', reposition);
  window.visualViewport?.addEventListener('resize', reposition);
  window.visualViewport?.addEventListener('scroll', reposition);
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(reposition);
    for (const el of [trigger.value, document.body]) if (el) resizeObserver.observe(el);
  }
  if (typeof IntersectionObserver !== 'undefined' && card) {
    observer = new IntersectionObserver(entries => { visible = !!entries[0]?.isIntersecting; if (!visible) close(); visibility(); });
    observer.observe(card);
  }
  visibility();
});
watch([() => props.seconds, () => props.children.map(c => c.id).join(',')], () => rotation.reset());
watch(others, () => { if (!others.value.length) close(); else void nextTick(reposition); });
onBeforeUnmount(() => {
  rotation.dispose(); observer?.disconnect(); resizeObserver?.disconnect(); cancelAnimationFrame(frame); cancelAnimationFrame(outsideFrame);
  for (const event of activityEvents) card?.removeEventListener(event, activity);
  document.removeEventListener('pointerdown', outside);
  document.removeEventListener('visibilitychange', visibility);
  window.removeEventListener('scroll', scroll, true);
  window.removeEventListener('resize', reposition);
  window.visualViewport?.removeEventListener('resize', reposition);
  window.visualViewport?.removeEventListener('scroll', reposition);
});
</script>
<template>
  <div ref="root" class="mon-child-picker" :class="{compact}" @click.stop @keydown="key" @focusout="focusout">
    <button ref="trigger" type="button" class="mon-child-trigger" :disabled="!others.length" :aria-label="`${parentName}：${selected?.name || '未选择监控项'}，选择监控项`" :title="selected?.name" aria-haspopup="listbox" :aria-controls="id" :aria-expanded="open" @click="open ? close() : show()">
      <span class="mon-child-label-stack"><Transition name="mon-selection"><span :key="modelValue" class="mon-child-label">{{ selected?.name || '未选择监控项' }}</span></Transition></span>
      <svg aria-hidden="true" class="mon-child-chevron" :class="{open}" width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="m6 3 5 5-5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
      <slot />
    </button>
    <Teleport to="body">
    <div ref="layer" class="mon-picker-layer" @click.stop @keydown="key" @focusout="focusout" @pointerdown="activity" @pointermove="activity" @touchstart.passive="activity" @touchmove.passive="activity" @focusin="activity">
    <Transition name="mon-menu">
      <div v-if="open" :id="id" ref="list" class="mon-child-menu" role="listbox" :aria-label="`${parentName}的其他监控项`">
        <button v-for="child in others" :key="child.id" type="button" role="option" aria-selected="false" :data-child-id="child.id" :title="child.name" @click="pick(child.id)"><span class="option-name">{{ child.name }}</span><small>{{ child.type }} · {{monitorStatusLabel(child)}}<template v-if="monitorStatusReason(child)"> · {{monitorStatusReason(child)}}</template></small></button>
      </div>
    </Transition>
    </div>
    </Teleport>
  </div>
</template>
<style scoped>
.mon-child-picker { position: relative; align-self: flex-start; max-width: 100%; min-width: 0; }
.mon-child-trigger { display: flex; align-items: center; gap: 8px; max-width: 100%; min-height: 40px; padding: 6px 0; border: none; background: transparent; color: var(--text-hi); font: inherit; font-size: 13px; cursor: pointer; }
.compact .mon-child-trigger { width:100%;min-height:27px;padding:0;gap:6px; }
.compact .mon-child-label-stack { flex:0 1 auto;max-width:55%;width:max-content;min-width:56px;overflow:hidden; }
.compact .mon-child-chevron { width:12px;height:12px;transform:none; }
.compact .mon-child-chevron.open { transform:rotate(90deg); }
.mon-child-trigger:disabled { cursor: default; }
.mon-child-trigger:disabled .mon-child-chevron { visibility: hidden; }
.mon-child-label-stack { display: grid; min-width: 0; }
.mon-child-label { grid-area: 1/1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mon-child-chevron { flex: none; transition: transform 180ms ease; }
.mon-child-chevron.open { transform: rotate(90deg); }
/* Above shell edge handles at 87 (portal paints later), below drawer mask 88. */
.mon-picker-layer { position: fixed; top: 0; left: 0; width: 100px; height: 0; z-index: 87; pointer-events: none; }
.mon-child-menu { position: absolute; visibility: hidden; pointer-events: auto; box-sizing: border-box; width: max-content; min-width: 0; max-width: 340px; max-height: 260px; overflow: auto; overscroll-behavior: contain; padding: 4px; background: var(--bg-panel); border: 1px solid var(--accent-dim); border-radius: 8px; box-shadow: 0 8px 24px #0006; }
.mon-child-menu button { display: flex; flex-direction: column; gap: 3px; width: 100%; min-height: 44px; border: none; border-radius: 4px; background: transparent; color: var(--text-hi); text-align: left; font: inherit; font-size: 13px; padding: 7px 10px; cursor: pointer; }
.option-name { display: block; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mon-child-menu small { color: var(--text-lo); font-size: 12px; overflow-wrap: anywhere; }
.mon-child-menu button:hover { background: var(--bg-raised); }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.mon-selection-enter-active,.mon-selection-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.mon-menu-enter-active,.mon-menu-leave-active { transition: opacity 180ms ease; }
.mon-menu-leave-active { pointer-events: none; }
.mon-selection-enter-from { opacity: 0; transform: translateX(6px); }
.mon-selection-leave-to { opacity: 0; transform: translateX(-6px); }
.mon-menu-enter-from,.mon-menu-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .mon-selection-enter-active,.mon-selection-leave-active,.mon-menu-enter-active,.mon-menu-leave-active,.mon-child-chevron { transition: none; } }
</style>
