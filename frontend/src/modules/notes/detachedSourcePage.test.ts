import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {createApp,defineComponent,h,nextTick,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {createMemoryHistory,createRouter,RouterView} from 'vue-router';
const mocks=vi.hoisted(()=>({catalog:vi.fn(),source:vi.fn(),entry:vi.fn(),detached:vi.fn(),read:vi.fn(),save:vi.fn(),move:vi.fn()}));
vi.mock('../../api/webProjects',()=>({
 listProjects:mocks.catalog,
 listProjectIdentities:async()=> (await mocks.catalog()).map((p:any)=>({id:p.id,workspace_id:p.workspace_id,members:[p.id,...p.files.map((f:any)=>f.id),...(p.directories??[]).map((d:any)=>d.id)]})),
 getProject:async(id:string)=>(await mocks.catalog()).find((p:any)=>p.id===id),
 getProjectSource:mocks.source,
}));
vi.mock('../../api/projectFiles',()=>({setProjectEntry:mocks.entry}));
vi.mock('../../api/detachedSources',()=>({listDetachedSources:mocks.detached,getDetachedSource:mocks.read,saveDetachedSource:mocks.save}));
vi.mock('../../api/notes',()=>({getDoc:vi.fn(async(id:string)=>({id,workspace_id:'ws',updated_at:'v2'})),updateDoc:mocks.move,listTemplates:vi.fn(async()=>({root_id:'templates'}))}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
vi.mock('../../stores/notes',async()=>({useNotesStore:(await import('pinia')).defineStore('project-files-page',{
 state:()=>({userId:'alice',workspaceId:'ws',docs:[] as any[],allDocs:[] as any[],workspaces:[],pendingDelete:null,hideProtectedId:null,templateRootId:null,draggingId:null}),
 actions:{bootstrap:vi.fn(async()=>{}),refreshList:vi.fn(async()=>{}),refreshRecent:vi.fn(async()=>{}),resetSession:vi.fn(),refreshTrash:vi.fn()}
})}));
vi.mock('../../stores/notesPreferences',async()=>({useNotesPreferencesStore:(await import('pinia')).defineStore('project-files-page-prefs',{state:()=>({draft:{},owner:''}),actions:{bindOwner(id:string){this.owner=id;},load:async()=>true}})}));
vi.mock('./DocList.vue',()=>({default:defineComponent({setup:()=>()=>h('div',{class:'doc-list'},[h('div',{class:'row','data-import-parent':'outside'},'outside')])})}));
vi.mock('./DocEditor.vue',()=>({default:defineComponent({setup:()=>()=>h('article',{'data-ordinary-editor':''})})}));
vi.mock('./WebProjectPane.vue',()=>({default:defineComponent({props:['fileId'],setup(p,{expose}){expose({prepareNavigation:async()=>true});return()=>h('article',{'data-project-source':p.fileId});}})}));
vi.mock('./DeleteNoteDialog.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./AttachmentsPanel.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./TrashPanel.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./GraphPanel.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./NotesSettings.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./ImportDialog.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./NewChildDialog.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
vi.mock('./MoveDialog.vue',()=>({default:defineComponent({setup:()=>()=>null})}));
import NotesPage from './NotesPage.vue';
import {useNotesStore} from '../../stores/notes';
const project={id:'root',workspace_id:'ws',title:'Project',entry:'assets/index.html',entry_file_id:'source',directories:[{id:'folder',path:'assets',kind:'directory'}],files:[{id:'source',path:'assets/index.html',kind:'text',mime:'text/html',updated_at:'v1',size:7}]};
let app:App,host:HTMLElement;
const settle=async()=>{for(let i=0;i<20;i++){await Promise.resolve();await nextTick();}};
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();vi.stubGlobal('WebSocket',class{static OPEN=1;readyState=1;close(){}});mocks.catalog.mockResolvedValue([]);mocks.detached.mockResolvedValue([{id:'source',workspace_id:'ws',kind:'detached-source',title:'renamed',mime:'text/html',updated_at:'v1'}]);mocks.read.mockResolvedValue({id:'source',workspace_id:'ws',kind:'detached-source',title:'renamed',mime:'text/html',content:'<script>const x=1</script>',updated_at:'v1'});});
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();});
it('list refresh after a committed move switches the selected project source to independent source',async()=>{
 mocks.catalog.mockResolvedValue([project]);mocks.detached.mockResolvedValue([]);
 const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.docs=store.allDocs=[{id:'source',title:'renamed',parent_id:'root'}] as any;
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/notes',component:NotesPage}]});await router.push('/notes?doc=source');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(RouterView)}).use(pinia).use(router);app.mount(host);await settle();
 expect(host.querySelector('[data-project-source]')).not.toBeNull();
 mocks.catalog.mockResolvedValue([]);mocks.detached.mockResolvedValue([{id:'source',workspace_id:'ws',kind:'detached-source',title:'renamed',mime:'text/html',updated_at:'v2'}]);
 store.allDocs=[{id:'source',title:'renamed',parent_id:null}] as any;await settle();
 expect(host.querySelector('.detached-source-pane')).not.toBeNull();expect(host.querySelector('[data-ordinary-editor]')).toBeNull();expect(host.querySelector('[data-project-source]')).toBeNull();
});
it('text drag to an ordinary folder is not blocked by the legacy project tree boundary guard',async()=>{
 mocks.catalog.mockResolvedValue([project]);mocks.detached.mockResolvedValue([]);mocks.move.mockResolvedValue({});const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
 const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.docs=store.allDocs=[{id:'source',title:'renamed',parent_id:'root'}] as any;
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/notes',component:NotesPage}]});await router.push('/notes?doc=source');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(RouterView)}).use(pinia).use(router);app.mount(host);await settle();
 (store as any).draggingId='source';const event=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(event,'dataTransfer',{value:{types:['text/plain'],files:[],items:[],getData:()=> 'source'}});host.querySelector('.row')!.dispatchEvent(event);await settle();
 expect(mocks.move).toHaveBeenCalledWith('source','v2',{parent_id:'outside'});expect(host.querySelector('[data-ordinary-editor]')).toBeNull();confirm.mockRestore();
});
it('NotesPage opens authoritative detached source without ordinary DocEditor',async()=>{
 const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.docs=store.allDocs=[{id:'source',title:'renamed',parent_id:null}] as any;
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/notes',component:NotesPage}]});await router.push('/notes?doc=source');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(RouterView)}).use(pinia).use(router);app.mount(host);await settle();
 expect(host.querySelector('[data-ordinary-editor]')).toBeNull();expect(host.querySelector('.detached-source-pane')).not.toBeNull();expect(host.querySelector('.cm-content')?.textContent).toContain('<script>const x=1</script>');expect(mocks.source).not.toHaveBeenCalled();
});
