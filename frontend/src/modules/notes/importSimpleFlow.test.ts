import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,reactive} from 'vue';
const m=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn(),list:vi.fn(),auth:{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}}));
vi.mock('../../api/client',()=>({api:m.api,ApiError:class extends Error{}}));
vi.mock('../../api/notes',()=>({listDocs:m.list}));
vi.mock('../../stores/notes',()=>({useNotesStore:()=>({workspaces:[{id:'ws',name:'资料'}],refreshList:m.refresh})}));
vi.mock('../home/auth',()=>({auth:reactive(m.auth)}));
import HtmlConversionRow from './HtmlConversionRow.vue';
import WebProjectImportRow from './WebProjectImportRow.vue';
import ZipImportDialog from './ZipImportDialog.vue';
import ImportDialog from './ImportDialog.vue';
import JSZip from 'jszip';
import {auth} from '../home/auth';
it('does not transfer a dialog queue to a replacement owner when a format action mounts its child',async()=>{
 m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{files:[],entries:['index.html'],suggested_entry:'index.html',warnings:[]}:{id:'must-not-create'});mount(ImportDialog,{files:[source('owner.html')],workspaceId:'ws',parentId:null});await flush();
 auth.me={id:'replacement'} as any;await flush();button('渲染HTML')!.click();await flush();
 expect(m.api).not.toHaveBeenCalled();expect(document.body.textContent).toContain('导入已暂停');
});
it('does not auto-continue a selected format when the session changes before its child mounts',async()=>{
 m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{files:[],entries:['index.html'],suggested_entry:'index.html',warnings:[]}:{id:'must-not-create'});mount(ImportDialog,{files:[source('held.html')],workspaceId:'ws',parentId:null});await flush();
 button('渲染HTML')!.click();auth.requestEpoch++;await flush();
 expect(m.api).not.toHaveBeenCalled();expect(document.body.textContent).toContain('导入已暂停');
 button('重试确认导入结果')!.click();await flush();expect(m.api).toHaveBeenCalledTimes(2);
});
it('keeps a ZIP queue owned by the dialog even when classification finishes after an owner switch',async()=>{
 const bytes=await new JSZip().file('正文.md','# 正文').generateAsync({type:'arraybuffer'});m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{entries:[],warnings:[],counts:{documents:1,attachments:0}}:{documents:[],attachments:0,warnings:[],reused:false});let release!:(v:ArrayBuffer)=>void;const held=new Promise<ArrayBuffer>(r=>release=r);
 mount(ImportDialog,{files:[{name:'held.zip',size:bytes.byteLength,arrayBuffer:()=>held}],workspaceId:'ws',parentId:null});await flush();auth.me={id:'replacement'} as any;release(bytes);
 await vi.waitFor(()=>expect(button('导入此 ZIP')?.disabled).toBe(false));button('导入此 ZIP')!.click();await flush();expect(m.api).not.toHaveBeenCalled();expect(document.body.textContent).toContain('导入已暂停');
});
it('opens the file picker immediately on empty entry and accepts files while targets load',async()=>{
 let resolve!:(v:any[])=>void;m.list.mockReturnValue(new Promise(r=>resolve=r));
 const picked=vi.spyOn(HTMLInputElement.prototype,'click').mockImplementation(()=>{});
 mount(ImportDialog,{files:[],workspaceId:'ws',parentId:null});
 expect(picked).toHaveBeenCalledTimes(1);picked.mockRestore();
 const input=document.querySelector<HTMLInputElement>('input[type=file]')!;Object.defineProperty(input,'files',{value:[source('直接.md','# 正文')]});input.dispatchEvent(new Event('change',{bubbles:true}));await flush();resolve([]);await flush();
 expect(button('导入 1 篇')?.disabled).toBe(false);expect(button('渲染HTML')).toBeUndefined();
});
it('keeps the structured ZIP upload budget at 32 MiB, not the HTML 25 MiB budget',async()=>{
 m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{entries:[],warnings:[],counts:{documents:1,attachments:0}}:{documents:[{id:'large-note',title:'正文'}],attachments:0,warnings:[],reused:false});
 mount(ZipImportDialog,{file:{...source('large.zip'),size:26*1024*1024},target:{workspaceId:'ws',parentId:null},disabled:false});await flush();
 expect(button('导入此 ZIP')?.disabled).toBe(false);button('导入此 ZIP')!.click();await flush();expect(m.api).toHaveBeenCalledTimes(2);
});
it.each(['page.html','资料.zip'])('offers two visible choices for %s and completes the selected action without another screen',async(name)=>{
 const data=name.endsWith('.zip')?await new JSZip().file('资料/index.html','<h1>正文</h1>').file('资料/原名.md','# 资料').generateAsync({type:'arraybuffer'}):new TextEncoder().encode('<h1>正文</h1>').buffer;
 m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{files:[{path:'资料/index.html',size:20,kind:'text'}],entries:['资料/index.html'],suggested_entry:'资料/index.html',warnings:[]}:{id:'chosen-project',reused:false});
 const opened=vi.fn();mount(ImportDialog,{files:[{name,size:data.byteLength,arrayBuffer:async()=>data}],workspaceId:'ws',parentId:null,onOpen:opened});
 await vi.waitFor(()=>expect(button('渲染HTML')?.disabled).toBe(false));
 const render=button('渲染HTML')!,convert=button('转为MD笔记')!;
 expect(convert).toBeTruthy();expect(render.closest('details')).toBeNull();expect(convert.closest('details')).toBeNull();expect(m.api).not.toHaveBeenCalled();
 render.click();await vi.waitFor(()=>expect(button('完成')).toBeTruthy());
 expect(m.api.mock.calls.map(([path])=>path)).toEqual(['/web-projects/import/preview','/web-projects/import']);expect(button('预览网页项目')).toBeUndefined();
 button('打开首篇')!.click();expect(opened).toHaveBeenCalledWith('chosen-project');
});
it('imports a structured Markdown ZIP in one action, keeping folder and attachment names',async()=>{
 const created=vi.fn();m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{entries:[{path:'资料/',title:'资料',kind:'directory',parent_path:null},{path:'资料/正文.md',title:'正文',kind:'document',parent_path:'资料/'},{path:'资料/图.png',title:'图.png',kind:'attachment',parent_path:'资料/'}],warnings:[],counts:{documents:2,attachments:1}}:{documents:[{id:'folder-id',title:'资料',path:'资料/',parent_id:null},{id:'note-id',title:'正文',path:'资料/正文.md',parent_id:'folder-id'}],attachments:1,warnings:[],reused:false});
 mount(ZipImportDialog,{file:source('资料.zip','original zip bytes'),target:{workspaceId:'ws',parentId:null},disabled:false,onCreated:created});await flush();
 expect(button('预览 ZIP')).toBeUndefined();expect(button('导入此 ZIP')?.disabled).toBe(false);button('导入此 ZIP')!.click();await flush();
 expect(m.api.mock.calls.map(([path])=>path)).toEqual(['/documents/import/zip/preview','/documents/import/zip']);
 expect(created.mock.calls[0]![0].map((d:any)=>[d.path,d.parent_id])).toEqual([['资料/',null],['资料/正文.md','folder-id']]);expect(document.body.textContent).toContain('1 个附件');
 expect(m.api.mock.calls[1]![1].body.get('import_id')).toMatch(/^[0-9a-f-]{36}$/);
});
it('renders HTML in one action using the suggested entry and a frozen identity on retry',async()=>{
 const original=source('页面.html');const target=reactive({workspaceId:'ws',parentId:'folder'});const complete=vi.fn();const writes:FormData[]=[];
 m.api.mockImplementation(async(p:string,args:any)=>{
  if(p.endsWith('/preview'))return {files:[{path:'页面.html',size:20,kind:'text'}],entries:['页面.html'],suggested_entry:'页面.html',warnings:[]};
  writes.push(args.body);if(writes.length===1)throw Error('连接断开');return {id:'actual-project-id',reused:true};
 });
 mount(WebProjectImportRow,{file:original,target,onComplete:complete});await flush();
 expect(button('预览网页项目')).toBeUndefined();expect(button('渲染HTML')?.disabled).toBe(false);
 button('渲染HTML')!.click();await flush();expect(document.body.textContent).toContain('连接断开');
 target.workspaceId='other';target.parentId='changed';await flush();button('重试确认导入结果')!.click();await flush();
 expect(complete).toHaveBeenCalledWith('actual-project-id');expect(writes).toHaveLength(2);
 for(const body of writes){expect(body.get('workspace_id')).toBe('ws');expect(body.get('parent_id')).toBe('folder');expect(body.get('entry')).toBe('页面.html');}
 expect(writes[0]!.get('import_id')).toBe(writes[1]!.get('import_id'));expect(document.querySelector('input[type=radio]')).toBeNull();
});
let app:ReturnType<typeof createApp>|undefined;
const flush=async()=>{for(let i=0;i<40;i++){await Promise.resolve();await nextTick();}};
const button=(text:string)=>[...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===text);
const source=(name:string,content='<h1>原始正文</h1>')=>({name,size:new TextEncoder().encode(content).length,arrayBuffer:async()=>new TextEncoder().encode(content).buffer});
function mount(component:any,props:any){const host=document.createElement('div');document.body.append(host);app=createApp(component,props);app.mount(host);}
beforeEach(()=>{Object.assign(auth,{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});m.list.mockResolvedValue([]);m.refresh.mockResolvedValue(undefined);m.api.mockReset();});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.clearAllMocks();});
it('converts HTML in one action with internal validation and unchanged original bytes',async()=>{
 const file=source('原稿.html','<!doctype html><h1>原始正文</h1>');const created=vi.fn();
 m.api.mockImplementation(async(p:string)=>p.endsWith('/preview')?{converted_count:1,documents:[{source:'原稿.html',target:'原稿.md',markdown:'# 正文',losses:[]}],warnings:[]}:{documents:[{id:'actual-html-id',title:'原稿'}]});
 mount(HtmlConversionRow,{file,target:{workspaceId:'ws',parentId:null},onCreated:created});await flush();
 expect(button('预览转换')).toBeUndefined();expect(button('转为MD笔记')?.disabled).toBe(false);
 button('转为MD笔记')!.click();await flush();
 expect(m.api.mock.calls.map(([path])=>path)).toEqual(['/documents/import/html/preview','/documents/import/html']);
 expect(created).toHaveBeenCalledWith([{id:'actual-html-id',title:'原稿'}]);
 const bodies=m.api.mock.calls.map(([,args])=>args.body as FormData);
 for(const body of bodies){expect(body.get('file')).toBeInstanceOf(Blob);expect(body.get('workspace_id')).toBe('ws');expect((body.get('file') as File).name).toBe('原稿.html');}
 expect(bodies[1]!.get('import_id')).toMatch(/^[0-9a-f-]{36}$/);
 expect(document.querySelector('.import-read-preview')).toBeNull();expect(button('已导入')).toBeTruthy();
});
