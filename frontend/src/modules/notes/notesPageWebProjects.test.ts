import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {createApp,defineComponent,h,nextTick,KeepAlive,ref,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {createMemoryHistory,createRouter,RouterView} from 'vue-router';

const mocks=vi.hoisted(()=>({catalog:vi.fn(),manifests:new Map<string,any>(),navigation:vi.fn(),deletion:vi.fn(),editorNavigation:vi.fn(),toast:vi.fn(),realPane:false,source:vi.fn(),saveSource:vi.fn(),launch:vi.fn(),saveState:vi.fn(),getDoc:vi.fn()}));
// Synthetic project workspaces contain no detached source identities.
vi.mock('../../api/detachedSources',()=>({listDetachedSources:vi.fn(async()=>[])}));
vi.mock('../../api/webProjects',()=>({listProjects:mocks.catalog,listProjectIdentities:async(workspace:string)=>(await mocks.catalog(workspace)).map((p:any)=>{mocks.manifests.set(p.id,p);return {id:p.id,workspace_id:p.workspace_id,members:[p.id,...p.files.map((f:any)=>f.id),...(p.directories??[]).map((d:any)=>d.id)]};}),getProject:async(id:string)=>{if(id==='broken')throw Error('invalid project path');return mocks.manifests.get(id);},getProjectSource:mocks.source,saveProjectSource:mocks.saveSource,launchProject:mocks.launch,saveProjectState:mocks.saveState,resetProjectState:vi.fn()}));
vi.mock('../../api/notes',()=>({getDoc:mocks.getDoc,listTemplates:vi.fn(async()=>({root_id:'templates'})),listDocs:vi.fn(async()=>[]),listTrash:vi.fn(async()=>[])}));
vi.mock('../home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})};});
vi.mock('../../composables/useToast',()=>({toast:mocks.toast}));
vi.mock('../../stores/notes',async()=>{const {defineStore}=await import('pinia');return {buildTree:(docs:any[])=>docs.map(d=>({...d,children:[]})),useNotesStore:defineStore('notes-project-wiring',{
 state:()=>({userId:'alice',workspaceId:'w1',docs:[] as any[],allDocs:[] as any[],workspaces:[{id:'w1',name:'One'},{id:'w2',name:'Two'}],recent:[],tags:[],docTags:[],searchQuery:'',searching:false,filterTagId:null,pendingDelete:null as any,hideProtectedId:null,templateRootId:null,trash:[],draggingId:null}),
 actions:{bootstrap:vi.fn(async()=>{}),resetSession(){this.userId='';this.workspaceId='';this.docs=[];this.allDocs=[];},refreshList:vi.fn(async()=>{}),refreshRecent:vi.fn(async()=>{}),refreshWorkspaces:vi.fn(async()=>{}),refreshTags:vi.fn(async()=>{}),refreshTrash:vi.fn(async()=>{}),switchWorkspace:vi.fn(async function(this:any,id:string){this.workspaceId=id;this.docs=[];this.allDocs=[];}),addWorkspace:vi.fn(async()=>{}),deleteCurrentWorkspace:vi.fn(async()=> 'deleted'),renameCurrentWorkspace:vi.fn(),requestDelete(doc:any){this.pendingDelete={doc};},pathOf:()=>'',moveTo:vi.fn()}
 })};});
vi.mock('../../stores/notesPreferences',async()=>{const {defineStore}=await import('pinia');return {useNotesPreferencesStore:defineStore('preferences-project-wiring',{state:()=>({draft:{},owner:''}),actions:{bindOwner(id:string){this.owner=id;},load:async()=>true,save:async()=>true}})};});
vi.mock('./WebProjectPane.vue',async()=>{
 const Actual=(await vi.importActual<typeof import('./WebProjectPane.vue')>('./WebProjectPane.vue')).default;
 return {default:defineComponent({name:'WebProjectPane',props:['project','fileId','active'],emits:['open','directory','saved'],setup(props,{expose,emit}){
  const child=ref<InstanceType<typeof Actual>|null>(null);
  expose({prepareNavigation:()=>mocks.realPane?child.value!.prepareNavigation():mocks.navigation(),prepareDeletion:()=>mocks.realPane?child.value!.prepareDeletion():mocks.deletion()});
  return()=>mocks.realPane?h(Actual,{ref:child,project:props.project,fileId:props.fileId,active:props.active,onOpen:(id:string)=>emit('open',id),onDirectory:()=>emit('directory'),onSaved:()=>emit('saved')}):h('section',{'data-project':props.project.id,'data-file':props.fileId},[props.active?h('iframe',{title:'fixture project'}):null,h('button',{'data-open-source':'',onClick:()=>emit('open','source')},'source')]);
 }})};
});
vi.mock('./ProjectSourceEditor.vue',()=>({default:defineComponent({props:['modelValue','filename','readonly'],emits:['update:modelValue'],setup(props,{emit}){return()=>h('textarea',{'data-source-editor':props.filename,value:props.modelValue,readonly:props.readonly,onInput:(event:Event)=>emit('update:modelValue',(event.target as HTMLTextAreaElement).value)});}})}));
vi.mock('./DocEditor.vue',()=>({default:defineComponent({props:['docId'],emits:['open','create-child','saved','deleted'],setup(props,{expose}){expose({prepareNavigation:mocks.editorNavigation,prepareDeletion:mocks.deletion});return()=>h('article',{'data-editor':props.docId},'ordinary editor');}})}));
vi.mock('./DeleteNoteDialog.vue',()=>({default:defineComponent({props:['beforeTrash'],emits:['deleted'],setup(props,{emit}){return()=>h('div',[h('button',{'data-delete-confirm':'',onClick:()=>props.beforeTrash(['root','source'])},'delete'),h('button',{'data-deleted':'',onClick:()=>emit('deleted')},'deleted')]);}})}));
vi.mock('./GraphPanel.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-panel':'graph'})})}));
vi.mock('./AttachmentsPanel.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-panel':'attachments'})})}));
vi.mock('./TrashPanel.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-panel':'trash'})})}));
vi.mock('./NotesSettings.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-settings':''})})}));
vi.mock('./ImportDialog.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-import':''})})}));
vi.mock('./NewChildDialog.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-new':''})})}));
vi.mock('./MoveDialog.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-move':''})})}));
import NotesPage from './NotesPage.vue';
import {auth} from '../home/auth';
import {useNotesStore} from '../../stores/notes';
const project={id:'root',workspace_id:'w1',title:'Project',entry:'index.html',files:[{id:'source',path:'readme.md',kind:'text',mime:'text/markdown',updated_at:'v1'},{id:'image',path:'cat.png',kind:'binary',mime:'image/png',updated_at:'v1'}]};
const docs=['root','source','image','ordinary'].map(id=>({id,title:id,parent_id:null,updated_at:'v1',created_at:'v1'}));
let app:App|null=null,host:HTMLElement;
const settle=async()=>{for(let i=0;i<12;i++){await Promise.resolve();await nextTick();}};
function deferred<T>(){let resolve!:(v:T)=>void,reject!:(e:Error)=>void;const promise=new Promise<T>((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
async function mountPage(keepalive=false,initial='/notes'){
 const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.docs=docs as any;store.allDocs=docs as any;
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/notes',component:NotesPage},{path:'/settings',component:{render:()=>h('section',{'data-unified-settings':''})}},{path:'/other',component:{render:()=>h('div','other')}},{path:'/public',meta:{public:true},component:{render:()=>h('div','public')}}]});
 await router.push(initial);await router.isReady();host=document.createElement('div');document.body.append(host);
 app=createApp(defineComponent({setup:()=>()=>keepalive?h(RouterView,{}, {default:({Component}:any)=>h(KeepAlive,{},()=>Component)}):h(RouterView)}));app.use(pinia);app.use(router);app.mount(host);await settle();return {store,router};
}
async function clickDoc(id:string){const el=host.querySelector<HTMLElement>(`[data-import-parent="${id}"] .title`)??host.querySelector<HTMLElement>(`[data-import-parent="${id}"]`);expect(el,`list entry ${id}`).not.toBeNull();el!.click();await settle();}
function clickText(text:string){const el=[...host.querySelectorAll<HTMLElement>('button,.trash-entry,.ws-opt')].find(el=>el.textContent?.trim()===text);expect(el,`action ${text}`).toBeTruthy();el!.click();}
beforeEach(()=>{vi.clearAllMocks();mocks.realPane=false;localStorage.clear();Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});mocks.getDoc.mockImplementation(async(id:string)=>({id,workspace_id:'w1'}));mocks.catalog.mockResolvedValue([project]);mocks.navigation.mockResolvedValue(true);mocks.deletion.mockResolvedValue(true);mocks.editorNavigation.mockResolvedValue(true);vi.stubGlobal('WebSocket',class {static OPEN=1;readyState=1;close(){};});});
afterEach(()=>{app?.unmount();app=null;host?.remove();vi.unstubAllGlobals();});
describe('NotesPage project dispatch (real mounted page/list/router)',()=>{
 it.each(['/notes','/notes?settings=open'])('keeps the settings action and legacy query in the notes drawer from %s',async initial=>{
  const {router}=await mountPage(false,initial);if(initial==='/notes'){clickText('笔记设置');await settle();}
  expect(router.currentRoute.value.path).toBe('/notes');expect(host.querySelector('.notes-settings-drawer')).not.toBeNull();expect(host.querySelector('[data-settings]')).not.toBeNull();
 });
 it('saves the ordinary editor before opening settings and returns focus without replacing its DOM',async()=>{
  const {router}=await mountPage();await clickDoc('ordinary');const editor=host.querySelector('[data-editor=ordinary]');
  const barrier=deferred<boolean>();mocks.editorNavigation.mockReturnValueOnce(barrier.promise);
  const trigger=host.querySelector<HTMLButtonElement>('button.notes-settings-link')!;trigger.focus();trigger.click();await settle();
  expect(mocks.editorNavigation).toHaveBeenCalled();expect(host.querySelector('.notes-settings-drawer')).toBeNull();
  barrier.resolve(true);await settle();expect(host.querySelector('[data-editor=ordinary]')).toBe(editor);expect(router.currentRoute.value.path).toBe('/notes');
  const close=host.querySelector<HTMLButtonElement>('[aria-label="关闭笔记设置"]')!;expect(document.activeElement).toBe(close);close.click();await settle();expect(document.activeElement).toBe(trigger);
 });
 it('refuses settings when an ordinary draft save fails',async()=>{
  await mountPage();await clickDoc('ordinary');mocks.editorNavigation.mockResolvedValue(false);clickText('笔记设置');await settle();expect(host.querySelector('.notes-settings-drawer')).toBeNull();expect(host.querySelector('[data-editor=ordinary]')).not.toBeNull();
 });
 it.each(['owner','session','epoch','suspended','sessionClosing','workspace','keepalive'])('fences settings opening and closes an existing drawer on %s',async boundary=>{
  const {store,router}=await mountPage(true);clickText('笔记设置');await settle();expect(host.querySelector('.notes-settings-drawer')).not.toBeNull();
  if(boundary==='owner')auth.me={id:'bob'} as any;
  if(boundary==='session')auth.sessionGeneration++;
  if(boundary==='epoch')auth.requestEpoch++;
  if(boundary==='suspended')auth.suspended=true;
  if(boundary==='sessionClosing')auth.sessionClosing=true;
  if(boundary==='workspace')store.workspaceId='w2';
  if(boundary==='keepalive')await router.push('/other');
  await settle();expect(host.querySelector('.notes-settings-drawer')).toBeNull();
 });
 it('skins retry/empty and settings buttons with Stella classes',async()=>{
  mocks.catalog.mockRejectedValue(Error('offline'));await mountPage();expect([...host.querySelectorAll('button')].find(b=>b.textContent==='重试')?.classList.contains('ghost-btn')).toBe(true);expect(host.querySelector('button.notes-settings-link')?.classList.contains('ghost-btn')).toBe(true);
 });
 it('opens an ordinary article beside a broken project, and never sends its raw source to Markdown',async()=>{
  const broken={...project,id:'broken'};mocks.catalog.mockResolvedValue([broken]);localStorage.setItem('stella_current_doc','ordinary');await mountPage();expect(host.querySelector('[data-editor=ordinary]')).not.toBeNull();
  await clickDoc('source');expect(host.querySelector('[data-editor=source]')).toBeNull();expect(host.querySelector('[data-editor=ordinary]')).not.toBeNull();expect(host.textContent).toContain('invalid project path');
 });
 it('keeps the selected editor DOM on same-owner profile replacement and suspended reauthentication',async()=>{
  await mountPage();await clickDoc('ordinary');const editor=host.querySelector('[data-editor="ordinary"]');expect(editor).not.toBeNull();
  auth.me={...auth.me!};await settle();expect(host.querySelector('[data-editor="ordinary"]')).toBe(editor);
  auth.suspended=true;auth.requestEpoch++;await settle();auth.suspended=false;auth.requestEpoch++;auth.me={...auth.me!};await settle();expect(host.querySelector('[data-editor="ordinary"]')).toBe(editor);
 });
 it.each(['owner','guest','session','workspace'])('clears private selection on real %s identity change',async boundary=>{
  const {store}=await mountPage();await clickDoc('ordinary');const oldEditor=host.querySelector('[data-editor="ordinary"]')!;
  if(boundary==='owner')auth.me={id:'bob'} as any;
  if(boundary==='guest')auth.me=null;
  if(boundary==='session')auth.sessionGeneration++;
  if(boundary==='workspace')store.workspaceId='w2';
  await settle();expect(oldEditor.isConnected).toBe(false);
  if(boundary==='owner'||boundary==='guest')expect(host.querySelector('[data-editor],[data-project]')).toBeNull();
 });
 it('allows revoked-owner exit only to public without invoking private save barriers',async()=>{
  const {router}=await mountPage();auth.suspended=true;auth.sessionClosing=true;auth.sessionGeneration++;auth.me=null;auth.suspended=false;auth.sessionClosing=false;
  await router.push('/public');await settle();expect(router.currentRoute.value.path).toBe('/public');expect(host.querySelector('[data-project],[data-editor]')).toBeNull();expect(mocks.navigation).not.toHaveBeenCalled();
 });
 it.each(['retained-owner','guest-private-target'])('retains navigation fence for %s',async boundary=>{
  const {router}=await mountPage();auth.suspended=true;
  if(boundary==='guest-private-target')auth.me=null;
  await router.push(boundary==='retained-owner'?'/public':'/other');await settle();expect(router.currentRoute.value.path).toBe('/notes');expect(mocks.navigation).not.toHaveBeenCalled();
 });
 it('honors a list click made while the initial catalog is pending instead of replacing it with the first root',async()=>{
  const catalog=deferred<any[]>();mocks.catalog.mockReturnValueOnce(catalog.promise);await mountPage();void clickDoc('source');await settle();catalog.resolve([project]);await settle();expect(host.querySelector('[data-file="source"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
 });
 it.each(['new','delete'])('guards workspace %s before calling its store mutation',async action=>{
  const {store}=await mountPage();const prompt=vi.spyOn(window,'prompt').mockReturnValue('New');const add=vi.spyOn(store,'addWorkspace'),del=vi.spyOn(store,'deleteCurrentWorkspace');const batch=vi.fn();(store as any).deleteWorkspaceBatch=batch;mocks.navigation.mockResolvedValue(false);mocks.deletion.mockResolvedValue(false);
  host.querySelector<HTMLElement>('.ws-current')!.click();await settle();clickText(action==='new'?'新建工作区':'删除工作区');await settle();if(action==='delete'){const confirm=[...document.querySelectorAll<HTMLButtonElement>('[role=dialog] button')].find(button=>button.textContent==='确认永久删除');expect(confirm,'explicit permanent workspace confirmation').toBeTruthy();expect(confirm!.disabled).toBe(false);confirm!.click();await settle();expect(mocks.deletion).toHaveBeenCalled();expect(batch).not.toHaveBeenCalled();}
  expect(add).not.toHaveBeenCalled();expect(del).not.toHaveBeenCalled();expect(prompt).not.toHaveBeenCalled();expect(store.workspaceId).toBe('w1');expect(host.querySelector('[data-project="root"]')).not.toBeNull();prompt.mockRestore();
 });
 it.each(['suspended','sessionClosing','owner','keepalive'])('removes a real project iframe on %s',async boundary=>{
  mocks.realPane=true;mocks.launch.mockResolvedValue({url:'https://runtime.invalid/fixture',source_origin:location.origin,target_origin:'https://runtime.invalid',capability:'fixture',expires_in:900,state:{revision:0,epoch:1,data:{}}});const {router}=await mountPage(true);const frame=host.querySelector('iframe')!;expect(frame).not.toBeNull();
  if(boundary==='owner')auth.me={id:'bob'} as any;else if(boundary==='keepalive')await router.push('/other');else (auth as any)[boundary]=true;
  await settle();expect(host.querySelector('iframe')).toBeNull();expect(frame.isConnected).toBe(false);
  // Owner replacement unmounts the whole pane; retained test references to its
  // detached DOM subtree need not have their parent pointers rewritten.
  if(boundary!=='owner')expect(frame.parentElement).toBeNull();
 });
 it('suspends the project after successful delete preparation so permanent confirmation cannot acquire new unsaved iframe state',async()=>{
  const {store}=await mountPage();host.querySelector<HTMLElement>('[data-import-parent="root"] button[title="删除"]')!.click();await settle();expect(mocks.deletion).toHaveBeenCalledOnce();expect(store.pendingDelete).not.toBeNull();expect(host.querySelector('iframe')).toBeNull();expect(host.querySelector('[data-project="root"]')).not.toBeNull();store.pendingDelete=null;await settle();expect(host.querySelector('iframe')).not.toBeNull();
 });
 it('does not revive an in-flight navigation across suspend/resume even if the visible scope values return to the same values',async()=>{
  await mountPage();const barrier=deferred<boolean>();mocks.navigation.mockReturnValueOnce(barrier.promise);void clickDoc('ordinary');await settle();auth.suspended=true;await settle();auth.suspended=false;await settle();barrier.resolve(true);await settle();expect(host.querySelector('[data-project="root"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
 });
 it('honors an initial deep link to a project source without mounting the first root as an intermediate editor',async()=>{
  await mountPage(false,'/notes?doc=source');expect(host.querySelector('[data-file="source"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
 });
 it('opens a cross-workspace deep link even when the new first document is another project',async()=>{
  const {store,router}=await mountPage();const second={...project,id:'second',workspace_id:'w2',files:[{...project.files[0],id:'second-source'}]};
  mocks.getDoc.mockResolvedValue({id:'second-source',workspace_id:'w2'});mocks.catalog.mockImplementation(async(id:string)=>id==='w2'?[second]:[project]);vi.spyOn(store,'switchWorkspace').mockImplementationOnce(async(id:string)=>{store.workspaceId=id;store.docs=[{...docs[0],id:'second'},{...docs[1],id:'second-source'}] as any;store.allDocs=store.docs;});
  await router.push('/notes?doc=second-source');await settle();expect(host.querySelector('[data-file="second-source"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
 });
 it('checks the save barrier after a delayed catalog, not only before it',async()=>{
  const {store}=await mountPage();const catalog=deferred<any[]>();mocks.catalog.mockReturnValueOnce(catalog.promise);store.allDocs=[...docs] as any;await settle();
  void clickDoc('ordinary');await settle();mocks.navigation.mockResolvedValue(false);catalog.resolve([project]);await settle();expect(host.querySelector('[data-project="root"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
 });
 it('does not let a late deep-link lookup switch the workspace of a new owner',async()=>{
  const {store,router}=await mountPage();const lookup=deferred<any>();mocks.getDoc.mockReturnValueOnce(lookup.promise);await router.push('/notes?doc=linked');await settle();auth.me={id:'bob'} as any;store.userId='bob';lookup.resolve({id:'linked',workspace_id:'w2'});await settle();expect(store.workspaceId).toBe('w1');expect(host.querySelector('[data-file="linked"],[data-editor="linked"]')).toBeNull();
 });
 it('mounts the real WebProjectPane: root iframe, markdown source, image preview and an actual failed save blocks navigation',async()=>{
  mocks.realPane=true;mocks.launch.mockResolvedValue({url:'https://runtime.invalid/fixture',source_origin:location.origin,target_origin:'https://runtime.invalid',capability:'fixture',expires_in:900,state:{revision:0,epoch:1,data:{}}});
  mocks.source.mockImplementation(async(_root:string,id:string)=>({...project.files.find(f=>f.id===id),content:id==='source'?'# raw markdown':null,url:id==='image'?'/fixture.png':null}));
  mocks.saveSource.mockRejectedValue(Error('fixture save failed'));await mountPage();expect(host.querySelector('.web-project-pane iframe')).not.toBeNull();
  await clickDoc('image');expect(host.querySelector<HTMLImageElement>('.web-project-pane img')?.getAttribute('src')).toBe('/fixture.png');expect(host.querySelector('[data-editor]')).toBeNull();
  await clickDoc('source');const source=host.querySelector<HTMLTextAreaElement>('[data-source-editor="readme.md"]')!;expect(source.value).toBe('# raw markdown');
  source.value='unsaved project source';source.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();await clickDoc('ordinary');expect(mocks.saveSource).toHaveBeenCalledWith('root','source','v1','unsaved project source');expect(host.querySelector('[data-editor]')).toBeNull();expect(source.value).toBe('unsaved project source');expect(host.textContent).toContain('fixture save failed');
 });
 it('refreshes catalog after list changes; a superseded same-workspace reply cannot classify a new project as an ordinary note',async()=>{
  const {store}=await mountPage();const stale=deferred<any[]>(),fresh=deferred<any[]>();mocks.catalog.mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
  store.allDocs=[...docs] as any;await settle();store.allDocs=[...docs,{...docs[0],id:'new-root'}] as any;store.docs=store.allDocs;await settle();
  fresh.resolve([project,{...project,id:'new-root',files:[]}]);await settle();stale.resolve([]);await settle();await clickDoc('new-root');expect(host.querySelector('[data-project="new-root"]')).not.toBeNull();
 });
 it('does not unmount a dirty project when a catalog refresh fails, and refuses unknown-document dispatch',async()=>{
  const {store}=await mountPage();const pane=host.querySelector('[data-project]');mocks.catalog.mockRejectedValue(Error('offline'));store.allDocs=[...docs] as any;await settle();await clickDoc('ordinary');expect(host.querySelector('[data-project]')).toBe(pane);expect(host.querySelector('[data-editor]')).toBeNull();expect(host.textContent).toContain('网页项目目录');
 });
 it('blocks a same-route deep link before its URL changes when project saving fails',async()=>{
  const {router}=await mountPage();mocks.navigation.mockResolvedValue(false);await router.push('/notes?doc=ordinary');await settle();expect(router.currentRoute.value.query.doc).not.toBe('ordinary');expect(host.querySelector('[data-project="root"]')).not.toBeNull();
 });
 it('clears the project classification after deletion before selecting a remaining ordinary note',async()=>{
  const {store}=await mountPage();store.requestDelete(docs[0] as any);await settle();store.allDocs=[docs[3]] as any;store.docs=store.allDocs;mocks.catalog.mockResolvedValue([]);host.querySelector<HTMLElement>('[data-deleted]')!.click();await settle();expect(host.querySelector('[data-editor="ordinary"]')).not.toBeNull();expect(host.querySelector('[data-project]')).toBeNull();
 });
 it('awaits prepareDeletion before even opening the delete dialog, including permanent-delete preferences',async()=>{
  const {store}=await mountPage();mocks.deletion.mockResolvedValue(false);host.querySelector<HTMLElement>('[data-import-parent="root"] button[title="删除"]')!.click();await settle();expect(mocks.deletion).toHaveBeenCalled();expect(store.pendingDelete).toBeNull();expect(host.querySelector('[data-project]')).not.toBeNull();
 });
 it('destroys the iframe on keepalive deactivation and remounts it only after reactivation',async()=>{
  const {router}=await mountPage(true);const frame=host.querySelector('iframe')!;expect(frame).not.toBeNull();await router.push('/other');await settle();expect(frame.parentElement).toBeNull();await router.push('/notes');await settle();expect(host.querySelector('iframe')).not.toBeNull();
 });
 it('fails closed when catalog loading fails, including direct list clicks, then retries without treating source as markdown',async()=>{
  mocks.catalog.mockRejectedValueOnce(Error('offline'));await mountPage();expect(host.querySelector('[data-editor],[data-project]')).toBeNull();
  mocks.catalog.mockRejectedValue(Error('offline'));await clickDoc('source');expect(host.querySelector('[data-editor],[data-project]')).toBeNull();expect(host.textContent).toContain('网页项目目录');
  mocks.catalog.mockResolvedValue([project]);clickText('重试');await settle();await clickDoc('source');expect(host.querySelector('[data-file="source"]')).not.toBeNull();
 });
 it.each(['owner','session','epoch','workspace'])('rejects a late catalog from an obsolete %s',async boundary=>{
  const old=deferred<any[]>();mocks.catalog.mockReturnValueOnce(old.promise);const {store}=await mountPage();
  if(boundary==='owner'){auth.me={id:'bob'} as any;store.userId='bob';}
  if(boundary==='session')auth.sessionGeneration++;
  if(boundary==='epoch')auth.requestEpoch++;
  if(boundary==='workspace')store.workspaceId='w2';
  mocks.catalog.mockResolvedValue([]);await settle();old.resolve([project]);await settle();
  expect(host.querySelector('[data-project="root"]')).toBeNull();
 });
 it('loads the new workspace catalog before dispatching its first document',async()=>{
  const {store}=await mountPage();const second={...project,id:'second',workspace_id:'w2',files:[]};
  mocks.catalog.mockImplementation(async(id:string)=>id==='w2'?[second]:[project]);
  vi.spyOn(store,'switchWorkspace').mockImplementationOnce(async(id:string)=>{store.workspaceId=id;store.docs=[{...docs[0],id:'second'}] as any;store.allDocs=store.docs;});
  host.querySelector<HTMLElement>('.ws-current')!.click();await settle();clickText('Two');await settle();expect(host.querySelector('[data-project="second"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
 });
 it('does not finish a pending navigation after authentication changes',async()=>{
  await mountPage();const barrier=deferred<boolean>();mocks.navigation.mockReturnValue(barrier.promise);void clickDoc('ordinary');await settle();auth.suspended=true;auth.requestEpoch++;barrier.resolve(true);await settle();expect(host.querySelector('[data-editor]')).toBeNull();expect(host.querySelector('iframe')).toBeNull();
 });
 it.each(['ordinary','source','附件','回收站','图谱','新建','导入','笔记设置','workspace','route'])('awaits failed project save before %s and keeps the mounted content',async action=>{
  const {store,router}=await mountPage();const barrier=deferred<boolean>();mocks.navigation.mockReturnValue(barrier.promise);
  const pane=host.querySelector('[data-project]');
  if(action==='ordinary'||action==='source')void clickDoc(action);
  else if(action==='workspace'){host.querySelector<HTMLElement>('.ws-current')!.click();await settle();clickText('Two');}
  else if(action==='route')void router.push('/other');else clickText(action);
  await settle();expect(mocks.navigation).toHaveBeenCalled();expect(host.querySelector('[data-project]')).toBe(pane);expect(store.workspaceId).toBe('w1');
  barrier.resolve(false);await settle();expect(host.querySelector('[data-project]')).toBe(pane);expect(router.currentRoute.value.path).toBe('/notes');expect(store.workspaceId).toBe('w1');expect(host.querySelector('[data-panel],[data-new],[data-import],[data-settings]')).toBeNull();
 });
 it('uses the project deletion barrier instead of a missing markdown editor',async()=>{
  const {store}=await mountPage();store.requestDelete(docs[0] as any);await settle();host.querySelector<HTMLElement>('[data-delete-confirm]')!.click();await settle();expect(mocks.deletion).toHaveBeenCalledOnce();
 });
 it('uses authoritative project roots/files including markdown and images, ordinary notes retain DocEditor',async()=>{
  await mountPage();expect(host.querySelector('[data-project="root"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
  await clickDoc('source');expect(host.querySelector('[data-file="source"]')).not.toBeNull();expect(host.querySelector('[data-editor]')).toBeNull();
  await clickDoc('image');expect(host.querySelector('[data-file="image"]')).not.toBeNull();
  await clickDoc('ordinary');expect(host.querySelector('[data-editor="ordinary"]')).not.toBeNull();expect(mocks.catalog).toHaveBeenCalledWith('w1');
 });
});
