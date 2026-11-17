import {createApp} from 'vue';
import {afterEach,expect,it,vi} from 'vitest';
const m=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn(),list:vi.fn()}));
vi.mock('../../api/client',()=>({api:m.api}));
vi.mock('../../api/notes',()=>({listDocs:m.list}));
vi.mock('../../stores/notes',()=>({useNotesStore:()=>({workspaces:[{id:'workspace',name:'笔记本'}],refreshList:m.refresh})}));
vi.mock('../home/auth',()=>({auth:{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}}));
import ImportDialog from './ImportDialog.vue';
let dispose:()=>void=()=>{};
afterEach(()=>{dispose();vi.clearAllMocks();});
const click=(text:string)=>{const button=[...document.querySelectorAll('button')].find(b=>b.textContent?.includes(text));expect(button, text).toBeTruthy();button!.click();};
it('renders original webpage import with automatic entry, preserves identity after uncertain result',async()=>{
 m.list.mockResolvedValue([]);m.refresh.mockResolvedValue(undefined);
 const writes:{id:string;entry:string;workspace:string}[]=[];
 m.api.mockImplementation(async(path:string,args:any)=>{
  if(path==='/web-projects/import/preview')return {files:[{path:'index.html',size:20,kind:'text'}],entries:['index.html','quiz.html'],suggested_entry:null,warnings:[]};
  if(path==='/web-projects/import') {writes.push({id:args.body.get('import_id'),entry:args.body.get('entry'),workspace:args.body.get('workspace_id')});if(writes.length===1)throw Error('网络断开，结果未知');return {id:'project',reused:true};}
  throw Error('unexpected '+path);
 });
 const host=document.createElement('div');document.body.append(host);
 const app=createApp(ImportDialog,{files:[{name:'quiz.html',size:20,arrayBuffer:async()=>new TextEncoder().encode('<h1>Quiz</h1>').buffer}],workspaceId:'workspace',parentId:null});app.mount(host);dispose=()=>{app.unmount();host.remove();};
 await vi.waitFor(()=>expect(m.list).toHaveBeenCalled());
 await vi.waitFor(()=>expect([...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='渲染HTML')?.disabled).toBe(false));
 click('渲染HTML');await vi.waitFor(()=>expect(document.body.textContent).toContain('网络断开'));
 click('重试确认');await vi.waitFor(()=>expect(document.body.textContent).toContain('网页项目已导入'));
 expect(writes).toHaveLength(2);expect(writes[0]).toEqual(writes[1]);expect(writes[0]?.entry).toBe('index.html');expect(writes[0]?.id).toMatch(/^[0-9a-f-]{36}$/);expect(m.refresh).toHaveBeenCalled();
});
