// Component contract with captured owned-PG input; not a real-network proof.
import {it, expect, vi, beforeEach, afterEach} from 'vitest';
import {createApp, h, nextTick, ref, KeepAlive, type App} from 'vue';
import {createPinia, setActivePinia} from 'pinia';
import {createHash, webcrypto} from 'node:crypto';
import {auth} from '../home/auth';
import {useNotesStore} from '../../stores/notes';
import DocEditor from './DocEditor.vue';
import captured from './bounded-display.http.json';

vi.mock('../home/auth', async () => ({auth:(await import('vue')).reactive({me:{id:'alice'}, suspended:false, sessionClosing:false, sessionGeneration:1, requestEpoch:1}), refreshAccess:vi.fn(async()=>false)}));
vi.mock('vue-router', () => ({useRoute:()=>({hash:'',query:{}}), useRouter:()=>({push:vi.fn()})}));
// Only the text widget is replaced; DocEditor, Pinia store, HTTP serializer and draft transport are real.
vi.mock('./CmEditor.vue', async () => {
 const {defineComponent,h}=await import('vue');
 return {default:defineComponent({props:['modelValue'],emits:['update:modelValue'],setup:(p,{emit})=>()=>h('textarea',{'data-body':'',value:p.modelValue,onInput:(e:any)=>emit('update:modelValue',e.target.value)})})};
});
const stamp='2026-10-16T01:02:03.123456+00:00';
const hash=(s:string)=>createHash('sha256').update(s,'utf8').digest('hex');
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
 rows={one:{...doc(),...captured.created,id:'one',workspace_id:'ws',has_draft:false},two:doc('two')};slots={one:{content:'草稿 😀\nraw\r\n',updated_at:stamp,device:'other'}};puts=[];requests=[];sockets.length=0;selected=ref('one');visible=ref(true);draftGate=null;docGate=null;putGate=null;failure=null;lostReply=false;
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
    rows[id]={...rows[id],...body,updated_at:captured.saved.updated_at,updated_at_display:captured.saved.updated_at_display,has_draft:!!slots[id]};if(lostReply)throw new Error('reply lost after commit');return response(rows[id]);
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

it('uses the real PG create display instant, never sending it as the raw CAS token',async()=>{
 vi.useFakeTimers({toFake:['Date']});vi.setSystemTime(captured.captured_epoch*1000);
 await mount();click('编辑');await settle();expect(document.body.textContent).toContain('保存于 刚刚');
 await edit('mounted changed');await save();
 expect(puts.at(-1)!.body.updated_at).toBe(captured.created.updated_at);
 expect(puts.at(-1)!.body).not.toHaveProperty('updated_at_display');
 expect(document.body.textContent).toContain('保存于 刚刚');
});
it('shows an unknown historical save without hiding its draft adoption controls',async()=>{
 rows.one.updated_at_display=null;rows.one.has_draft=true;rows.one.draft_updated_at=stamp;
 await mount();click('编辑');await settle();expect(document.body.textContent).toContain('保存时间未知');
 expect(document.body.textContent).toContain('采用并保存');
});
