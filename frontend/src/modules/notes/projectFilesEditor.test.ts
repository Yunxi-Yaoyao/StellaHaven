import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,h,nextTick,ref,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {webcrypto} from 'node:crypto';
import DocEditor from './DocEditor.vue';
import {auth} from '../home/auth';
import {useNotesStore} from '../../stores/notes';
import {PROJECT_ASSET_MIME} from './projectAssetCopy';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1}),refreshAccess:vi.fn(async()=>false)}));
vi.mock('vue-router',()=>({useRoute:()=>({hash:'',query:{}}),useRouter:()=>({push:vi.fn()})}));
vi.mock('./CmEditor.vue',async()=>({default:(await import('vue')).defineComponent({props:['modelValue'],emits:['update:modelValue'],setup:(p,{emit})=>()=>h('textarea',{'data-body':'',value:p.modelValue,onInput:(e:any)=>emit('update:modelValue',e.target.value)})})}));
let app:App,host:HTMLElement,row:any,copies:any[],puts:any[],lost:boolean,gate:Promise<Response>|null;
let copySignals:(AbortSignal|null|undefined)[];
const editor=ref<any>(null),selected=ref('one');
const root='10000000-0000-4000-8000-000000000001',file='10000000-0000-4000-8000-000000000002',aid='20000000-0000-4000-8000-000000000001';
const response=(data:any)=>new Response(JSON.stringify(data),{status:200,headers:{'content-type':'application/json'}});
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();await nextTick();};
const settle=async()=>{await flush();await new Promise(r=>setTimeout(r,10));await flush();};
beforeEach(()=>{
 copySignals=[];
 Object.assign(auth,{me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1});localStorage.clear();localStorage.setItem('stella_note_edit_mode','markdown');localStorage.setItem('stella_ipinfo',JSON.stringify({ip:'127.0.0.1',region:'local',at:Date.now()}));
 selected.value='one';copies=[];puts=[];lost=false;gate=null;row={id:'one',title:'note',content:'original body',updated_at:'2026-10-16T01:00:00.000001+00:00',workspace_id:'ws',parent_id:null,has_draft:false,created_at:'2026-10-16T01:00:00+00:00'};
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('matchMedia',()=>({matches:false,addEventListener(){},removeEventListener(){}}));vi.stubGlobal('WebSocket',class{static OPEN=1;readyState=1;send(){}close(){};});
 vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{
  if(path===`/web-projects/${root}/copy-asset`){copySignals.push(options?.signal);copies.push(JSON.parse(String(options?.body)));if(gate)return gate;if(lost)throw Error('response lost');return response({url:'/attachments/'+aid,filename:'cat.png'});}
  if(/^\/documents\/(one|two)$/.test(path)){if(options?.method==='PUT'){puts.push(JSON.parse(String(options.body)));row={...row,...puts.at(-1)};}return response({...row,id:path.split('/').at(-1)});}
  return response([]);
 }));
});
afterEach(()=>{auth.suspended=true;app?.unmount();host?.remove();vi.unstubAllGlobals();vi.useRealTimers();});
async function mount(){host=document.createElement('div');document.body.append(host);const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.userId='alice';store.workspaceId='ws';app=createApp({render:()=>h(DocEditor,{docId:selected.value,ref:editor})}).use(pinia);app.mount(host);await settle();}
function drop(raw=JSON.stringify({root,file,path:'assets/cat.png',mime:'image/png'})){
 const e=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(e,'dataTransfer',{value:{types:[PROJECT_ASSET_MIME],getData:(type:string)=>type===PROJECT_ASSET_MIME?raw:'',files:[]}});host.querySelector('.panes')!.dispatchEvent(e);return e;
}
function click(text:string){const button=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(button).toBeTruthy();button!.click();}
const cancelButton=()=>[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()==='取消这次插入')!;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
it.each(['fetch','body'])('bounds a held %s without auth changes and fences its late ACK against the retry',async phase=>{
 await mount();vi.useFakeTimers();const old=deferred<Response>(),body=deferred<any>(),fresh=deferred<Response>();
 if(phase==='fetch')gate=old.promise;
 else{const r=response({});Object.defineProperty(r,'json',{value:()=>body.promise});gate=Promise.resolve(r);}
 drop();await flush();expect(copies).toHaveLength(1);expect(copySignals[0]?.aborted).toBe(false);
 await vi.advanceTimersByTimeAsync(29999);await flush();expect(cancelButton().disabled).toBe(true);
 await vi.advanceTimersByTimeAsync(1);await flush();
 expect(copySignals[0]?.aborted).toBe(true);expect(cancelButton().disabled).toBe(false);
 expect(host.textContent).toContain('超时');expect(host.textContent).toContain('取消不会删除');
 expect(await editor.value.prepareNavigation()).toBe(false);
 gate=fresh.promise;click('重试图片复制');await flush();
 expect(copies).toHaveLength(2);expect(copies[1]).toEqual(copies[0]);expect(copySignals[1]?.aborted).toBe(false);
 const asset={url:'/attachments/'+aid,filename:'cat.png'};
 if(phase==='fetch')old.resolve(response(asset));else body.resolve(asset);
 await flush();expect(cancelButton().disabled).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');
 expect(await editor.value.prepareNavigation()).toBe(false);expect(copies).toHaveLength(2);
 fresh.resolve(response(asset));await flush();
 expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body\n\n![cat.png](/attachments/'+aid+')');
 expect(await editor.value.prepareNavigation()).toBe(true);expect(puts.at(-1).content).toContain('/attachments/'+aid);
});
it('auth recovery retries the same pending operation before the old request settles',async()=>{
 await mount();const old=deferred<Response>(),fresh=deferred<Response>();gate=old.promise;drop();await flush();
 auth.requestEpoch++;auth.suspended=true;await settle();auth.requestEpoch++;auth.suspended=false;await settle();
 expect(copySignals[0]?.aborted).toBe(true);expect(copies).toHaveLength(1);
 gate=fresh.promise;click('重试图片复制');await flush();expect(copies).toHaveLength(2);expect(copies[1]).toEqual(copies[0]);
 old.resolve(response({url:'/attachments/'+aid,filename:'cat.png'}));await settle();
 expect(cancelButton().disabled).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');
 fresh.resolve(response({url:'/attachments/'+aid,filename:'cat.png'}));await settle();
 expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body\n\n![cat.png](/attachments/'+aid+')');
});
it('cancelled insertion never publishes a late ACK after leaving for another document',async()=>{
 await mount();const old=deferred<Response>();gate=old.promise;drop();await flush();
 auth.requestEpoch++;await settle();click('取消这次插入');await settle();
 expect(await editor.value.prepareNavigation()).toBe(true);selected.value='two';await settle();
 old.resolve(response({url:'/attachments/'+aid,filename:'cat.png'}));await settle();
 expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');expect(puts).toHaveLength(0);expect(copies).toHaveLength(1);
});
it('real ordinary editor copies a project image, retries unknown ACK with same id, saves an independent URL',async()=>{
 await mount();lost=true;expect(drop().defaultPrevented).toBe(true);await settle();expect(copies).toHaveLength(1);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');expect(await editor.value.prepareNavigation()).toBe(false);
 lost=false;click('重试图片复制');await settle();expect(copies).toHaveLength(2);expect(copies[0]).toEqual(copies[1]);expect(copies[0].target_doc_id).toBe('one');expect(copies[0].request_id).toMatch(/^[\da-f-]{36}$/);
 expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body\n\n![cat.png](/attachments/'+aid+')');
 expect(await editor.value.prepareNavigation()).toBe(true);expect(puts.at(-1).content).toContain('/attachments/'+aid);expect(puts.at(-1).content).not.toContain('/p/');
});
it('late image copy after selection changes cannot insert into another document',async()=>{
 await mount();let finish!:(r:Response)=>void;gate=new Promise(r=>finish=r);drop();await flush();selected.value='two';await settle();finish(response({url:'/attachments/'+aid,filename:'cat.png'}));await settle();expect(copies).toHaveLength(1);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');
});
it('malformed project drop is intercepted without an upload, move or private URL fallback',async()=>{
 await mount();expect(drop('{bad').defaultPrevented).toBe(true);await settle();expect(copies).toEqual([]);expect(puts).toEqual([]);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');
});
it('pending copy provides a safe escape after same-owner authentication recovery',async()=>{
 await mount();gate=new Promise(()=>{});drop();await flush();
 auth.suspended=true;auth.requestEpoch++;await settle();auth.suspended=false;auth.requestEpoch++;await settle();
 const cancel=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()==='取消这次插入')!;
 console.log('COPY_HELD_AUTH_RECOVERY',JSON.stringify({cancelDisabled:cancel.disabled,retryVisible:host.textContent?.includes('重试图片复制'),canNavigate:await editor.value.prepareNavigation()}));
 expect(cancel.disabled).toBe(false);
 expect(copySignals[0]?.aborted).toBe(true);
 expect(host.textContent).toContain('重试图片复制');
 expect(await editor.value.prepareNavigation()).toBe(false);
 cancel.click();await settle();
 expect(await editor.value.prepareNavigation()).toBe(true);
 expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');
});
it('late image ACK after selection switch cannot insert into another document',async()=>{
 await mount();let finish!:(r:Response)=>void;gate=new Promise(r=>finish=r);drop();await flush();selected.value='two';await settle();finish(response({url:'/attachments/'+aid,filename:'cat.png'}));await settle();
 expect(copies).toHaveLength(1);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');
});
it('late image ACK after request epoch changes cannot insert until explicit retry',async()=>{
 await mount();let finish!:(r:Response)=>void;gate=new Promise(r=>finish=r);drop();await flush();auth.requestEpoch++;await settle();finish(response({url:'/attachments/'+aid,filename:'cat.png'}));await settle();
 expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('original body');expect(await editor.value.prepareNavigation()).toBe(false);
 gate=null;click('重试图片复制');await settle();expect(copies[0]).toEqual(copies[1]);expect(host.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toContain('/attachments/'+aid);
});
