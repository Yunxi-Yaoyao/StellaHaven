import {it,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import LoginPage from './LoginPage.vue';
import {loginStatus} from './loginStatus';
vi.mock('../home/auth',()=>({register:vi.fn(async()=>undefined),login:vi.fn(async()=>undefined),acceptLogin:vi.fn()}));
let app:ReturnType<typeof createApp>;
afterEach(()=>{app?.unmount();document.body.innerHTML='';vi.unstubAllGlobals();});
it('registration success distinguishes a fresh account; normal login does not reopen first-use',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>new Response('{"initialized":false,"email_enabled":false}')));loginStatus.initialized=false;const events:unknown[]=[];const root=document.createElement('div');document.body.append(root);app=createApp(LoginPage,{onSuccess:(fresh?:boolean)=>events.push(fresh)});app.mount(root);await nextTick();root.querySelector<HTMLButtonElement>('.submit')!.click();await nextTick();root.querySelector<HTMLButtonElement>('.submit')!.click();await new Promise(r=>setTimeout(r,20));expect(events).toEqual([true]);app.unmount();loginStatus.initialized=true;app=createApp(LoginPage,{onSuccess:(fresh?:boolean)=>events.push(fresh)});app.mount(root);root.querySelector<HTMLButtonElement>('.submit')!.click();await new Promise(r=>setTimeout(r,20));expect(events).toEqual([true,false]);});
