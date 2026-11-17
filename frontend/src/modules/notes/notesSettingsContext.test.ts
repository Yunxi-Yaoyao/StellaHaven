import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
const mocks=vi.hoisted(()=>({bootstrap:vi.fn(),docs:vi.fn(),get:vi.fn(),patch:vi.fn()}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),ensureWorkspace:mocks.bootstrap,listDocs:mocks.docs,getNotesPreferences:mocks.get,patchNotesPreferences:mocks.patch}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
import NotesSettings from './NotesSettings.vue';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
let app:App,host:HTMLElement,pinia:ReturnType<typeof createPinia>;
const settle=async()=>{for(let i=0;i<30;i++){await Promise.resolve();await nextTick();}};
beforeEach(()=>{vi.clearAllMocks();pinia=createPinia();setActivePinia(pinia);Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});mocks.bootstrap.mockResolvedValue({userId:'alice',workspaceId:'w1'});mocks.docs.mockResolvedValue([{id:'folder',title:'Current folder',is_folder:true,parent_id:null,workspace_id:'w1'}]);mocks.get.mockResolvedValue({revision:4,delete_action:'trash',ask_before_delete:true,hidden_folders:[]});mocks.patch.mockResolvedValue({revision:5});});
afterEach(()=>{app?.unmount();host?.remove();});
function mount(){host=document.createElement('div');document.body.append(host);app=createApp(NotesSettings,{loadWorkspace:true});app.use(pinia);app.mount(host);}
it('loads current workspace folders independently of NotesPage and saves hidden folders through existing CAS',async()=>{
 const store=useNotesStore();store.allDocs=[{id:'stale',is_folder:true,title:'Stale private folder'}] as any;mount();await settle();expect(mocks.bootstrap).toHaveBeenCalledOnce();expect(mocks.docs).toHaveBeenCalledWith('w1');expect(host.textContent).toContain('Current folder');expect(host.textContent).not.toContain('Stale private folder');
 mocks.get.mockResolvedValue({revision:5,delete_action:'trash',ask_before_delete:true,hidden_folders:['folder']});host.querySelector<HTMLInputElement>('#notes-hidden-folders input')!.click();await settle();expect(mocks.patch).toHaveBeenCalledWith({expected_revision:4,delete_action:'trash',ask_before_delete:true,hidden_folders:['folder']});expect(store.allDocs[0]?.id).toBe('stale');
});
it('never labels a failed directory lookup as an empty workspace and exposes retry',async()=>{mocks.docs.mockRejectedValue(Error('offline'));mount();await settle();expect(host.textContent).toContain('目录读取失败');expect(host.textContent).not.toContain('当前工作区没有目录');mocks.docs.mockResolvedValue([{id:'folder',title:'Current folder',is_folder:true,parent_id:null,workspace_id:'w1'}]);[...host.querySelectorAll('button')].find(b=>b.textContent==='重试目录')!.click();await settle();expect(host.textContent).toContain('Current folder');});
it.each(['owner','session','epoch','suspended'])('discards pending folder context after %s change',async boundary=>{let release!:(v:any)=>void;mocks.docs.mockReturnValueOnce(new Promise(r=>release=r));mount();await settle();if(boundary==='owner')auth.me={id:'bob'} as any;if(boundary==='session')auth.sessionGeneration++;if(boundary==='epoch')auth.requestEpoch++;if(boundary==='suspended')auth.suspended=true;release([{id:'folder',title:'Leaked folder',is_folder:true,parent_id:null,workspace_id:'w1'}]);await settle();expect(host.textContent).not.toContain('Leaked folder');});
