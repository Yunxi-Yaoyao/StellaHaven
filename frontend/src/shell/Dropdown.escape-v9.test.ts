import {afterEach,expect,it} from 'vitest';
import {createApp,h,nextTick,type App} from 'vue';
import Dropdown from './Dropdown.vue';
let app:App|undefined,host:HTMLElement;
afterEach(()=>{app?.unmount();host?.remove();});
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Dropdown,{modelValue:'a',options:[{value:'a',label:'A'},{value:'b',label:'B'}]})});app.mount(host);await nextTick();return host.querySelector('button')!;}
it('closed dropdown lets Escape reach the enclosing dialog',async()=>{const trigger=await mount();let bubbled=false;host.addEventListener('keydown',()=>bubbled=true);const e=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});trigger.dispatchEvent(e);expect(e.defaultPrevented).toBe(false);expect(bubbled).toBe(true);});
it('open dropdown consumes the first Escape and restores trigger focus',async()=>{const trigger=await mount();trigger.click();await nextTick();let bubbled=false;host.addEventListener('keydown',()=>bubbled=true);const e=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});trigger.dispatchEvent(e);await nextTick();expect(e.defaultPrevented).toBe(true);expect(bubbled).toBe(false);expect(trigger.getAttribute('aria-expanded')).toBe('false');expect(document.activeElement).toBe(trigger);});
