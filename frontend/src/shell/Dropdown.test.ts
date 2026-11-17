import {createApp,nextTick,type App} from 'vue';
import {it,expect,afterEach} from 'vitest';
import Dropdown from './Dropdown.vue';
let app:App;afterEach(()=>{app?.unmount();document.body.innerHTML='';});
it('supports keyboard selection, Escape and focus return on the shared dropdown',async()=>{
 const root=document.createElement('div');document.body.append(root);let picked:unknown;
 app=createApp(Dropdown,{modelValue:'one',options:[{value:'one',label:'一'},{value:'two',label:'二'}],'onUpdate:modelValue':(v:unknown)=>picked=v});app.mount(root);await nextTick();
 const trigger=root.querySelector<HTMLButtonElement>('.dd-btn')!;trigger.focus();trigger.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));await nextTick();
 expect(trigger.getAttribute('aria-expanded')).toBe('true');expect(document.activeElement?.textContent).toContain('一');
 document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));await nextTick();expect(document.activeElement?.textContent).toContain('二');
 (document.activeElement as HTMLButtonElement).click();await nextTick();expect(picked).toBe('two');expect(document.activeElement).toBe(trigger);
 trigger.click();await nextTick();trigger.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await nextTick();expect(trigger.getAttribute('aria-expanded')).toBe('false');await new Promise(r=>setTimeout(r,200));expect(root.querySelector('.dd-menu')).toBeNull();expect(document.activeElement).toBe(trigger);
});
