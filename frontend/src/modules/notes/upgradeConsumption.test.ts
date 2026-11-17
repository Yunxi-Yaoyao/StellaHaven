import {it, expect, vi, beforeEach, afterEach} from 'vitest';
import {createApp, h, nextTick, ref, KeepAlive, type App} from 'vue';
import {createPinia, setActivePinia} from 'pinia';
import {createHash, webcrypto} from 'node:crypto';
import {auth} from '../home/auth';
import {useNotesStore} from '../../stores/notes';
import DocEditor from './DocEditor.vue';

vi.mock('../home/auth', async () => ({auth:(await import('vue')).reactive({me:{id:'alice'}, suspended:false, sessionClosing:false, sessionGeneration:1, requestEpoch:1}), refreshAccess:vi.fn(async()=>false)}));
vi.mock('vue-router', () => ({useRoute:()=>({hash:'',query:{}}), useRouter:()=>({push:vi.fn()})}));
// Only the text widget is replaced; DocEditor, Pinia store, HTTP serializer and draft transport are real.
vi.mock('./CmEditor.vue', async () => {
 const {defineComponent,h}=await import('vue');
 return {default:defineComponent({props:['modelValue'],emits:['update:modelValue'],setup:(p,{emit})=>()=>h('textarea',{'data-body':'',value:p.modelValue,onInput:(e:any)=>emit('update:modelValue',e.target.value)})})};
});
const stamp='2026-10-16T01:02:03.123456+00:00';
const hash=(s:string)=>createHash('sha256').update(s,'utf8').digest('hex');
const receipt=(s:string,t=stamp)=>({draft_updated_at:t,content_hash:hash(s)});
const doc=(id='one')=>({id,title:id,content:'body '+id,updated_at:'2026-10-16T01:00:00.000001+00:00',workspace_id:'ws',parent_id:null,has_draft:true,draft_updated_at:stamp,draft_device:'other',created_at:stamp});
type Slot={content:string;updated_at:string;device:string};
let rows:Record<string,any>, slots:Record<string,Slot|undefined>, puts:{id:string;body:any}[], requests:{path:string;method:string}[];
let app:App|undefined, selected=ref('one'), visible=ref(true), store:ReturnType<typeof useNotesStore>;
let draftGate:Promise<Response>|null, docGate:Promise<Response>|null, putGate:Promise<void>|null, failure:number|null, lostReply:boolean;
const sockets:FakeSocket[]=[];
class FakeSocket {
 static OPEN=1; readyState=1; onmessage:any; onclose:any; onopen:any; onerror:any; sent:any[]=[];
 url:string;
 constructor(url:string){this.url=url;sockets.push(this);}
 send(raw:string){this.sent.push(JSON.parse(raw));}
 close(){this.readyState=3;}
 message(msg:any){this.onmessage?.({data:JSON.stringify(msg)});}
}
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();await nextTick();};
const settle=async()=>{await flush();await new Promise(r=>setTimeout(r,10));await flush();};
const response=(data:any,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
beforeEach(()=>{
 Object.assign(auth,{me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1});
 localStorage.clear();localStorage.setItem('stella_note_edit_mode','markdown');localStorage.setItem('stella_ipinfo',JSON.stringify({ip:'127.0.0.1',region:'local',at:Date.now()}));
 rows={one:doc(),two:doc('two')};slots={one:{content:'草稿 😀\nraw\r\n',updated_at:stamp,device:'other'}};puts=[];requests=[];sockets.length=0;selected=ref('one');visible=ref(true);draftGate=null;docGate=null;putGate=null;failure=null;lostReply=false;
 vi.stubGlobal('matchMedia',()=>({matches:false,addEventListener(){},removeEventListener(){}}));
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('WebSocket',FakeSocket);
 vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{
  const method=options?.method??'GET';requests.push({path,method});
  if(path==='/document-versions/?doc_id=one')return response([{id:'v1',doc_id:'one',version_no:1,created_at:stamp}]);
  if(path==='/document-versions/v1/restore'){rows.one={...rows.one,content:'restored body',updated_at:'2026-10-16T01:03:00.999999+00:00'};return response(rows.one);}
  const match=path.match(/^\/documents\/(one|two)(\/draft)?$/);
  if(match){const id=match[1]!;
   if(match[2])return draftGate??response(slots[id]??{detail:'expired'},slots[id]?200:404);
   if(method==='PUT'){
    const body=JSON.parse(options!.body as string);puts.push({id,body});if(putGate)await putGate;
    if(failure===0)throw new Error('unknown result');if(failure)return response({detail:'conflict'},failure);
    if(body.updated_at!==rows[id].updated_at)return response({detail:'conflict'},409);
    const slot=slots[id],r=body.consumed_draft;
    if('content'in body&&slot&&r?.draft_updated_at===slot.updated_at&&r?.content_hash===hash(slot.content))delete slots[id];
    rows[id]={...rows[id],...body,updated_at:'2026-10-16T01:04:00.456789+00:00',has_draft:!!slots[id]};if(lostReply)throw new Error('reply lost after commit');return response(rows[id]);
   }
   return docGate??response(rows[id]);
  }
  return response([]);
 }));
});
afterEach(()=>{auth.suspended=true;app?.unmount();app=undefined;vi.useRealTimers();vi.unstubAllGlobals();document.body.innerHTML='';});
async function mount(){const root=document.createElement('div');document.body.append(root);const pinia=createPinia();setActivePinia(pinia);store=useNotesStore();store.userId='alice';store.workspaceId='ws';app=createApp({render:()=>h(KeepAlive,null,{default:()=>visible.value?h(DocEditor,{docId:selected.value}):null})}).use(pinia);app.mount(root);await settle();}
function click(text:string){const b=[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();}
async function edit(text:string){const el=document.querySelector<HTMLTextAreaElement>('[data-body]')!;el.value=text;el.dispatchEvent(new Event('input',{bubbles:true}));await flush();}
async function save(){window.dispatchEvent(new KeyboardEvent('keydown',{key:'s',ctrlKey:true}));await settle();}

async function sendLocal(text:string){vi.useFakeTimers();await edit(text);await vi.advanceTimersByTimeAsync(2500);vi.useRealTimers();await settle();return sockets.at(-1)!.sent.at(-1);}
function ack(message:any, socket=sockets.at(-1)!,time=stamp){slots.one={content:message.content,updated_at:time,device:'this'};socket.message({type:'draft_ack',request_id:message.request_id,base_updated_at:rows.one.updated_at,...receipt(message.content,time)});}
it('binds the local ACK to its request and preserves that provenance while editing newer text',async()=>{
 await mount();const message=await sendLocal('local draft');expect(message.request_id).toBeTypeOf('string');
 ack(message);await settle();await edit('local draft with further edits');await save();
 expect(puts.at(-1)!.body.consumed_draft).toEqual(receipt('local draft'));expect(rows.one.content).toBe('local draft with further edits');expect(slots.one).toBeUndefined();
});

it.each(['edit','doc','workspace','logout','suspend','keepalive'] as const)('late fetched adoption is fenced after %s and never writes stale content',async(boundary)=>{
 await mount();let finish!:(r:Response)=>void;draftGate=new Promise(r=>finish=r);click('采用并保存');await flush();
 if(boundary==='edit')await edit('new local text');
 if(boundary==='doc')selected.value='two';
 if(boundary==='workspace')store.workspaceId='elsewhere';
 if(boundary==='logout'){auth.sessionGeneration++;auth.me={id:'bob'} as any;}
 if(boundary==='suspend'){auth.suspended=true;auth.suspended=false;}
 if(boundary==='keepalive'){visible.value=false;await flush();visible.value=true;}
 await flush();finish(response({content:'late draft',updated_at:stamp,device:'other'}));await settle();
 expect(puts).toEqual([]);expect(document.querySelector<HTMLTextAreaElement>('[data-body]')?.value).not.toBe('late draft');
 if(boundary==='edit')expect(document.querySelector<HTMLTextAreaElement>('[data-body]')?.value).toBe('new local text');
});

it('a successful save consumes provenance once, retaining newer edits without reusing the old receipt',async()=>{
 await mount();const sent=await sendLocal('snapshot');ack(sent);await settle();let finish!:()=>void;putGate=new Promise(r=>finish=r);await save();await edit('typed during PUT');finish();await settle();putGate=null;
 expect(rows.one.content).toBe('snapshot');expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('typed during PUT');await save();
 expect(puts[1]!.body).not.toHaveProperty('consumed_draft');expect(rows.one.content).toBe('typed during PUT');
});
it('metadata-only editor save omits content and receipt and preserves the draft slot',async()=>{
 await mount();const sent=await sendLocal('draft');ack(sent);await settle();await edit('body one');click('编辑');await flush();const title=document.querySelector<HTMLTextAreaElement>('.title-input')!;title.value='renamed';title.dispatchEvent(new Event('input'));await flush();await save();
 expect(puts.at(-1)!.body).not.toHaveProperty('consumed_draft');expect(puts.at(-1)!.body).not.toHaveProperty('content');expect(slots.one?.content).toBe('draft');expect(rows.one.title).toBe('renamed');
});
it('late failed PUT cannot put an error on the newly selected document',async()=>{
 await mount();await edit('old changes');let finish!:()=>void;putGate=new Promise(r=>finish=r);failure=409;await save();selected.value='two';await settle();finish();await settle();
 expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('body two');expect(document.body.textContent).not.toContain('版本冲突');expect(puts.map(p=>p.id)).toEqual(['one']);
});

it('body save fences a draft read started before the save, even if local text stayed unchanged',async()=>{
 await mount();await edit('save this');let finish!:(r:Response)=>void;draftGate=new Promise(r=>finish=r);click('采用并保存');await flush();await save();finish(response({content:'old remote draft',updated_at:stamp,device:'other'}));await settle();
 expect(puts).toHaveLength(1);expect(rows.one.content).toBe('save this');expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('save this');
});
it.each([409,0])('save failure %s retains text and the adopted receipt on explicit retry',async(status)=>{
 await mount();failure=status;click('采用并保存');await settle();expect(slots.one).toBeDefined();expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('草稿 😀\nraw\n');expect(puts[0]!.body.content).toBe('草稿 😀\nraw\r\n');
 await edit('continued after failure');failure=null;await save();expect(puts[1]!.body.consumed_draft).toEqual(receipt('草稿 😀\nraw\r\n'));expect(rows.one.content).toBe('continued after failure');expect(slots.one).toBeUndefined();
});
it('newer other-device slot survives a PUT with our exact older adopted receipt',async()=>{
 await mount();let finish!:()=>void;putGate=new Promise(r=>finish=r);click('采用并保存');await settle();slots.one={content:'new from other',updated_at:'2026-10-16T01:03:00.123457+00:00',device:'other'};finish();await settle();
 expect(rows.one.content).toBe('草稿 😀\nraw\r\n');expect(slots.one?.content).toBe('new from other');expect(puts[0]!.body.consumed_draft).toEqual(receipt('草稿 😀\nraw\r\n'));
});
it.each(['missing','wrong-request','wrong-base','wrong-hash'] as const)('unmatched %s ACK never grants a receipt and does not block save',async(kind)=>{
 await mount();const msg=await sendLocal('local');
 if(kind!=='missing')sockets.at(-1)!.message({type:'draft_ack',request_id:kind==='wrong-request'?'foreign':msg.request_id,base_updated_at:kind==='wrong-base'?'different':rows.one.updated_at,...receipt(kind==='wrong-hash'?'foreign':'local')});
 await settle();await save();expect(puts[0]!.body).not.toHaveProperty('consumed_draft');expect(rows.one.content).toBe('local');expect(slots.one).toBeDefined();
});
it('out-of-order ACK cannot replace the newer acknowledged local source',async()=>{
 await mount();const first=await sendLocal('first'),second=await sendLocal('second');const socket=sockets.at(-1)!;ack(second,socket,'2026-10-16T01:03:00.111111+00:00');await settle();socket.message({type:'draft_ack',request_id:first.request_id,base_updated_at:rows.one.updated_at,...receipt('first')});await settle();await save();
 expect(puts[0]!.body.consumed_draft).toEqual(receipt('second','2026-10-16T01:03:00.111111+00:00'));expect(slots.one).toBeUndefined();
});
it('ACK for replaced local text cannot steal provenance from explicitly adopted remote draft',async()=>{
 await mount();const msg=await sendLocal('local not adopted'),socket=sockets.at(-1)!;failure=409;click('采用并保存');await settle();socket.message({type:'draft_ack',request_id:msg.request_id,base_updated_at:rows.one.updated_at,...receipt(msg.content)});await settle();failure=null;await edit('remote plus changes');await save();
 expect(puts[1]!.body.consumed_draft).toEqual(receipt('草稿 😀\nraw\r\n'));expect(rows.one.content).toBe('remote plus changes');
});
it('viewing a remote draft does not adopt its receipt',async()=>{
 await mount();click('查看');await settle();await edit('unrelated text');await save();expect(puts[0]!.body).not.toHaveProperty('consumed_draft');expect(slots.one).toBeDefined();
});
it.each(['absent','reject'] as const)('crypto %s preserves the server draft and still saves the adopted content',async(kind)=>{
 await mount();vi.stubGlobal('crypto',kind==='absent'?{}:{subtle:{digest:()=>Promise.reject(new Error('unavailable'))}});click('采用并保存');await settle();expect(puts[0]!.body).not.toHaveProperty('consumed_draft');expect(rows.one.content).toBe('草稿 😀\nraw\r\n');expect(slots.one).toBeDefined();
});

it.each(['doc','workspace','logout','suspend','keepalive','reconnect'] as const)('late ACK from the previous %s context cannot authorize current-body consumption',async(boundary)=>{
 await mount();const msg=await sendLocal('previous context');const old=sockets.at(-1)!,deliver=old.onmessage;
 // Avoid navigation autosave success masking the stale ACK under test.
 failure=409;
 if(boundary==='doc'){selected.value='two';await settle();}
 if(boundary==='workspace'){store.workspaceId='elsewhere';store.workspaceId='ws';await settle();}
 if(boundary==='logout'){auth.sessionGeneration++;auth.me={id:'bob'} as any;await settle();}
 if(boundary==='suspend'){auth.suspended=true;auth.suspended=false;await settle();}
 if(boundary==='keepalive'){visible.value=false;await settle();visible.value=true;await settle();}
 if(boundary==='reconnect'){vi.useFakeTimers();old.onclose();await vi.advanceTimersByTimeAsync(3000);vi.useRealTimers();await settle();}
 puts=[];failure=null;deliver({data:JSON.stringify({type:'draft_ack',request_id:msg.request_id,base_updated_at:rows.one.updated_at,...receipt(msg.content)})});await settle();await edit('current body');await save();
 if(boundary==='logout')expect(puts).toEqual([]);else{expect(puts).toHaveLength(1);expect(puts[0]!.body).not.toHaveProperty('consumed_draft');expect(rows[boundary==='doc'?'two':'one'].content).toBe('current body');}
});
it('late ACK after a successful save cannot be attached to later edits',async()=>{
 await mount();const msg=await sendLocal('saved before ACK'),socket=sockets.at(-1)!;await save();socket.message({type:'draft_ack',request_id:msg.request_id,base_updated_at:doc().updated_at,...receipt(msg.content)});await settle();await edit('later edits');await save();expect(puts[1]!.body).not.toHaveProperty('consumed_draft');
});
it('new ACK received during a held PUT is retained for the newer edited body only',async()=>{
 await mount();const a=await sendLocal('a');ack(a);await settle();let finish!:()=>void;putGate=new Promise(r=>finish=r);await save();const b=await sendLocal('b');ack(b,sockets.at(-1)!,'2026-10-16T01:03:00.111111+00:00');await settle();finish();await settle();putGate=null;
 expect(puts[0]!.body.consumed_draft).toEqual(receipt('a'));expect(slots.one?.content).toBe('b');expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('b');await save();expect(puts[1]!.body.consumed_draft).toEqual(receipt('b','2026-10-16T01:03:00.111111+00:00'));expect(slots.one).toBeUndefined();
});
it('late adoption digest cannot replace edits made while SHA256 was pending',async()=>{
 await mount();let finish!:(v:ArrayBuffer)=>void;vi.stubGlobal('crypto',{subtle:{digest:()=>new Promise<ArrayBuffer>(r=>finish=r)}});click('采用并保存');await flush();await edit('typed while hashing');finish(new Uint8Array(32).buffer);await settle();expect(puts).toEqual([]);expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('typed while hashing');
});
it('empty draft is a body update with the empty UTF-8 digest, never null',async()=>{
 await mount();slots.one={content:'',updated_at:stamp,device:'other'};click('采用并保存');await settle();expect(puts[0]!.body.content).toBe('');expect(puts[0]!.body.consumed_draft).toEqual(receipt(''));expect(slots.one).toBeUndefined();
});

it('version restore replaces the source lineage; future edits cannot consume the previous draft',async()=>{
 await mount();const msg=await sendLocal('previous draft');ack(msg);await settle();await edit('body one');document.querySelector<HTMLButtonElement>('[aria-label="更多"]')!.click();await flush();click('版本历史');await settle();click('恢复');await flush();click('确认恢复版本');await settle();expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('restored body');await edit('restored plus edit');await save();expect(puts[0]!.body).not.toHaveProperty('consumed_draft');expect(slots.one?.content).toBe('previous draft');
});
it('dismiss cancels a pending adoption without replacing the current body',async()=>{
 await mount();let finish!:(r:Response)=>void;draftGate=new Promise(r=>finish=r);click('采用并保存');await flush();click('忽略');finish(response(slots.one));await settle();expect(puts).toEqual([]);expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('body one');
});

it('lost response after an actual fixture commit retains local continuation and never rebases the CAS token',async()=>{
 await mount();lostReply=true;click('采用并保存');await settle();expect(slots.one).toBeUndefined();expect(rows.one.content).toBe('草稿 😀\nraw\r\n');await edit('local continuation');lostReply=false;await save();expect(puts[1]!.body.updated_at).toBe(doc().updated_at);expect(puts[1]!.body.consumed_draft).toEqual(receipt('草稿 😀\nraw\r\n'));expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('local continuation');expect(document.body.textContent).toContain('版本冲突');
});
it('real editor ignores a held background body read after local edits',async()=>{
 await mount();let finish!:(r:Response)=>void;docGate=new Promise(r=>finish=r);sockets.at(-1)!.message({type:'doc_saved'});await flush();await edit('keep local');finish(response({...rows.one,content:'remote overwrite'}));await settle();expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('keep local');
});
it('remote saved notification cannot reload over a pending PUT even after the user reverts local text',async()=>{
 await mount();await edit('pending body');let finish!:()=>void;putGate=new Promise(r=>finish=r);await save();await edit('body one');rows.one.content='remote body';sockets.at(-1)!.message({type:'doc_saved'});await settle();expect(document.querySelector<HTMLTextAreaElement>('[data-body]')!.value).toBe('body one');finish();await settle();
});
it('title-only edits do not publish the unchanged body into the shared draft slot',async()=>{
 await mount();click('编辑');await flush();vi.useFakeTimers();const title=document.querySelector<HTMLTextAreaElement>('.title-input')!;title.value='title only';title.dispatchEvent(new Event('input'));await flush();await vi.advanceTimersByTimeAsync(2500);vi.useRealTimers();await settle();expect(sockets.at(-1)!.sent).toEqual([]);await save();expect(puts[0]!.body).not.toHaveProperty('content');expect(slots.one?.content).toBe('草稿 😀\nraw\r\n');
});
it('metadata API serialization strips any receipt without a body, including moved documents',async()=>{
 const {updateDoc}=await import('../../api/notes');await updateDoc('one',rows.one.updated_at,{title:'metadata',parent_id:'parent',consumed_draft:receipt('草稿 😀\nraw\r\n')});expect(puts[0]!.body).not.toHaveProperty('consumed_draft');expect(slots.one).toBeDefined();
});
it('adopts the fetched UTF-8 draft and sends its exact timestamp/hash in the real PUT; fixture slot is consumed',async()=>{
 await mount();click('采用并保存');await settle();
 expect(puts).toHaveLength(1);expect(puts[0]!.body.consumed_draft).toEqual(receipt('草稿 😀\nraw\r\n'));
 expect(rows.one.content).toBe('草稿 😀\nraw\r\n');expect(slots.one).toBeUndefined();
 expect(requests.filter(r=>r.method==='DELETE')).toEqual([]);
});
