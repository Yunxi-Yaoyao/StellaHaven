import {afterEach, expect, it, vi} from 'vitest';
import {createApp, h, nextTick, ref} from 'vue';
import Picker from './MonitorChildPicker.vue';
let app:ReturnType<typeof createApp>|undefined, host:HTMLElement;
async function settle(){for(let i=0;i<8;i++)await nextTick();}
afterEach(()=>{app?.unmount();host?.remove();vi.restoreAllMocks();});
it('escapes clipping ancestors while retaining option clicks, focus, scrolling and keyboard ownership',async()=>{
 vi.spyOn(HTMLElement.prototype,'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
 const value=ref(1);host=document.createElement('div');host.style.overflow='hidden';document.body.append(host);
 app=createApp({render:()=>h('div',[h(Picker,{modelValue:value.value,'onUpdate:modelValue':(id:number)=>value.value=id,children:[1,2,3].map(id=>({id,name:'监控 '+id,type:'ping',status:'up'})) as any,seconds:0,parentName:'组'}),h('button',{id:'after-picker'},'之后')])});app.mount(host);await settle();
 const trigger=host.querySelector<HTMLButtonElement>('[aria-haspopup]')!;trigger.click();await settle();
 const list=document.querySelector<HTMLElement>('[role=listbox]')!;
 expect(list).toBeTruthy();expect(host.contains(list),'floating list must escape clipping card').toBe(false);
 expect(document.activeElement?.getAttribute('data-child-id')).toBe('2');
 Object.defineProperty(list,'clientHeight',{value:60});
 const last=list.querySelector<HTMLButtonElement>('[data-child-id="3"]')!;
 Object.defineProperties(last,{offsetTop:{value:100},offsetHeight:{value:44}});
 document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));await settle();
 expect(list.scrollTop,'keyboard navigation reveals the option inside the menu only').toBe(84);
 list.dispatchEvent(new Event('scroll'));await settle();expect(trigger.getAttribute('aria-expanded')).toBe('true');
 list.querySelector<HTMLButtonElement>('[data-child-id="3"]')!.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));await settle();expect(trigger.getAttribute('aria-expanded')).toBe('true');
 list.querySelector<HTMLButtonElement>('[data-child-id="3"]')!.click();await settle();expect(value.value).toBe(3);expect(document.activeElement).toBe(trigger);
 trigger.click();await settle();document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));await settle();expect(document.activeElement?.id).toBe('after-picker');expect(trigger.getAttribute('aria-expanded')).toBe('false');
 trigger.click();await settle();document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));await settle();expect(document.activeElement).toBe(trigger);
 trigger.click();await settle();document.body.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));await settle();expect(trigger.getAttribute('aria-expanded')).toBe('false');expect(document.activeElement).toBe(trigger);
 trigger.click();await settle();window.dispatchEvent(new Event('scroll'));await settle();expect(trigger.getAttribute('aria-expanded')).toBe('false');
});
it.each(['open','outside'])('unmount disposes the %s portal, pending frames, observers and global listeners',async state=>{
 vi.useFakeTimers();
 const disconnect=vi.fn();vi.stubGlobal('ResizeObserver',class{observe(){}disconnect=disconnect;});
 const removeWindow=vi.spyOn(window,'removeEventListener'),removeDocument=vi.spyOn(document,'removeEventListener');
 try{
  host=document.createElement('div');document.body.append(host);
  app=createApp({render:()=>h(Picker,{modelValue:1,children:[1,2].map(id=>({id,name:'监控 '+id,type:'ping',status:'up'})) as any,seconds:0,parentName:'组'})});app.mount(host);
  host.querySelector<HTMLButtonElement>('button')!.click();await settle();expect(vi.getTimerCount()).toBeGreaterThan(0);
  if(state==='outside')document.body.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true}));
  app.unmount();app=undefined;
  // Vue Transition owns two enter/leave RAFs independently of the picker.
  await vi.advanceTimersByTimeAsync(500);
  expect(document.querySelector('.mon-picker-layer')).toBeNull();expect(vi.getTimerCount()).toBe(0);expect(disconnect).toHaveBeenCalledOnce();
  for(const event of ['scroll','resize'])expect(removeWindow.mock.calls.some(([name])=>name===event)).toBe(true);
  for(const event of ['pointerdown','visibilitychange'])expect(removeDocument.mock.calls.some(([name])=>name===event)).toBe(true);
 }finally{vi.unstubAllGlobals();vi.useRealTimers();}
});
