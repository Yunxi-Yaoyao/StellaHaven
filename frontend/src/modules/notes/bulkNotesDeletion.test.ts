import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
import DocList from './DocList.vue';
import DeleteNoteDialog from './DeleteNoteDialog.vue';
const m=vi.hoisted(()=>({preview:vi.fn(),del:vi.fn(),purge:vi.fn(),get:vi.fn(),list:vi.fn(),trash:vi.fn(),document:vi.fn(),before:vi.fn()}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),previewDelete:m.preview,deleteDoc:m.del,permanentDeleteDoc:m.purge,getNotesPreferences:m.get,listDocs:m.list,listTrash:m.trash,getDoc:m.document}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:vi.fn(async()=>false)}));
const doc=(id:string,parent_id:string|null=null)=>({id,title:id,parent_id,workspace_id:'w',updated_at:'2026',created_at:'2026'} as any);
let apps:App[]=[];
const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();await nextTick();};
function click(text:string){const el=[...document.querySelectorAll('button')].find(el=>el.textContent?.trim()===text);expect(el,text).toBeTruthy();el!.click();}
async function mountList(){const p=createPinia();setActivePinia(p);const s=useNotesStore();s.userId='alice';s.workspaceId='w';s.workspaces=[{id:'w',name:'工作',user_id:'alice'}];s.docs=s.allDocs=[doc('one'),doc('two'),doc('protected')];s.templateRootId='protected';const root=document.createElement('div');document.body.append(root);const app=createApp(DocList,{currentId:null,trashOpen:false,attachOpen:false,graphOpen:false}).use(p);apps.push(app);app.mount(root);await flush();return {s,p};}
async function mountDialog(s:ReturnType<typeof useNotesStore>,p:ReturnType<typeof createPinia>){s.requestDeleteBatch([doc('one'),doc('two')]);const root=document.createElement('div');document.body.append(root);const app=createApp(DeleteNoteDialog,{beforeTrash:m.before}).use(p);apps.push(app);app.mount(root);await flush();}
beforeEach(async()=>{vi.resetAllMocks();localStorage.clear();Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});m.get.mockResolvedValue({revision:0,delete_action:'trash',ask_before_delete:true});m.preview.mockImplementation(async(r:any)=>({...r,scope_token:'scope-'+r.doc_id,target_ids:[r.doc_id],descendant_count:0}));m.list.mockResolvedValue([doc('protected')]);m.trash.mockResolvedValue([doc('one'),doc('two')]);m.before.mockResolvedValue(true);const {ApiError}=await import('../../api/client');m.document.mockRejectedValue(new ApiError(404,null));});
afterEach(()=>{for(const a of apps)a.unmount();apps=[];document.body.innerHTML='';});
it('directory selects notes (not workspaces), excludes protected root and freezes chosen IDs',async()=>{const {s}=await mountList();click('工作▾');await flush();expect(document.body.textContent).not.toContain('批量删除工作区');click('工作▾');click('批量删除笔记');await flush();const inputs=[...document.querySelectorAll<HTMLInputElement>('[aria-label^="选择笔记"]')];expect(inputs).toHaveLength(3);expect(document.querySelector<HTMLInputElement>('[aria-label="选择笔记：protected"]')!.disabled).toBe(true);document.querySelector<HTMLElement>('[aria-label="选择笔记：one"]')!.click();document.querySelector<HTMLElement>('[aria-label="选择笔记：two"]')!.click();await flush();click('删除所选（2）');await flush();expect(s.pendingDelete?.kind).toBe('batch');expect(s.pendingDelete?.docs?.map(d=>d.id)).toEqual(['one','two']);});
it('one explicit batch confirmation reuses trash lifecycle and re-previews the second token',async()=>{const {s,p}=await mountList();await mountDialog(s,p);expect(m.del).not.toHaveBeenCalled();click('确认移入回收站');click('确认移入回收站');await flush();expect(m.before).toHaveBeenCalledWith(['one','two']);expect(m.del.mock.calls).toEqual([['one',false,'scope-one',expect.any(Function)],['two',false,'scope-two',expect.any(Function)]]);expect(m.purge).not.toHaveBeenCalled();expect(m.preview.mock.calls.map(c=>c[0].doc_id)).toEqual(['one','two','two']);expect(s.pendingDelete).toBeNull();});
it.each(['session','workspace-return','unmount'])('held save barrier admits no batch writes after %s',async(boundary)=>{let release!:(v:boolean)=>void;m.before.mockReturnValue(new Promise(r=>release=r));const {s,p}=await mountList();await mountDialog(s,p);click('确认移入回收站');await flush();if(boundary==='session')auth.requestEpoch++;else if(boundary==='workspace-return'){s.workspaceId='other';s.workspaceId='w';}else apps.at(-1)!.unmount();release(true);await flush();expect(m.del).not.toHaveBeenCalled();});
it('unmount after an admitted first DELETE stops remaining selected notes',async()=>{
 let release!:()=>void;m.del.mockImplementationOnce(()=>new Promise<void>(r=>release=r));
 const {s,p}=await mountList();await mountDialog(s,p);click('确认移入回收站');await flush();expect(m.del).toHaveBeenCalledTimes(1);
 apps.at(-1)!.unmount();release();await flush();expect(m.del).toHaveBeenCalledTimes(1);expect(m.list).not.toHaveBeenCalled();
});
it('a newly expanded second cascade scope stops before deleting unconfirmed IDs',async()=>{
 m.preview.mockImplementation(async(r:any)=>({...r,scope_token:'scope-'+r.doc_id,target_ids:r.cascade?[r.doc_id,r.doc_id+'-child']:[r.doc_id],descendant_count:1}));
 const {s,p}=await mountList();await mountDialog(s,p);
 document.querySelector<HTMLInputElement>('input[value=cascade]')!.click();await flush();
 m.preview.mockImplementationOnce(async(r:any)=>({...r,scope_token:'changed',target_ids:[r.doc_id,r.doc_id+'-child','new-child'],descendant_count:2}));
 click('确认移入回收站');await flush();expect(m.del).toHaveBeenCalledTimes(1);expect(document.body.textContent).toContain('批量删除已停止');
 expect(document.querySelector('[role=dialog]')!.textContent).toContain('two：尚未执行');
});
it('partial batch reconciliation never remembers a preference as if the whole selection completed',async()=>{
 const {s,p}=await mountList();await mountDialog(s,p);
 const preferences=(await import('../../stores/notesPreferences')).useNotesPreferencesStore();const save=vi.spyOn(preferences,'save');
 document.querySelector<HTMLInputElement>('[data-remember]')!.click();
 m.preview.mockRejectedValueOnce(new Error('second scope offline'));
 m.trash.mockResolvedValue([doc('one')]);m.list.mockResolvedValue([doc('two'),doc('protected')]);
 click('确认移入回收站');await flush();expect(m.del).toHaveBeenCalledTimes(1);
 click('刷新列表核对');await flush();expect(save).not.toHaveBeenCalled();expect(m.del).toHaveBeenCalledTimes(1);
});

it('a lost second ACK never replays the first acknowledged delete',async()=>{m.del.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('lost ack'));const {s,p}=await mountList();await mountDialog(s,p);click('确认移入回收站');await flush();expect(document.body.textContent).toContain('结果尚未确认');expect(m.del).toHaveBeenCalledTimes(2);click('刷新列表核对');await flush();expect(m.del).toHaveBeenCalledTimes(2);});
