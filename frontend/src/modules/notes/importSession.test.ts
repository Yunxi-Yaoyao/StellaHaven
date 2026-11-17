import {createApp} from 'vue';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
const m=vi.hoisted(()=>({refresh:vi.fn(),list:vi.fn()}));
vi.mock('../home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:vi.fn()};});
vi.mock('../../stores/notes',()=>({useNotesStore:()=>({workspaces:[{id:'ws',name:'Workspace'}],refreshList:m.refresh})}));
vi.mock('../../api/notes',()=>({listDocs:m.list}));
import {auth} from '../home/auth';
import {api} from '../../api/client';
import {prepareImport,queueImports,runImportBatch} from './import-helpers';
import ImportDialog from './ImportDialog.vue';
import HtmlConversionRow from './HtmlConversionRow.vue';
import WebProjectImportRow from './WebProjectImportRow.vue';
import ZipImportDialog from './ZipImportDialog.vue';
const deferred=<T,>()=>{let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};};
const source=(name='a.md')=>({name,size:10,arrayBuffer:async()=>new TextEncoder().encode('source').buffer});
const response=(value:unknown)=>new Response(JSON.stringify(value),{status:200});
let dispose=()=>{};
function invalidate(transition:string){
 if(transition==='unmount')dispose();
 else if(transition==='owner')auth.me={id:'other'} as any;
 else if(transition==='generation')auth.sessionGeneration++;
 else if(transition==='suspend'){auth.suspended=true;auth.suspended=false;}
 else auth.requestEpoch++;
}
beforeEach(()=>{Object.assign(auth,{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});m.list.mockResolvedValue([]);m.refresh.mockResolvedValue(undefined);});
afterEach(()=>{dispose();dispose=()=>{};document.body.replaceChildren();vi.unstubAllGlobals();vi.clearAllMocks();});
function mount(component:any,props:any){const host=document.createElement('div');document.body.append(host);const app=createApp(component,props);app.mount(host);let alive=true;dispose=()=>{if(alive){alive=false;app.unmount();host.remove();}};}
function click(label:string){const b=[...document.querySelectorAll('button')].find(b=>b.textContent?.includes(label));expect(b,label).toBeTruthy();expect(b!.disabled,label).toBe(false);b!.click();}
it('real batch + api stops on stale receipt instead of adopting a new login',async()=>{
 const rows=queueImports([source(),source('b.md')]);for(const row of rows)await prepareImport(row);
 const first=deferred<Response>();const fetch=vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(response({id:'second'}));vi.stubGlobal('fetch',fetch);
 const run=runImportBatch(rows,{workspaceId:'old-ws',parentId:null},[],p=>api('/documents/',{method:'POST',body:JSON.stringify(p)}));
 const settled=run.catch(e=>e);auth.requestEpoch++;auth.sessionGeneration++;first.resolve(response({id:'committed-but-stale'}));
 expect((await settled)?.name).toBe('AbortError');expect(fetch).toHaveBeenCalledTimes(1);expect(rows[0]!.status).toBe('failed');expect(rows[1]!.status).toBe('ready');expect(rows[0]!.payload?.file_path).toContain(rows[0]!.id);
});
for(const transition of ['unmount','owner','epoch','generation','suspend'] as const)it(`mounted text batch stops after ${transition} while target lookup is pending`,async()=>{
 const lookup=deferred<any[]>();m.list.mockResolvedValueOnce([]).mockReturnValueOnce(lookup.promise);const fetch=vi.fn().mockResolvedValue(response({id:'x'}));vi.stubGlobal('fetch',fetch);
 mount(ImportDialog,{files:[source()],workspaceId:'ws',parentId:null});await vi.waitFor(()=>expect(document.body.textContent).toContain('导入 1 篇'));click('导入 1 篇');
 invalidate(transition);
 lookup.resolve([]);await new Promise(r=>setTimeout(r,30));expect(fetch).not.toHaveBeenCalled();expect(m.refresh).not.toHaveBeenCalled();
});
const modes=[{component:HtmlConversionRow,action:'转为MD笔记',path:'/documents/import/html',data:{converted_count:1,documents:[],warnings:[]},result:{documents:[{id:'d'}]}},{component:WebProjectImportRow,action:'渲染HTML',path:'/web-projects/import',data:{files:[],entries:['index.html'],suggested_entry:'index.html',warnings:[]},result:{id:'d'}},{component:ZipImportDialog,action:'导入此 ZIP',path:'/documents/import/zip',data:{entries:[],warnings:[],counts:{documents:1,attachments:0}},result:{documents:[{id:'d',title:'doc'}],attachments:0,warnings:[]}}];
for(const mode of modes)for(const transition of ['unmount','owner','epoch','generation','suspend'] as const)it(`${mode.path} checks ${transition} after delayed arrayBuffer before preview POST`,async()=>{
 const bytes=deferred<ArrayBuffer>();const fetch=vi.fn().mockResolvedValue(response(mode.data));vi.stubGlobal('fetch',fetch);mount(mode.component,{file:{...source('a.zip'),arrayBuffer:()=>bytes.promise},target:{workspaceId:'ws',parentId:null},disabled:false});click(mode.action);
 invalidate(transition);
 bytes.resolve(new ArrayBuffer(1));await new Promise(r=>setTimeout(r,30));expect(fetch).not.toHaveBeenCalled();
});

for(const mode of modes)for(const transition of ['unmount','owner','epoch','generation','suspend'] as const)it(`${mode.path} ignores unknown commit receipt after ${transition}, preserves identity for explicit same-owner retry`,async()=>{
 const receipt=deferred<Response>();const writes:FormData[]=[];let complete=0;
 const fetch=vi.fn((path:string,init:RequestInit)=>{if(path.endsWith('/preview'))return Promise.resolve(response(mode.data));writes.push(init.body as FormData);return writes.length===1?receipt.promise:Promise.resolve(response(mode.result));});vi.stubGlobal('fetch',fetch);
 mount(mode.component,{file:source('a.zip'),target:{workspaceId:'ws',parentId:null},disabled:false,onComplete:()=>complete++});click(mode.action);
 await vi.waitFor(()=>expect(writes).toHaveLength(1));
 invalidate(transition);
 receipt.resolve(response(mode.result));await new Promise(r=>setTimeout(r,30));expect(writes).toHaveLength(1);expect(complete).toBe(0);expect(m.refresh).not.toHaveBeenCalled();
 if(transition==='unmount')return;
 expect(document.body.textContent).toContain('导入已暂停');
 click(mode.component===ZipImportDialog?'重试此 ZIP':'重试确认');await new Promise(r=>setTimeout(r,30));
 if(transition==='owner'){expect(writes).toHaveLength(1);return;}
 expect(writes).toHaveLength(2);expect(complete).toBe(1);expect(writes[1]!.get('import_id')).toBe(writes[0]!.get('import_id'));expect(writes[1]!.get('workspace_id')).toBe('ws');
});
for(const mode of modes)it(`${mode.path} refuses a queue mounted without a logged-in owner`,async()=>{
 auth.me=null;const fetch=vi.fn().mockResolvedValue(response(mode.data));vi.stubGlobal('fetch',fetch);mount(mode.component,{file:source('a.zip'),target:{workspaceId:'ws',parentId:null},disabled:false});click(mode.action);await new Promise(r=>setTimeout(r,30));expect(fetch).not.toHaveBeenCalled();
});
it('mounted text batch retains unknown first write and retries exact key only after explicit click in new epoch',async()=>{
 const receipt=deferred<Response>();const writes:RequestInit[]=[];
 vi.stubGlobal('fetch',vi.fn((path:string,init:RequestInit)=>{if(path==='/documents/import/finalize')return Promise.resolve(response({synced:2}));writes.push(init);return writes.length===1?receipt.promise:Promise.resolve(response({id:'d'+writes.length}));}));
 mount(ImportDialog,{files:[source(),source('b.md')],workspaceId:'ws',parentId:null});await vi.waitFor(()=>expect(document.body.textContent).toContain('导入 2 篇'));click('导入 2 篇');await vi.waitFor(()=>expect(writes).toHaveLength(1));
 auth.requestEpoch++;receipt.resolve(response({id:'unknown'}));await vi.waitFor(()=>expect(document.body.textContent).toContain('重试未成功文件'));expect(writes).toHaveLength(1);expect(m.refresh).not.toHaveBeenCalled();
 click('重试未成功文件');await vi.waitFor(()=>expect(writes).toHaveLength(3));expect(writes[1]!.body).toBe(writes[0]!.body);expect(new Headers(writes[1]!.headers).get('X-Import-Key')).toBe(new Headers(writes[0]!.headers).get('X-Import-Key'));
});
for(const mode of modes)it(`${mode.path} displays server upload, decoded source and archive budgets before preview`,()=>{
 mount(mode.component,{file:source('a.zip'),target:{workspaceId:'ws',parentId:null},disabled:false});const text=document.body.textContent!;
 expect(text).toContain(mode.component===ZipImportDialog?'上传 ≤ 32 MiB':'上传 ≤ 25 MiB');
 expect(text).toContain('展开合计 ≤ 128 MiB');expect(text).toContain('单文件 ≤ 25 MiB');expect(text).toContain('2000');expect(text).toContain('32 层');expect(text).toContain('200 倍');expect(text).toContain('1024');expect(text).toContain('255');
 if(mode.component!==ZipImportDialog)expect(text).toContain('解码后 UTF-8 ≤ 5 MiB');
 if(mode.component===HtmlConversionRow)expect(text).toContain('转换结果归档 ≤ 32 MiB');
});

it('same-owner epoch change during finalize leaves an explicit sync-only retry',async()=>{
 const receipt=deferred<Response>();let creates=0,finalizes=0;
 vi.stubGlobal('fetch',vi.fn((path:string)=>{if(path==='/documents/import/finalize'){finalizes++;return finalizes===1?receipt.promise:Promise.resolve(response({synced:1}));}creates++;return Promise.resolve(response({id:'created'}));}));
 mount(ImportDialog,{files:[source()],workspaceId:'ws',parentId:null});await vi.waitFor(()=>expect(document.body.textContent).toContain('导入 1 篇'));click('导入 1 篇');await vi.waitFor(()=>expect(finalizes).toBe(1));auth.requestEpoch++;receipt.resolve(response({synced:1}));
 await vi.waitFor(()=>expect([...document.querySelectorAll('button')].find(b=>b.textContent==='重试双链同步')?.disabled).toBe(false));click('重试双链同步');await vi.waitFor(()=>expect(finalizes).toBe(2));expect(creates).toBe(1);
});
for(const mode of modes)it(`${mode.path} aborts transport signal when the mounted queue is destroyed`,async()=>{
 const receipt=deferred<Response>();let signal:AbortSignal|undefined;
 vi.stubGlobal('fetch',vi.fn((_path:string,init:RequestInit)=>{signal=init.signal??undefined;return receipt.promise;}));
 mount(mode.component,{file:source('a.zip'),target:{workspaceId:'ws',parentId:null},disabled:false});click(mode.action);await vi.waitFor(()=>expect(signal).toBeDefined());dispose();expect(signal!.aborted).toBe(true);receipt.resolve(response(mode.data));
});

for(const mode of modes.filter(m=>m.component!==WebProjectImportRow))for(const transition of ['unmount','owner','epoch'] as const)it(`${mode.path} rechecks ${transition} after automatic validation before committing the retained original bytes`,async()=>{
 const validation=deferred<Response>();let reads=0;const fetch=vi.fn().mockReturnValue(validation.promise);vi.stubGlobal('fetch',fetch);
 mount(mode.component,{file:{...source('a.zip'),arrayBuffer:async()=>{reads++;return new ArrayBuffer(1);}},target:{workspaceId:'ws',parentId:null},disabled:false});click(mode.action);await vi.waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));invalidate(transition);validation.resolve(response(mode.data));await new Promise(r=>setTimeout(r,30));expect(fetch).toHaveBeenCalledTimes(1);expect(reads).toBe(1);expect(m.refresh).not.toHaveBeenCalled();
});

it('epoch change between batch completion and finalize admission retains a sync-only retry',async()=>{
 let creates=0,finalizes=0;
 vi.stubGlobal('fetch',vi.fn(async(path:string)=>{
  if(path==='/documents/import/finalize'){finalizes++;return response({synced:1});}
  creates++;
  return {ok:true,status:200,json:async()=>{
   queueMicrotask(()=>queueMicrotask(()=>queueMicrotask(()=>{auth.requestEpoch++;})));
   return {id:'created'};
  }};
 }));
 mount(ImportDialog,{files:[source()],workspaceId:'ws',parentId:null});await vi.waitFor(()=>expect(document.body.textContent).toContain('导入 1 篇'));click('导入 1 篇');
 await vi.waitFor(()=>expect(document.body.textContent).toContain('已导入'));
 expect(finalizes).toBe(0);
 await vi.waitFor(()=>expect([...document.querySelectorAll('button')].find(b=>b.textContent==='重试双链同步')?.disabled).toBe(false));click('重试双链同步');await vi.waitFor(()=>expect(finalizes).toBe(1));expect(creates).toBe(1);
});

it('same identity metadata refresh does not invalidate an unchanged session',async()=>{
 const bytes=deferred<ArrayBuffer>();const fetch=vi.fn().mockResolvedValueOnce(response(modes[0]!.data)).mockResolvedValue(response(modes[0]!.result));vi.stubGlobal('fetch',fetch);
 mount(HtmlConversionRow,{file:{...source('a.html'),arrayBuffer:()=>bytes.promise},target:{workspaceId:'ws',parentId:null},disabled:false});click('转为MD笔记');
 auth.me={...auth.me!,display_name:'refreshed metadata'};bytes.resolve(new ArrayBuffer(1));await vi.waitFor(()=>expect(document.body.textContent).toContain('已导入'));expect(fetch).toHaveBeenCalledTimes(2);
});
