import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,nextTick,h,KeepAlive,ref,type App} from 'vue';
import {createPinia,setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
import DocList from './DocList.vue';
const m=vi.hoisted(()=>({del:vi.fn(),list:vi.fn(),trash:vi.fn(),workspaces:vi.fn(),recent:vi.fn(),barrier:vi.fn()}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),deleteWorkspace:m.del,listDocs:m.list,listTrash:m.trash,listWorkspaces:m.workspaces,listRecent:m.recent}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:vi.fn(async()=>false)}));
const a={id:'a',name:'研究笔记',user_id:'alice'},b={id:'b',name:'旧资料',user_id:'alice'};
const doc=(id:string,workspace_id='a')=>({id,title:id,workspace_id,parent_id:null,created_at:'2026',updated_at:'2026'} as any);
let app:App|undefined;
let visible=ref(true);
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();await nextTick();};
function click(text:string){const el=[...document.querySelectorAll('button,[role=button],.ws-opt')].find(e=>e.textContent?.trim()===text);expect(el,text).toBeTruthy();(el as HTMLElement).click();}
async function mount(keepalive=false){const pinia=createPinia();setActivePinia(pinia);const s=useNotesStore();s.userId='alice';s.workspaceId='a';s.workspaces=[a,b];s.docs=[doc('filtered')];s.allDocs=[doc('cached')];const root=document.createElement('div');document.body.append(root);const props={currentId:null,trashOpen:false,attachOpen:false,graphOpen:false,beforeWorkspaceDelete:m.barrier};visible=ref(true);app=createApp({render:()=>keepalive?h(KeepAlive,{},()=>visible.value?h(DocList,props):null):h(DocList,props)}).use(pinia);app.mount(root);await flush();return s;}
beforeEach(()=>{vi.resetAllMocks();localStorage.clear();auth.me={id:'alice'} as any;auth.suspended=false;auth.sessionClosing=false;auth.requestEpoch=1;auth.sessionGeneration=1;m.barrier.mockResolvedValue(true);m.list.mockImplementation(async(id:string)=>id==='a'?[doc('one'),doc('two')]:[doc('other','b')]);m.trash.mockImplementation(async(id:string)=>id==='a'?[doc('trash')]:[]);m.workspaces.mockResolvedValue([b]);m.recent.mockResolvedValue([]);});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';});
it('existing single deletion previews full active and trash counts, then explicitly force-deletes nonempty workspace',async()=>{
 const s=await mount();click('研究笔记▾');await flush();click('删除工作区');await flush();
 const modal=document.querySelector('[role=dialog]');expect(modal,'workspace deletion confirmation').not.toBeNull();
 expect(modal!.textContent).toContain('正常 2 篇');expect(modal!.textContent).toContain('回收站 1 篇');expect(modal!.textContent).toContain('共 3 篇');expect(m.del).not.toHaveBeenCalled();expect(s.workspaceId).toBe('a');
 click('确认永久删除');await flush();expect(m.barrier).toHaveBeenCalledTimes(1);expect(m.del).toHaveBeenCalledExactlyOnceWith('a',true,expect.any(Function));expect(s.workspaceId).toBe('b');
});
it('workspace menu keeps single deletion and no longer exposes mistaken workspace bulk deletion',async()=>{
 const s=await mount();click('研究笔记▾');await flush();
 expect(document.querySelectorAll('.ws-menu input[type=checkbox]')).toHaveLength(0);
 expect(document.querySelector('.ws-menu')!.textContent).not.toContain('批量删除工作区');
 expect(s.workspaceId).toBe('a');click('删除工作区');await flush();
 click('确认永久删除');click('确认永久删除');await flush();
 expect(m.del).toHaveBeenCalledExactlyOnceWith('a',true,expect.any(Function));expect(m.barrier).toHaveBeenCalledTimes(1);
});
async function openSingle(){const s=await mount();click('研究笔记▾');await flush();click('删除工作区');await flush();return s;}
it('cancel sends neither delete nor lifecycle barrier and returns focus to switcher',async()=>{
 await openSingle();click('取消');await flush();expect(m.del).not.toHaveBeenCalled();expect(m.barrier).not.toHaveBeenCalled();expect(document.activeElement?.className).toBe('ws-current');
});
it.each(['epoch','generation','suspended','sessionClosing','workspace','return'])(
 'held save barrier cannot admit deletion after %s changes',async(boundary)=>{
 let release!:(v:boolean)=>void;m.barrier.mockImplementationOnce(()=>new Promise(r=>release=r));
 const s=await openSingle();click('确认永久删除');await flush();
 if(boundary==='epoch')auth.requestEpoch++;else if(boundary==='generation')auth.sessionGeneration++;
 else if(boundary==='workspace')s.workspaceId='b';else if(boundary==='return'){s.workspaceId='b';s.workspaceId='a';}
 else auth[boundary as 'suspended'|'sessionClosing']=true;
 release(true);await flush();expect(m.del).not.toHaveBeenCalled();expect(document.querySelector('[role=dialog]')).toBeNull();
});
it('preview failure stays open, disables delete and retries reads only',async()=>{
 m.trash.mockRejectedValueOnce(new Error('offline'));await openSingle();expect(document.querySelector('[role=alert]')?.textContent).toContain('读取失败');
 click('确认永久删除');await flush();expect(m.del).not.toHaveBeenCalled();click('重新读取数量');await flush();expect(document.querySelector('[role=alert]')).toBeNull();expect(m.del).not.toHaveBeenCalled();
});
it('mismatched workspace inventory is not count authority',async()=>{
 m.list.mockResolvedValue([doc('foreign','b')]);await openSingle();expect(document.querySelector('[role=alert]')?.textContent).toContain('读取失败');click('确认永久删除');await flush();expect(m.del).not.toHaveBeenCalled();
});
it('partial failure keeps per-workspace results and offers no destructive retry',async()=>{
 const {ApiError}=await import('../../api/client');m.del.mockRejectedValueOnce(new ApiError(409,{code:'attachment_in_use'}));await openSingle();click('确认永久删除');await flush();
 expect(document.body.textContent).toContain('研究笔记：删除失败');expect([...document.querySelectorAll('button')].map(e=>e.textContent)).not.toContain('确认永久删除');
});
it('save denial keeps confirmation and does not call API',async()=>{
 m.barrier.mockResolvedValueOnce(false);await openSingle();click('确认永久删除');await flush();expect(m.del).not.toHaveBeenCalled();expect(document.querySelector('[role=dialog]')).not.toBeNull();
});
it('readback recovery in dialog sends reads only, then reconciles active workspace',async()=>{
 m.workspaces.mockRejectedValueOnce(new Error('offline')).mockResolvedValue([b]);const s=await openSingle();click('确认永久删除');await flush();
 expect(document.body.textContent).toContain('待核对');click('刷新工作区列表');await flush();expect(m.del).toHaveBeenCalledTimes(1);expect(s.workspaceId).toBe('b');expect(document.body.textContent).toContain('研究笔记：已删除');
});
it('result modal hides on auth invalidation even after its own workspace switch',async()=>{
 await openSingle();click('确认永久删除');await flush();expect(document.querySelector('[role=dialog]')).not.toBeNull();auth.suspended=true;await flush();expect(document.querySelector('[role=dialog]')).toBeNull();
});
it('dialog focuses cancel, traps Tab and supports Escape without a deletion',async()=>{
 await openSingle();expect(document.activeElement?.textContent).toBe('取消');
 document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));expect(document.activeElement?.textContent).toBe('确认永久删除');
 document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(document.activeElement?.textContent).toBe('取消');
 document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await flush();expect(document.querySelector('[role=dialog]')).toBeNull();expect(m.del).not.toHaveBeenCalled();
});
it('closing a held preview fences late count results',async()=>{
 let release!:(v:any)=>void;m.list.mockImplementationOnce(()=>new Promise(r=>release=r));await openSingle();click('取消');await flush();release([doc('one')]);await flush();expect(document.querySelector('[role=dialog]')).toBeNull();expect(m.del).not.toHaveBeenCalled();
});
it('keepalive deactivation fences readback after a held workspace DELETE',async()=>{
 let release!:()=>void;m.del.mockImplementationOnce(()=>new Promise<void>(r=>release=r));
 await mount(true);click('研究笔记▾');await flush();click('删除工作区');await flush();
 click('确认永久删除');await flush();
 visible.value=false;await flush();visible.value=true;await flush();release();await flush();
 expect(m.del).toHaveBeenCalledTimes(1);expect(document.querySelector('[role=dialog]')).toBeNull();
});
