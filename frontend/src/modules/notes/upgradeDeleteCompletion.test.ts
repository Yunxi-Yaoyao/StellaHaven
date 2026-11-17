import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createPinia,setActivePinia,type Pinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {useNotesPreferencesStore} from '../../stores/notesPreferences';
import {auth} from '../home/auth';
import DeleteNoteDialog from './DeleteNoteDialog.vue';
import {toasts} from '../../composables/useToast';
const m=vi.hoisted(()=>({del:vi.fn(),get:vi.fn(),patch:vi.fn(),list:vi.fn(),trash:vi.fn(),preview:vi.fn(),document:vi.fn(),done:vi.fn()}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),deleteDoc:m.del,getNotesPreferences:m.get,patchNotesPreferences:m.patch,listDocs:m.list,listTrash:m.trash,previewDelete:m.preview,getDoc:m.document}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1}),refreshAccess:vi.fn(async()=>false)}));
const doc={id:'one',title:'Leaf',workspace_id:'ws',parent_id:null} as any;
const nextLeaf={...doc,id:'two',title:'Next leaf'};
const initial={revision:0,delete_action:'trash',ask_before_delete:true};
const remembered={revision:1,delete_action:'trash',ask_before_delete:false};
const flush=async()=>{for(let i=0;i<35;i++)await Promise.resolve();await nextTick();};
let app:App|undefined;
let pinia:Pinia;
function deferred<T>(){let resolve!:(value:T)=>void;return {promise:new Promise<T>(r=>resolve=r),resolve};}
beforeEach(async()=>{
 vi.resetAllMocks();toasts.splice(0);Object.assign(auth,{me:{id:'alice'},suspended:false,sessionClosing:false});pinia=createPinia();setActivePinia(pinia);
 m.get.mockResolvedValue(initial);m.patch.mockResolvedValue(remembered);m.list.mockResolvedValue([]);m.trash.mockResolvedValue([doc,nextLeaf]);
 m.preview.mockImplementation(async(req:any)=>({...req,scope_token:'exact-scope',target_ids:[req.doc_id],descendant_count:0}));
 const {ApiError}=await import('../../api/client');m.document.mockRejectedValue(new ApiError(404,null));
});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';});
async function mount(store=useNotesStore(),target=doc){
 store.userId='alice';store.workspaceId='ws';store.allDocs=[target];store.requestDelete(target);
 const host=document.createElement('div');document.body.append(host);app=createApp(DeleteNoteDialog,{onDeleted:m.done}).use(pinia);app.mount(host);await flush();return store;
}
function click(text:string){const button=[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(button,text).toBeTruthy();button!.click();}
function remember(){document.querySelector<HTMLInputElement>('[data-remember]')!.click();}
it('the real settings UI retries a failed remembered preference without replaying the completed deletion',async()=>{
 m.patch.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(remembered);
 const store=await mount();remember();click('确认移入回收站');await flush();expect(store.pendingDelete).toBeNull();
 app!.unmount();app=undefined;
 const {default:Settings}=await import('./NotesSettings.vue');const host=document.createElement('div');document.body.append(host);
 app=createApp(Settings).use(pinia);app.mount(host);await flush();
 expect(document.body.textContent).toContain('已保留选择');expect(m.patch).toHaveBeenCalledTimes(1);
 m.get.mockResolvedValue(remembered);click('重新应用我的选择');await flush();
 expect(document.body.textContent).toContain('已同步');expect(useNotesPreferencesStore().saved?.ask_before_delete).toBe(false);
 expect(m.del).toHaveBeenCalledTimes(1);expect(m.patch).toHaveBeenCalledTimes(2);
});
it.each(['owner','generation','epoch','suspended','closing'] as const)('queued remember GET cannot write across the %s boundary',async(boundary)=>{
 const held=deferred<any>();m.get.mockResolvedValueOnce(initial).mockReturnValueOnce(held.promise);
 await mount();remember();const preferences=useNotesPreferencesStore();const reading=preferences.load();click('确认移入回收站');await flush();
 if(boundary==='owner')auth.me={id:'bob'} as any;
 else if(boundary==='generation')auth.sessionGeneration++;
 else if(boundary==='epoch')auth.requestEpoch++;
 else if(boundary==='suspended')auth.suspended=true;
 else auth.sessionClosing=true;
 held.resolve(initial);await reading;await flush();expect(m.patch).not.toHaveBeenCalled();expect(preferences.saved).toBeNull();expect(toasts).toEqual([]);
});
it('a completed dialog cannot publish a held preference verification into the next owner',async()=>{
 const held=deferred<any>();m.get.mockResolvedValueOnce(initial).mockReturnValueOnce(held.promise);
 const store=await mount();remember();click('确认移入回收站');await flush();expect(store.pendingDelete).toBeNull();
 app!.unmount();app=undefined;auth.me={id:'bob'} as any;held.resolve(remembered);await flush();
 expect(useNotesPreferencesStore().owner).toBe('bob');expect(useNotesPreferencesStore().saved).toBeNull();expect(toasts).toEqual([]);expect(m.del).toHaveBeenCalledTimes(1);
});
it('preference failure leaves deletion finished but reports the independent settings retry',async()=>{
 m.patch.mockRejectedValue(new Error('offline'));
 const store=await mount();remember();click('确认移入回收站');await flush();
 expect(store.pendingDelete).toBeNull();expect(m.done).toHaveBeenCalledTimes(1);expect(useNotesPreferencesStore().status).toBe('verify');
 expect(toasts.map(t=>t.text).join(' ')).toContain('设置 → 笔记');expect(m.del).toHaveBeenCalledTimes(1);
});
it('an acknowledged deletion remembers the choice even if list readback fails, and retry never repeats either write',async()=>{
 m.list.mockRejectedValueOnce(new Error('offline')).mockResolvedValue([]);m.get.mockResolvedValueOnce(initial).mockResolvedValue(remembered);
 const store=await mount();remember();click('确认移入回收站');await flush();
 expect(store.pendingDelete).not.toBeNull();expect(m.del).toHaveBeenCalledTimes(1);
 expect(m.patch,'list refresh must not suppress saving the checked choice after an acknowledged delete').toHaveBeenCalledTimes(1);
 expect(useNotesPreferencesStore().saved?.ask_before_delete).toBe(false);
 click('重试刷新列表');await flush();expect(store.pendingDelete).toBeNull();expect(m.del).toHaveBeenCalledTimes(1);expect(m.patch).toHaveBeenCalledTimes(1);
});
it('a deletion ACK does not claim verified completion while exact readback is held',async()=>{
 const held=deferred<any>();m.list.mockReturnValueOnce(held.promise);
 const store=await mount();click('确认移入回收站');await flush();
 expect(document.querySelector('[role=status]')?.textContent).not.toContain('笔记删除已完成');
 expect(document.body.textContent).toContain('正在核对删除结果');
 expect(store.pendingDelete).not.toBeNull();expect(m.done).not.toHaveBeenCalled();
 held.resolve([]);await flush();expect(store.pendingDelete).toBeNull();expect(m.del).toHaveBeenCalledTimes(1);
});
it('the next leaf joins a pending preference PATCH instead of opening an uninitialized confirmation',async()=>{
 const held=deferred<any>();m.patch.mockReturnValueOnce(held.promise);m.get.mockResolvedValueOnce(initial).mockResolvedValue(remembered);
 const store=await mount();remember();click('确认移入回收站');await flush();expect(store.pendingDelete).toBeNull();
 app!.unmount();app=undefined;await mount(store,nextLeaf);expect(m.del).toHaveBeenCalledTimes(1);
 held.resolve(remembered);await flush();
 expect(m.del,'the next deletion must resume after the remembered write is verified').toHaveBeenCalledTimes(2);
 expect(store.pendingDelete).toBeNull();expect(m.patch).toHaveBeenCalledTimes(1);
});
it('remember intent survives a preference refresh already in flight when deletion finishes',async()=>{
 const held=deferred<any>();m.get.mockResolvedValueOnce(initial).mockReturnValueOnce(held.promise).mockResolvedValue(remembered);
 const store=await mount();remember();const preferences=useNotesPreferencesStore();const refreshing=preferences.load();
 click('确认移入回收站');await flush();expect(store.pendingDelete).toBeNull();
 held.resolve(initial);await refreshing;await flush();
 expect(m.patch,'the checked choice must not be silently dropped because a GET was busy').toHaveBeenCalledWith({expected_revision:0,delete_action:'trash',ask_before_delete:false});
 expect(preferences.saved?.ask_before_delete).toBe(false);
 app!.unmount();app=undefined;await mount(store,nextLeaf);expect(m.del).toHaveBeenCalledTimes(2);expect(store.pendingDelete).toBeNull();
});
it('verified deletion finishes without waiting for preference readback; the next leaf waits for and uses that save',async()=>{
 const held=deferred<any>();m.get.mockResolvedValueOnce(initial).mockReturnValueOnce(held.promise).mockResolvedValue(remembered);
 const store=await mount();remember();click('确认移入回收站');await flush();
 expect(m.patch).toHaveBeenCalledTimes(1);
 expect(store.pendingDelete,'verified deletion must release its action/dialog while only preference GET is pending').toBeNull();
 expect(m.done).toHaveBeenCalledTimes(1);
 app!.unmount();app=undefined;await mount(store,nextLeaf);expect(m.del).toHaveBeenCalledTimes(1);
 held.resolve(remembered);await flush();expect(m.del).toHaveBeenCalledTimes(2);expect(store.pendingDelete).toBeNull();expect(m.patch).toHaveBeenCalledTimes(1);
});
