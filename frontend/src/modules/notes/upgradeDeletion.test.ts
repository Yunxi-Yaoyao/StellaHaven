import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {useNotesPreferencesStore} from '../../stores/notesPreferences';
import {auth} from '../home/auth';
const m=vi.hoisted(()=>({del:vi.fn(),purge:vi.fn(),empty:vi.fn(),document:vi.fn(),preview:vi.fn(),get:vi.fn(),patch:vi.fn(),done:vi.fn(),list:vi.fn(),trash:vi.fn()}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),deleteDoc:m.del,permanentDeleteDoc:m.purge,emptyTrash:m.empty,getDoc:m.document,previewDelete:m.preview,getNotesPreferences:m.get,patchNotesPreferences:m.patch,listDocs:m.list,listTrash:m.trash}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1}),refreshAccess:vi.fn(async()=>false)}));
let app:App|undefined;
beforeEach(async()=>{auth.suspended=false;auth.sessionClosing=false;auth.me={id:'alice'} as any;setActivePinia(createPinia());vi.resetAllMocks();const {ApiError}=await import('../../api/client');m.document.mockRejectedValue(new ApiError(404,null));m.preview.mockImplementation(async(req:any)=>({...req,scope_token:"scope-fixture",target_ids:["one"],descendant_count:0}));m.get.mockResolvedValue({revision:0,delete_action:'trash',ask_before_delete:true});m.list.mockResolvedValue([]);m.trash.mockImplementation(async()=>m.del.mock.calls.length&&!m.purge.mock.calls.length?[doc]:[]);});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';});
const doc={id:'one',title:'知识库',workspace_id:'ws',parent_id:null} as any;
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();await nextTick();};
async function mount(children:any[]=[],kind='note'){const modules=import.meta.glob('./DeleteNoteDialog.vue');expect(modules['./DeleteNoteDialog.vue'],'unified delete dialog exists').toBeTypeOf('function');const component=(await modules['./DeleteNoteDialog.vue']!() as any).default;const root=document.createElement('div');document.body.append(root);const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.userId='alice';store.workspaceId='ws';store.allDocs=[doc,...children];store.trash=[doc,...children];m.preview.mockImplementation(async(req:any)=>({...req,scope_token:'scope-fixture',target_ids:kind==='empty'?[doc,...children].map(d=>d.id):req.cascade?[doc,...children].map(d=>d.id):['one'],descendant_count:children.length}));if(kind==='empty')(store as any).requestEmptyTrash();else if(kind==='trash')(store as any).requestPurge(doc);else store.requestDelete(doc);app=createApp(component,{onDeleted:m.done}).use(pinia);app.mount(root);await flush();return store;}
it('explicit permanent choice and remember saves only after deletion, then readback',async()=>{await mount();const radio=document.querySelector<HTMLInputElement>('input[value=permanent]');expect(radio,'permanent choice').not.toBeNull();radio!.click();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认永久删除');await flush();expect(m.purge).toHaveBeenCalledWith('one',false,'scope-fixture');expect(m.del).not.toHaveBeenCalled();expect(m.patch).toHaveBeenCalledWith({expected_revision:0,delete_action:'permanent',ask_before_delete:false});});
it('remembered permanent without asking executes directly, but descendants still require an explicit scope',async()=>{
 m.get.mockResolvedValue({revision:2,delete_action:'permanent',ask_before_delete:false});
 const s=await mount();await flush();expect(m.purge).toHaveBeenCalledWith('one',false,'scope-fixture');expect(s.pendingDelete).toBeNull();app!.unmount();app=undefined;m.purge.mockClear();
 await mount([{...doc,id:'two',parent_id:'one'},{...doc,id:'three',parent_id:'two'}]);expect(m.purge).not.toHaveBeenCalled();expect(document.body.textContent).toContain('2 篇子页面');
 const confirm=[...document.querySelectorAll('button')].find(e=>e.textContent==='确认永久删除')!;expect(confirm.disabled).toBe(true);
 document.querySelector<HTMLInputElement>('input[value=keep]')!.click();await flush();confirm.click();await flush();expect(m.purge).toHaveBeenCalledWith('one',false,'scope-fixture');
});
it('trash and empty use explicit permanent range, with no preference write',async()=>{
 await mount([], 'trash');expect(document.body.textContent).toContain('回收站');click('确认永久删除');await flush();expect(m.purge).toHaveBeenCalledWith('one',false,'scope-fixture');app!.unmount();app=undefined;
 await mount([{...doc,id:'two'}], 'empty');expect(document.body.textContent).toContain('2 篇');click('确认永久清空');await flush();expect(m.empty).toHaveBeenCalledWith('ws','scope-fixture');expect(m.patch).not.toHaveBeenCalled();
});
it('409 attachment conflict is readable and keeps choices without saving preferences',async()=>{
 const {ApiError}=await import('../../api/client');m.purge.mockRejectedValue(new ApiError(409,{code:'attachment_reference_conflict'}));
 await mount();document.querySelector<HTMLInputElement>('input[value=permanent]')!.click();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认永久删除');await flush();expect(document.querySelector('[role=alert]')?.textContent).toContain('引用');expect(document.querySelector<HTMLInputElement>('input[value=permanent]')!.checked).toBe(true);expect(m.patch).not.toHaveBeenCalled();
});
it('preference readback failure retries only GET and never deletes twice',async()=>{
 m.get.mockResolvedValueOnce({revision:0,delete_action:'trash',ask_before_delete:true}).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({revision:1,delete_action:'trash',ask_before_delete:false});
 const s=await mount();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认移入回收站');await flush();expect(s.pendingDelete).toBeNull();expect(m.done).toHaveBeenCalledTimes(1);expect(m.del).toHaveBeenCalledTimes(1);const preferences=useNotesPreferencesStore();expect(preferences.status).toBe('verify');expect(await preferences.load()).toBe(true);expect(preferences.saved?.ask_before_delete).toBe(false);expect(m.del).toHaveBeenCalledTimes(1);expect(m.patch).toHaveBeenCalledTimes(1);
});
it('unmounted modal fences late deletion and does not remember or reopen',async()=>{
 let finish!:()=>void;m.del.mockReturnValue(new Promise<void>(r=>finish=r));await mount();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认移入回收站');app!.unmount();app=undefined;finish();await flush();expect(m.patch).not.toHaveBeenCalled();expect(document.querySelector('[role=dialog]')).toBeNull();
});
it('acknowledged deletion with stale readback stays open and retries reads, not deletion',async()=>{m.list.mockResolvedValueOnce([doc]).mockResolvedValue([]);const s=await mount();click('确认移入回收站');await flush();expect(s.pendingDelete).not.toBeNull();expect(document.body.textContent).toContain('列表');click('重试刷新列表');await flush();expect(m.del).toHaveBeenCalledTimes(1);expect(s.pendingDelete).toBeNull();});
it.each(['suspended','sessionClosing'] as const)('%s hides modal synchronously and fences held deletion',async(field)=>{let finish!:()=>void;m.del.mockReturnValue(new Promise<void>(r=>finish=r));const s=await mount();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认移入回收站');auth[field]=true;expect(s.pendingDelete).toBeNull();await flush();expect(document.querySelector('[role=dialog]')).toBeNull();finish();await flush();expect(m.patch).not.toHaveBeenCalled();expect(m.list).not.toHaveBeenCalled();});
it('a preference failure cannot hold the successfully deleted editor open',async()=>{m.patch.mockRejectedValue(new Error('offline'));const s=await mount();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认移入回收站');await flush();expect(s.pendingDelete).toBeNull();expect(useNotesPreferencesStore().status).toBe('verify');expect(m.done).toHaveBeenCalledTimes(1);expect(m.del).toHaveBeenCalledTimes(1);});
function click(text:string){const b=[...document.querySelectorAll('button')].find(e=>e.textContent?.trim()===text);expect(b, text).toBeTruthy();b!.click();}
it('leaf deletion asks, cancel sends neither deletion nor preference PATCH',async()=>{const s=await mount();expect(document.querySelector('[role=dialog]')).not.toBeNull();expect(m.del).not.toHaveBeenCalled();click('取消');await flush();expect(s.pendingDelete).toBeNull();expect(m.patch).not.toHaveBeenCalled();});
