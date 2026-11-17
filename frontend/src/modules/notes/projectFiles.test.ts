import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {createApp,defineComponent,h,nextTick,ref,provide,type App} from 'vue';
const mocks=vi.hoisted(()=>({list:vi.fn(),source:vi.fn(),entry:vi.fn(),toast:vi.fn()}));
// Synthetic project workspaces contain no detached source identities.
vi.mock('../../api/detachedSources',()=>({listDetachedSources:vi.fn(async()=>[])}));
vi.mock('../../api/webProjects',()=>({listProjectIdentities:async()=>(await mocks.list()).map((p:any)=>({id:p.id,workspace_id:p.workspace_id,members:[p.id,...p.files.map((f:any)=>f.id),...(p.directories??[]).map((d:any)=>d.id)]})),getProject:async()=>project,getProjectSource:mocks.source}));
vi.mock('../../api/projectFiles',()=>({setProjectEntry:mocks.entry}));
vi.mock('../../composables/useToast',()=>({toast:mocks.toast}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
vi.mock('../../stores/notes',async()=>({useNotesStore:()=>store}));
import ProjectFiles from './ProjectFiles.vue';
import DocTreeNode from './DocTreeNode.vue';
import {useWebProjectCatalog} from './useWebProjectCatalog';
import {projectCatalogKey,PROJECT_ASSET_MIME} from './projectAssetCopy';
import {auth} from '../home/auth';
const root='10000000-0000-4000-8000-000000000001',image='10000000-0000-4000-8000-000000000002';
const project:any={id:root,workspace_id:'ws',title:'Project',entry:'index.html',entry_file_id:'entry',directories:[{id:'assets',path:'assets',kind:'directory'}],files:[{id:'entry',path:'index.html',kind:'text',mime:'text/html',size:8,updated_at:'v1'},{id:'second',path:'second.html',kind:'text',mime:'text/html',size:9,updated_at:'v1'},{id:image,path:'assets/cat.png',kind:'binary',mime:'image/png',size:1234,updated_at:'v1'}]};
const store={userId:'owner',workspaceId:'ws',draggingId:null as string|null};
let app:App,host:HTMLElement;
const settle=async()=>{for(let n=0;n<10;n++){await Promise.resolve();await nextTick();}};
function mount(component:any){host=document.createElement('div');document.body.append(host);app=createApp(component);app.mount(host);}
function transfer(){const data:Record<string,string>={};return {setData:(t:string,v:string)=>data[t]=v,getData:(t:string)=>data[t]||'',get types(){return Object.keys(data);},effectAllowed:'',dropEffect:''};}
function drag(el:Element,type:string,dt:any){const e=new Event(type,{bubbles:true,cancelable:true});Object.defineProperty(e,'dataTransfer',{value:dt});el.dispatchEvent(e);return e;}
beforeEach(()=>{vi.clearAllMocks();Object.assign(auth,{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});store.draggingId=null;mocks.list.mockResolvedValue([project]);});
afterEach(()=>{app?.unmount();host?.remove();});
describe('project directories, details and tree copy boundary',()=>{
 it('classifies an authoritative directory as project, not ordinary Markdown',async()=>{
  let catalog!:ReturnType<typeof useWebProjectCatalog>;mount(defineComponent({setup(){catalog=useWebProjectCatalog(store,ref(true));return()=>h('div');}}));
  await catalog.load();expect(catalog.identityFor('assets')?.id).toBe(root);expect(catalog.projectFor('unknown')).toBeNull();
 });
 it('directory view lists children and binary detail shows exact MIME/bytes with image drag MIME',async()=>{
  const selected=ref('assets');mocks.source.mockResolvedValue({...project.files[2],url:'/attachments/20000000-0000-4000-8000-000000000001',content:null});
  mount(defineComponent({setup:()=>()=>h(ProjectFiles,{project,fileId:selected.value,active:true,onOpen:(id:string)=>selected.value=id})}));await settle();
  expect(host.textContent).toContain('assets/cat.png');expect(mocks.source).not.toHaveBeenCalled();
  host.querySelector<HTMLButtonElement>(`[data-project-file="${image}"]`)!.click();await settle();
  expect(host.textContent).toContain('image/png');expect(host.textContent).toContain('1234');expect(host.querySelector('img')).not.toBeNull();
  const dt=transfer();drag(host.querySelector('img')!,'dragstart',dt);expect(JSON.parse(dt.getData(PROJECT_ASSET_MIME))).toEqual({root,file:image,path:'assets/cat.png',mime:'image/png'});
 });
 it('changes entry only after the navigation barrier; emits a confirmed manifest and never launches runtime',async()=>{
  const barrier=vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true),updated=vi.fn();mocks.entry.mockResolvedValue({...project,entry:'second.html',entry_file_id:'second'});
  mount(defineComponent({setup:()=>()=>h(ProjectFiles,{project,fileId:root,active:true,beforeChange:barrier,onUpdated:updated})}));await settle();
  expect(host.querySelector('select')).toBeNull();
  const trigger=host.querySelector<HTMLButtonElement>('[aria-label="网页入口"]')!;trigger.click();await settle();
  const option=[...host.querySelectorAll<HTMLButtonElement>('[role=option]')].find(b=>b.textContent==='second.html')!;option.focus();option.click();await settle();
  expect(document.activeElement).toBe(trigger);
  host.querySelector<HTMLButtonElement>('[data-set-entry]')!.click();await settle();expect(mocks.entry).not.toHaveBeenCalled();
  host.querySelector<HTMLButtonElement>('[data-set-entry]')!.click();await settle();expect(mocks.entry).toHaveBeenCalledWith(root,'second','entry');expect(updated).toHaveBeenCalledWith(expect.objectContaining({entry:'second.html'}));expect(host.textContent).toContain('手动刷新');
 });
 it('tree image drop on ordinary note never invokes move and points to body copy',async()=>{
  const drop=vi.fn();const node=(id:string)=>({id,title:id,parent_id:null,children:[]});
  mount(defineComponent({setup(){provide(projectCatalogKey,{projectFor:id=>id===image?project:null});return()=>h('div',[h(DocTreeNode,{node:node(image) as any,depth:0,currentId:null,expanded:new Set<string>()}),h(DocTreeNode,{node:node('ordinary') as any,depth:0,currentId:null,expanded:new Set<string>(),onDropOn:drop})]);}}));
  const rows=host.querySelectorAll('.row'),dt=transfer();drag(rows[0]!,'dragstart',dt);expect(dt.getData(PROJECT_ASSET_MIME)).not.toBe('');
  drag(rows[1]!,'drop',dt);await settle();expect(drop).not.toHaveBeenCalled();expect(mocks.toast).toHaveBeenCalledWith(expect.stringContaining('正文'));expect(store.draggingId).toBeNull();
 });
 it('rejects a ProjectFiles image dropped on a tree row even without store draggingId',async()=>{
  const drop=vi.fn();mount(defineComponent({setup:()=>()=>h(DocTreeNode,{node:{id:'ordinary',title:'note',children:[]} as any,depth:0,currentId:null,expanded:new Set<string>(),onDropOn:drop})}));
  const dt=transfer();dt.setData(PROJECT_ASSET_MIME,JSON.stringify({root,file:image,path:'assets/cat.png',mime:'image/png'}));drag(host.querySelector('.row')!,'drop',dt);await settle();expect(drop).not.toHaveBeenCalled();expect(mocks.toast).toHaveBeenCalledWith(expect.stringContaining('正文'));
 });
 it('allows moving a whole project root to an ordinary folder',async()=>{
  const drop=vi.fn();const node=(id:string)=>({id,title:id,parent_id:null,children:[]});
  mount(defineComponent({setup(){provide(projectCatalogKey,{projectFor:id=>id===root?project:null});return()=>h('div',[h(DocTreeNode,{node:node(root) as any,depth:0,currentId:null,expanded:new Set<string>()}),h(DocTreeNode,{node:node('ordinary') as any,depth:0,currentId:null,expanded:new Set<string>(),onDropOn:drop})]);}}));
  const rows=host.querySelectorAll('.row'),dt=transfer();drag(rows[0]!,'dragstart',dt);drag(rows[1]!,'drop',dt);await settle();expect(drop).toHaveBeenCalledOnce();
 });
 it('hides binary private media at auth suspension and ignores late source replies',async()=>{
  let resolve!:(x:any)=>void;mocks.source.mockReturnValue(new Promise(r=>resolve=r));
  mount(defineComponent({setup:()=>()=>h(ProjectFiles,{project,fileId:image,active:true})}));auth.suspended=true;
  resolve({...project.files[2],url:'/attachments/private',content:null});await settle();expect(host.querySelector('img,a[download]')).toBeNull();
 });
});
