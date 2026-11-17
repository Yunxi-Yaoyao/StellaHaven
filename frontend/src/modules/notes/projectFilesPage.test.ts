import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {createApp,defineComponent,h,nextTick,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {createMemoryHistory,createRouter,RouterView} from 'vue-router';
const mocks=vi.hoisted(()=>({catalog:vi.fn(),source:vi.fn(),entry:vi.fn()}));
// Synthetic project workspaces contain no detached source identities.
vi.mock('../../api/detachedSources',()=>({listDetachedSources:vi.fn(async()=>[])}));
vi.mock('../../api/webProjects',()=>({
 listProjects:mocks.catalog,
 listProjectIdentities:async()=> (await mocks.catalog()).map((p:any)=>({id:p.id,workspace_id:p.workspace_id,members:[p.id,...p.files.map((f:any)=>f.id),...(p.directories??[]).map((d:any)=>d.id)]})),
 getProject:async(id:string)=>(await mocks.catalog()).find((p:any)=>p.id===id),
 getProjectSource:mocks.source,
}));
vi.mock('../../api/projectFiles',()=>({setProjectEntry:mocks.entry}));
vi.mock('../../api/notes',()=>({getDoc:vi.fn(async(id:string)=>({id,workspace_id:'ws'})),listTemplates:vi.fn(async()=>({root_id:'templates'}))}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
vi.mock('../../stores/notes',async()=>({useNotesStore:(await import('pinia')).defineStore('project-files-page',{
 state:()=>({userId:'alice',workspaceId:'ws',docs:[] as any[],allDocs:[] as any[],workspaces:[],pendingDelete:null,hideProtectedId:null,templateRootId:null,draggingId:null}),
 actions:{bootstrap:vi.fn(async()=>{}),refreshList:vi.fn(async()=>{}),refreshRecent:vi.fn(async()=>{}),resetSession:vi.fn(),refreshTrash:vi.fn()}
})}));
vi.mock('../../stores/notesPreferences',async()=>({useNotesPreferencesStore:(await import('pinia')).defineStore('project-files-page-prefs',{state:()=>({draft:{},owner:''}),actions:{bindOwner(id:string){this.owner=id;},load:async()=>true}})}));
vi.mock('./DocList.vue',()=>({default:defineComponent({setup:()=>()=>h('div')})}));
vi.mock('./DocEditor.vue',()=>({default:defineComponent({setup:()=>()=>h('article',{'data-ordinary-editor':''})})}));
vi.mock('./WebProjectPane.vue',()=>({default:defineComponent({props:['fileId'],setup:p=>()=>h('article',{'data-project-source':p.fileId})})}));
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
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();vi.stubGlobal('WebSocket',class{static OPEN=1;readyState=1;close(){}});mocks.catalog.mockResolvedValue([project]);});
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();});
it('real NotesPage deep-links project directory without mounting Markdown; directory child navigates to source',async()=>{
 const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.docs=store.allDocs=['root','folder','source'].map(id=>({id,title:id,parent_id:null})) as any;
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/notes',component:NotesPage}]});await router.push('/notes?doc=folder');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(RouterView)}).use(pinia).use(router);app.mount(host);await settle();
 expect(host.querySelector('.project-files')).not.toBeNull();expect(host.querySelector('[data-ordinary-editor]')).toBeNull();expect(host.textContent).toContain('assets/index.html');expect(mocks.source).not.toHaveBeenCalled();
 host.querySelector<HTMLButtonElement>('[data-project-file="source"]')!.click();await settle();expect(host.querySelector('[data-project-source="source"]')).not.toBeNull();expect(router.currentRoute.value.query.doc).toBe('source');expect(host.querySelector('[data-ordinary-editor]')).toBeNull();
});
