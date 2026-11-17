import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import {defaults} from './controller';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
vi.mock('../home/auth',async()=>{const {reactive,computed,ref}=await import('vue');const auth=reactive({me:{id:'review-owner'},sessionGeneration:1,requestEpoch:1});return {auth,loggedIn:computed(()=>!!auth.me),displayBg:ref('')};});
vi.mock('../../stores/navigation',()=>({navigation:{modules:[]}}));
vi.mock('../home/backgroundMedia',async()=>{const {ref}=await import('vue');return {useBackgroundMedia:()=>({source:ref(''),poster:ref('')})};});
vi.mock('../../composables/useToast',()=>({toast:vi.fn()}));
import Page from './NavPage.vue';
let app:ReturnType<typeof createApp>|undefined,host:HTMLDivElement|undefined;
const clone=(v:any)=>JSON.parse(JSON.stringify(v));
const flush=async()=>{for(let i=0;i<15;i++)await nextTick();};
beforeEach(()=>{mocks.api.mockReset();HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open')};});
afterEach(()=>{app?.unmount();host?.remove();app=undefined;host=undefined;});
it('review R1: editable slow-save draft stays open with saved-snapshot notice and saves again against ACK revision',async()=>{
 let server={revision:0,data:defaults()},release!:(x:any)=>void,pending:any,writes=0;
 mocks.api.mockImplementation(async(path:string,o?:RequestInit)=>{
  if(path==='/nav-assets')return [];
  if(o?.method==='PUT'){writes++;pending=JSON.parse(o.body as string);if(writes===1)return await new Promise(r=>release=r);expect(pending.revision).toBe(1);server={revision:2,data:pending.data};return clone(server);}
  if(path==='/nav-data')return clone(server);
  throw new Error('unexpected '+path);
 });
 host=document.createElement('div');document.body.append(host);app=createApp(Page);app.use(createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]}));app.mount(host);await flush();
 (host.querySelector('[aria-label="导航设置"]') as HTMLButtonElement).click();await flush();
 const input=Array.from(host.querySelectorAll('label')).find(x=>x.textContent==='导航标题')!.querySelector('input')!;
 input.value='sent-A';input.dispatchEvent(new Event('input',{bubbles:true}));await flush();
 host.querySelector('dialog form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 expect(pending.data.preferences.title).toBe('sent-A');expect(input.disabled).toBe(false);
 input.value='newer-B';input.dispatchEvent(new Event('input',{bubbles:true}));await flush();
 server={revision:1,data:pending.data};release(clone(server));await flush();
 expect(host.querySelector('dialog')!.hasAttribute('open')).toBe(true);expect(input.value).toBe('newer-B');
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('先前快照已保存');
 expect((host.querySelector('footer button[type=submit]') as HTMLButtonElement).disabled).toBe(false);
 host.querySelector('dialog form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 expect(writes).toBe(2);expect(server.data.preferences.title).toBe('newer-B');expect(host.querySelector('dialog')!.hasAttribute('open')).toBe(false);
});
