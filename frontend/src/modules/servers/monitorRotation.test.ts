import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, ref } from 'vue';
import MonitorChildPicker from './MonitorChildPicker.vue';
import { createMonitorRotation } from './monitorRotation';
let app: ReturnType<typeof createApp> | undefined, host: HTMLElement;
let visible: (entries: any[]) => void;
const disconnect = vi.fn();
async function settle() { for (let i=0;i<8;i++) { await nextTick(); await Promise.resolve(); } }
async function mount(seconds=2) {
  const selected = ref(1);
  host = document.createElement('div'); host.className='mon-card'; document.body.append(host);
  app=createApp({ render: () => h(MonitorChildPicker, {
    modelValue: selected.value, 'onUpdate:modelValue': (id:number)=>{ selected.value=id; }, seconds, parentName:'父监控',
    children: [1,2,3].map(id=>({id,name:`子项 ${id}`,type:'ping',status:'up'})) as any,
  }) }); app.mount(host); await settle(); return selected;
}
const trigger = () => host.querySelector<HTMLButtonElement>('[aria-haspopup]')!;
async function select(id=2) { trigger().click(); await settle(); document.querySelector<HTMLButtonElement>(`[data-child-id="${id}"]`)!.click(); await settle(); }
beforeEach(()=>{
  vi.useFakeTimers(); vi.clearAllMocks(); Object.defineProperty(document,'hidden',{configurable:true,value:false});
  vi.stubGlobal('IntersectionObserver', class { constructor(callback:any) { visible=callback; } observe() {} disconnect=disconnect; });
});
afterEach(()=>{app?.unmount();app=undefined;host?.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
it('holds manual choice until ten quiet seconds, then continues the configured cadence', async()=>{
  const selected=await mount(); await select(); await vi.advanceTimersByTimeAsync(9999); expect(selected.value).toBe(2);
  await vi.advanceTimersByTimeAsync(1);expect(selected.value).toBe(3);await vi.advanceTimersByTimeAsync(2000);expect(selected.value).toBe(1);
});
it.each(['pointermove','pointerdown','keydown','touchstart','touchmove'])('%s activity extends the hold from the latest operation', async event=>{
  const selected=await mount();await select();await vi.advanceTimersByTimeAsync(9000);
  host.dispatchEvent(event==='keydown'?new KeyboardEvent(event,{key:'Shift',bubbles:true}):new Event(event,{bubbles:true}));
  await vi.advanceTimersByTimeAsync(9999);expect(selected.value).toBe(2);await vi.advanceTimersByTimeAsync(1);expect(selected.value).toBe(3);
});
it('neither hover residency nor pointer leave can pin forever or resume early',async()=>{
  const selected=await mount();await select();host.dispatchEvent(new Event('pointermove'));await vi.advanceTimersByTimeAsync(9000);
  host.dispatchEvent(new Event('mouseleave'));await vi.advanceTimersByTimeAsync(999);expect(selected.value).toBe(2);await vi.advanceTimersByTimeAsync(1);expect(selected.value).toBe(3);
});
it('an open menu does not rotate or take focus after twenty idle seconds; Escape closes and restores focus',async()=>{
  const selected=await mount();trigger().dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));await settle();
  expect(document.activeElement?.getAttribute('data-child-id')).toBe('2');await vi.advanceTimersByTimeAsync(20000);expect(selected.value).toBe(1);
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));await settle();expect(document.activeElement?.getAttribute('data-child-id')).toBe('3');
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await settle();expect(trigger().getAttribute('aria-expanded')).toBe('false');expect(document.activeElement).toBe(trigger());
  await vi.advanceTimersByTimeAsync(9999);expect(selected.value).toBe(1);await vi.advanceTimersByTimeAsync(1);expect(selected.value).toBe(2);
});
it('closes on ancestor scroll, but internal menu scrolling preserves focus and delays idle',async()=>{
  const selected=await mount();trigger().click();await settle();document.querySelector('[role="listbox"]')!.dispatchEvent(new Event('scroll'));await settle();expect(trigger().getAttribute('aria-expanded')).toBe('true');
  window.dispatchEvent(new Event('scroll'));await settle();expect(trigger().getAttribute('aria-expanded')).toBe('false');await vi.advanceTimersByTimeAsync(9999);expect(selected.value).toBe(1);
});
it('clears hidden/offscreen timers without catch-up and disconnects on unmount',async()=>{
  const selected=await mount();visible([{isIntersecting:false}]);await vi.advanceTimersByTimeAsync(20000);expect(selected.value).toBe(1);
  visible([{isIntersecting:true}]);await vi.advanceTimersByTimeAsync(1999);expect(selected.value).toBe(1);await vi.advanceTimersByTimeAsync(1);expect(selected.value).toBe(2);
  Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));await vi.advanceTimersByTimeAsync(20000);expect(selected.value).toBe(2);
  Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));await vi.advanceTimersByTimeAsync(2000);expect(selected.value).toBe(3);
  app!.unmount();app=undefined;expect(disconnect).toHaveBeenCalledOnce();await vi.advanceTimersByTimeAsync(20000);expect(selected.value).toBe(3);
});
it('the deadline controller releases every scheduled timeout on menu, suspension, and disposal',()=>{
  const advance=vi.fn(), clock=createMonitorRotation(()=>2000,advance);expect(vi.getTimerCount()).toBe(0);clock.suspend(false);expect(vi.getTimerCount()).toBe(1);
  clock.menu(true);expect(vi.getTimerCount()).toBe(0);clock.activity();expect(vi.getTimerCount()).toBe(0);clock.menu(false);expect(vi.getTimerCount()).toBe(1);
  clock.suspend(true);expect(vi.getTimerCount()).toBe(0);clock.suspend(false);expect(vi.getTimerCount()).toBe(1);clock.dispose();expect(vi.getTimerCount()).toBe(0);
});
it.each([0,-1])('disabled cadence %s does not schedule timers',seconds=>{
  const advance=vi.fn(), clock=createMonitorRotation(()=>seconds*1000,advance);clock.suspend(false);clock.activity();expect(vi.getTimerCount()).toBe(0);clock.dispose();
});
