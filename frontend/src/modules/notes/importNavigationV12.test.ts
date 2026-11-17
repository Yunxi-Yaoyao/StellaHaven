import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,defineComponent,h,nextTick,KeepAlive,ref,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {createMemoryHistory,createRouter,RouterView} from 'vue-router';

const mocks=vi.hoisted(()=>({catalog:vi.fn(),manifests:new Map<string,any>(),navigation:vi.fn(),deletion:vi.fn(),editorNavigation:vi.fn(),toast:vi.fn(),realPane:false,source:vi.fn(),saveSource:vi.fn(),launch:vi.fn(),saveState:vi.fn(),getDoc:vi.fn()}));
// Synthetic project workspaces contain no detached source identities.
vi.mock('../../api/detachedSources',()=>({listDetachedSources:vi.fn(async()=>[])}));
vi.mock('../../api/webProjects',()=>({listProjects:mocks.catalog,listProjectIdentities:async(workspace:string)=>(await mocks.catalog(workspace)).map((p:any)=>{mocks.manifests.set(p.id,p);return {id:p.id,workspace_id:p.workspace_id,members:[p.id,...p.files.map((f:any)=>f.id),...(p.directories??[]).map((d:any)=>d.id)]};}),getProject:async(id:string)=>{if(id==='broken')throw Error('invalid project path');return mocks.manifests.get(id);},getProjectSource:mocks.source,saveProjectSource:mocks.saveSource,launchProject:mocks.launch,saveProjectState:mocks.saveState,resetProjectState:vi.fn()}));
vi.mock('../../api/notes',()=>({getDoc:mocks.getDoc,listTemplates:vi.fn(async()=>({root_id:'templates'}))}));
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
vi.mock('./ImportDialog.vue',()=>({default:defineComponent({props:['files'],emits:['open'],setup(props,{emit}){return()=>h('aside',{'data-import':''},[h('span',{},props.files.map((f:any)=>f.name).join(',')),h('button',{'data-open-import':'',onClick:()=>emit('open','created-real')},'打开首篇')]);}})}));
vi.mock('./NewChildDialog.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-new':''})})}));
vi.mock('./MoveDialog.vue',()=>({default:defineComponent({setup:()=>()=>h('aside',{'data-move':''})})}));
import NotesPage from './NotesPage.vue';
import {auth} from '../home/auth';
import {useNotesStore} from '../../stores/notes';
const project={id:'root',workspace_id:'w1',title:'Project',entry:'index.html',files:[{id:'source',path:'readme.md',kind:'text',mime:'text/markdown',updated_at:'v1'},{id:'image',path:'cat.png',kind:'binary',mime:'image/png',updated_at:'v1'}]};
const docs=['root','source','image','ordinary'].map(id=>({id,title:id,parent_id:null,updated_at:'v1',created_at:'v1'}));
let app:App|null=null,host:HTMLElement;
const settle=async()=>{for(let i=0;i<12;i++){await Promise.resolve();await nextTick();}};
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

it('opens an imported ID only after the current editor barrier succeeds',async()=>{
 const {router}=await mountPage();await clickDoc('ordinary');clickText('导入');await settle();expect(host.querySelector('[data-import]')).not.toBeNull();
 const oldEditor=host.querySelector('[data-editor=ordinary]');mocks.editorNavigation.mockResolvedValue(false);mocks.editorNavigation.mockClear();
 host.querySelector<HTMLButtonElement>('[data-open-import]')!.click();await settle();expect(mocks.editorNavigation).toHaveBeenCalled();expect(host.querySelector('[data-editor=ordinary]')).toBe(oldEditor);expect(host.querySelector('[data-import]')).not.toBeNull();expect(router.currentRoute.value.query.doc).not.toBe('created-real');
 mocks.editorNavigation.mockResolvedValue(true);host.querySelector<HTMLButtonElement>('[data-open-import]')!.click();await settle();await settle();expect(host.querySelector('[data-editor=created-real]')).not.toBeNull();expect(host.querySelector('[data-import]')).toBeNull();expect(router.currentRoute.value.query.doc).toBe('created-real');
});
it.each(['page.html','page.HTM'])('routes editor HTML drop %s into the same import dialog as picker',async name=>{
 await mountPage();await clickDoc('ordinary');const event=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(event,'dataTransfer',{value:{types:['Files'],files:[{name,size:4,arrayBuffer:async()=>new ArrayBuffer(0)}],items:[]}});host.querySelector('[data-editor=ordinary]')!.dispatchEvent(event);await settle();expect(event.defaultPrevented).toBe(true);expect(host.querySelector('[data-import]')?.textContent).toContain(name);
});
