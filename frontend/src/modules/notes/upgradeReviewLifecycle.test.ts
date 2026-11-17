import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
const m=vi.hoisted(()=>({del:vi.fn(),purge:vi.fn(),empty:vi.fn(),document:vi.fn(),preview:vi.fn(),get:vi.fn(),patch:vi.fn(),done:vi.fn(),list:vi.fn(),trash:vi.fn()}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),deleteDoc:m.del,permanentDeleteDoc:m.purge,emptyTrash:m.empty,getDoc:m.document,previewDelete:m.preview,getNotesPreferences:m.get,patchNotesPreferences:m.patch,listDocs:m.list,listTrash:m.trash}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1}),refreshAccess:vi.fn(async()=>false)}));
let app:App|undefined;
const doc={id:'one',title:'Review target',workspace_id:'ws',parent_id:null} as any;
const flush=async()=>{for(let i=0;i<25;i++)await Promise.resolve();await nextTick();};
beforeEach(async()=>{auth.suspended=false;auth.sessionClosing=false;auth.me={id:'alice'} as any;setActivePinia(createPinia());vi.resetAllMocks();const {ApiError}=await import('../../api/client');m.document.mockRejectedValue(new ApiError(404,null));m.preview.mockImplementation(async(req:any)=>({...req,scope_token:"scope-fixture",target_ids:["one"],descendant_count:0}));m.get.mockResolvedValue({revision:0,delete_action:'trash',ask_before_delete:true});m.list.mockResolvedValue([]);m.trash.mockResolvedValue([]);});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';});
async function mount(kind='note',trashed:any[]=[]){const {default:component}=await import('./DeleteNoteDialog.vue');const root=document.createElement('div');document.body.append(root);const pinia=createPinia();setActivePinia(pinia);const s=useNotesStore();s.userId='alice';s.workspaceId='ws';s.allDocs=kind==='note'?[doc]:[];s.trash=kind==='empty'?[doc]:trashed;if(kind==='empty')s.requestEmptyTrash();else s.requestDelete(doc);app=createApp(component,{onDeleted:m.done}).use(pinia);app.mount(root);await flush();return s;}
function click(text:string){const b=[...document.querySelectorAll('button')].find(e=>e.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();}

it.each([
 ['attachment_in_use','引用'],['attachment_reference_check_incomplete','引用检查未完成'],['reference_check_incomplete','引用检查未完成'],['document_has_children','子页'],['document_tree_invalid','树结构异常'],['document_tree_check_incomplete','树检查未完成'],['tree_invalid','树结构异常'],['tree_check_incomplete','树检查未完成'],['delete_scope_changed','范围已变化'],
])('conflict %s has a specific recovery message',async(code,message)=>{
 const {ApiError}=await import('../../api/client');m.empty.mockRejectedValue(new ApiError(409,{code}));await mount('empty');click('确认永久清空');await flush();expect(document.body.textContent).toContain(message);expect(m.empty).toHaveBeenCalledTimes(1);expect(m.patch).not.toHaveBeenCalled();expect(document.body.textContent).toContain('重新读取范围');
});
it.each([{target_ids:null}, {descendant_count:undefined}, {descendant_count:-1}, {target_ids:[]}, {target_ids:['one','one']}, {workspace_id:'other'}, {mode:'trash'}, {cascade:true}, {scope_token:''}])('partial/mismatched preview is never leaf authority: %j',async(change)=>{
 m.get.mockResolvedValue({revision:2,delete_action:'permanent',ask_before_delete:false});
 m.preview.mockImplementation(async(req:any)=>({...req,scope_token:'partial',target_ids:['one'],descendant_count:0,...change}));
 await mount();expect(m.purge).not.toHaveBeenCalled();expect(document.body.textContent).toContain('范围读取失败');
});
it('held exact target read cannot publish after a request epoch change',async()=>{
 const {ApiError}=await import('../../api/client');let reject!:(e:any)=>void;m.document.mockReturnValue(new Promise((_resolve,r)=>reject=r));m.trash.mockResolvedValue([doc]);
 const s=await mount();click('确认移入回收站');await flush();auth.requestEpoch++;reject(new ApiError(404,null));await flush();expect(m.done).not.toHaveBeenCalled();expect(s.allDocs).toEqual([doc]);expect(m.patch).not.toHaveBeenCalled();
});
it('a held old list cannot resurrect a reconciled deleted target',async()=>{
 let release!:(v:any)=>void;m.list.mockImplementationOnce(()=>new Promise(r=>release=r)).mockResolvedValue([]);m.trash.mockResolvedValue([doc]);
 const s=await mount();const old=s.refreshList();click('确认移入回收站');await flush();expect(s.pendingDelete).toBeNull();release([doc]);await old;await flush();expect(s.allDocs).toEqual([]);
});
it('list absence alone is not proof of permanent deletion when exact target still exists',async()=>{
 const {ApiError}=await import('../../api/client');m.purge.mockRejectedValue(new ApiError(500,null));m.document.mockResolvedValue(doc);
 const s=await mount();document.querySelector<HTMLInputElement>('input[value=permanent]')!.click();await flush();click('确认永久删除');await flush();click('刷新列表核对');await flush();
 expect(s.pendingDelete).not.toBeNull();expect(m.done).not.toHaveBeenCalled();expect(m.purge).toHaveBeenCalledTimes(1);
});
it('preview failure cannot apply a remembered leaf default' ,async()=>{
 m.get.mockResolvedValue({revision:1,delete_action:'permanent',ask_before_delete:false});m.preview.mockRejectedValue(new Error('offline'));
 await mount();expect(m.purge).not.toHaveBeenCalled();expect(document.body.textContent).toContain('范围');
});
it('frozen token is sent and completed empty targets ignore new trash',async()=>{
 const {ApiError}=await import('../../api/client');m.empty.mockRejectedValue(new ApiError(500,null));m.trash.mockResolvedValue([{...doc,id:'new-trash'}]);
 const s=await mount('empty');click('确认永久清空');await flush();expect(m.empty).toHaveBeenCalledWith('ws','scope-fixture');click('刷新列表核对');await flush();
 expect(s.pendingDelete).toBeNull();expect(m.done).toHaveBeenCalledTimes(1);expect(m.empty).toHaveBeenCalledTimes(1);
});
it('late preview cannot overwrite a newer mode selection',async()=>{
 await mount();let release!:(v:any)=>void;m.preview.mockImplementationOnce(()=>new Promise(r=>release=r));
 document.querySelector<HTMLInputElement>('input[value=permanent]')!.click();await flush();
 document.querySelector<HTMLInputElement>('input[value=trash]')!.click();await flush();
 release({workspace_id:'ws',doc_id:'one',mode:'permanent',cascade:false,scope_token:'old',target_ids:['one'],descendant_count:0});await flush();
 click('确认移入回收站');await flush();expect(m.del).toHaveBeenCalledWith('one',false,'scope-fixture');expect(m.purge).not.toHaveBeenCalled();
});
it('5xx after uncertain empty commit must disable destructive replay',async()=>{
 const {ApiError}=await import('../../api/client');m.empty.mockRejectedValue(new ApiError(500,null));
 await mount('empty');click('确认永久清空');await flush();
 expect(document.body.textContent).toContain('结果尚未确认');
 expect([...document.querySelectorAll('button')].map(e=>e.textContent)).not.toContain('确认永久清空');
});

it('uncertain deletion readback must not close as deleted when target is still live',async()=>{
 m.del.mockRejectedValue(new TypeError('Failed to fetch'));m.list.mockResolvedValue([doc]);
 const s=await mount();click('确认移入回收站');await flush();click('刷新列表核对');await flush();
 expect(s.pendingDelete,'must preserve unresolved choice while target still exists').not.toBeNull();
 expect(m.done).not.toHaveBeenCalled();
});

it('unknown trash descendants must be loaded before applying no-confirm permanent',async()=>{
 m.get.mockResolvedValue({revision:3,delete_action:'permanent',ask_before_delete:false});
 m.trash.mockResolvedValue([{...doc,id:'child',parent_id:doc.id}]);
 m.preview.mockImplementation(async(req:any)=>({...req,scope_token:'cold-scope',target_ids:req.cascade?['one','child']:['one'],descendant_count:1}));
 await mount('note');
 expect(m.purge,'a cold trash inventory is not proof of no children').not.toHaveBeenCalled();
 expect(document.body.textContent).toContain('子页面');
});

it('document_has_children must not be presented as attachment conflict',async()=>{
 const {ApiError}=await import('../../api/client');m.empty.mockRejectedValue(new ApiError(409,{code:'document_has_children',message:'删除集合外仍有子页，请明确选择级联或上移'}));
 await mount('empty');click('确认永久清空');await flush();
 expect(document.body.textContent).toContain('子页');
 expect(document.body.textContent).not.toContain('请先处理引用');
});

it('confirmed permanent cleanup may not bypass keepalive/session fences',async()=>{
 let release!:()=>void;m.purge.mockImplementation(()=>new Promise<void>(r=>release=r));
 await mount();document.querySelector<HTMLInputElement>('input[value=permanent]')!.click();document.querySelector<HTMLInputElement>('[data-remember]')!.click();await flush();click('确认永久删除');
 auth.requestEpoch++;await flush();release();await flush();
 expect(m.patch).not.toHaveBeenCalled();expect(m.list).not.toHaveBeenCalled();expect(document.querySelector('[role=dialog]')).toBeNull();
});
