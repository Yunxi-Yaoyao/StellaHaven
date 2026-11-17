import {it, expect, vi, beforeEach} from 'vitest';
import {createPinia, setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
const m = vi.hoisted(() => ({del:vi.fn(), workspaces:vi.fn(), docs:vi.fn(), trash:vi.fn(), recent:vi.fn(), bootstrap:vi.fn(), create:vi.fn()}));
vi.mock('../../api/notes', async () => ({...await vi.importActual<any>('../../api/notes'), deleteWorkspace:m.del, listWorkspaces:m.workspaces, listDocs:m.docs, listTrash:m.trash, listRecent:m.recent, ensureWorkspace:m.bootstrap,createWorkspace:m.create}));
vi.mock('../home/auth', async () => ({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}), refreshAccess:vi.fn(async()=>false)}));
const ws = (id:string) => ({id,name:`工作区${id}`,user_id:'alice'});
function setup() {const s=useNotesStore();s.userId='alice';s.workspaceId='a';s.workspaces=['a','b','c'].map(ws);return s;}
beforeEach(()=>{vi.resetAllMocks();setActivePinia(createPinia());auth.me={id:'alice'} as any;auth.suspended=false;auth.sessionClosing=false;auth.sessionGeneration=1;auth.requestEpoch=1;m.workspaces.mockResolvedValue([ws('c')]);m.docs.mockResolvedValue([]);m.trash.mockResolvedValue([]);m.recent.mockResolvedValue([]);});
it('deletes each selected workspace once with force, then reuses active-workspace switching',async()=>{
 const s=setup();expect((s as any).deleteWorkspaceBatch,'workspace batch lifecycle').toBeTypeOf('function');
 const result=await (s as any).deleteWorkspaceBatch(['a','b','a']);
 expect(m.del.mock.calls).toEqual([['a',true,expect.any(Function)],['b',true,expect.any(Function)]]);
 expect(result.results).toEqual([{id:'a',status:'deleted'},{id:'b',status:'deleted'}]);
 expect(s.workspaceId).toBe('c');expect(s.workspaces).toEqual([ws('c')]);expect(m.docs).toHaveBeenCalledWith('c');
});
it.each(['workspace','session','generation','epoch','suspended','sessionClosing','unmounted'])(
 'held deletion stops later targets and reconciliation after %s changes',async(boundary)=>{
 const s=setup();let release!:()=>void;let alive=true;
 m.del.mockImplementationOnce(()=>new Promise<void>(r=>release=r));
 const pending=s.deleteWorkspaceBatch(['a','b'],()=>alive);
 if(boundary==='workspace')s.workspaceId='c';
 else if(boundary==='session'){s.resetSession();s.userId='alice';s.workspaceId='a';}
 else if(boundary==='generation')auth.sessionGeneration++;
 else if(boundary==='epoch')auth.requestEpoch++;
 else if(boundary==='unmounted')alive=false;
 else auth[boundary as 'suspended'|'sessionClosing']=true;
 release();const result=await pending;
 expect(m.del).toHaveBeenCalledTimes(1);expect(m.workspaces).not.toHaveBeenCalled();
 expect(result.results).toEqual([{id:'a',status:'deleted'},{id:'b',status:'skipped'}]);
});
it('readback failure preserves successful receipts rather than throwing into a destructive retry',async()=>{
 const s=setup();m.workspaces.mockRejectedValue(new Error('offline'));
 const result=await s.deleteWorkspaceBatch(['b']);
 expect(result).toMatchObject({results:[{id:'b',status:'deleted'}],refreshFailed:true});expect(m.del).toHaveBeenCalledTimes(1);
});
it('one pass reports partial and uncertain failures and continues without replaying successful targets',async()=>{
 const {ApiError}=await import('../../api/client');const s=setup();
 m.del.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new ApiError(409,{code:'attachment_in_use'})).mockRejectedValueOnce(new TypeError('network'));
 const result=await s.deleteWorkspaceBatch(['a','b','c']);
 expect(result.results).toEqual([{id:'a',status:'deleted'},{id:'b',status:'failed'},{id:'c',status:'unknown'}]);expect(m.del).toHaveBeenCalledTimes(3);
});
it('concurrent confirmations admit only one pass',async()=>{
 const s=setup();let release!:()=>void;m.del.mockImplementationOnce(()=>new Promise<void>(r=>release=r));
 const pending=s.deleteWorkspaceBatch(['b']);const duplicate=await s.deleteWorkspaceBatch(['b']);
 expect(duplicate.results).toEqual([{id:'b',status:'skipped'}]);expect(m.del).toHaveBeenCalledTimes(1);release();await pending;
});
it('unknown/unowned selections are not deletion authority',async()=>{
 const s=setup();s.workspaces.push({...ws('foreign'),user_id:'bob'});
 const result=await s.deleteWorkspaceBatch(['missing','foreign']);
 expect(m.del).not.toHaveBeenCalled();expect(result.results).toEqual([{id:'missing',status:'skipped'},{id:'foreign',status:'skipped'}]);
});
it('workspace leave/reentry cannot restore held admission',async()=>{
 const s=setup();let release!:()=>void;m.del.mockImplementationOnce(()=>new Promise<void>(r=>release=r));
 const pending=s.deleteWorkspaceBatch(['a','b']);s.workspaceId='c';s.workspaceId='a';release();await pending;
 expect(m.del).toHaveBeenCalledTimes(1);expect(m.workspaces).not.toHaveBeenCalled();
});
it('held workspace readback cannot overwrite a newer navigation',async()=>{
 const s=setup();let release!:(v:any)=>void;m.workspaces.mockImplementationOnce(()=>new Promise(r=>release=r));
 const pending=s.deleteWorkspaceBatch(['b']);await Promise.resolve();s.workspaceId='c';release([ws('a')]);await pending;
 expect(s.workspaces.map(w=>w.id)).toEqual(['a','b','c']);expect(s.workspaceId).toBe('c');
});
it('last workspace deletion reuses owner creation and switching without cache-mutating ensureWorkspace',async()=>{
 const s=setup();s.workspaces=[ws('a')];m.workspaces.mockResolvedValue([]);m.create.mockResolvedValue(ws('fresh'));
 await s.deleteWorkspaceBatch(['a']);expect(m.bootstrap).not.toHaveBeenCalled();expect(m.create).toHaveBeenCalledExactlyOnceWith('alice','云曦的笔记本');expect(s.workspaceId).toBe('fresh');
});
it('late last-workspace creation cannot overwrite a newer workspace or its bootstrap cache',async()=>{
 const s=setup();s.workspaces=[ws('a')];m.workspaces.mockResolvedValue([]);let release!:(v:any)=>void;m.create.mockImplementationOnce(()=>new Promise(r=>release=r));
 const pending=s.deleteWorkspaceBatch(['a']);for(let i=0;i<10;i++)await Promise.resolve();s.workspaceId='new';localStorage.setItem('stella_bootstrap','new-cache');expect(release).toBeTypeOf('function');release(ws('fresh'));await pending;
 expect(s.workspaceId).toBe('new');expect(localStorage.getItem('stella_bootstrap')).toBe('new-cache');
});
it('stale workspace inventory is not a verified deletion and never navigates back to deleted target',async()=>{
 const s=setup();m.workspaces.mockResolvedValue([ws('a'),ws('c')]);const result=await s.deleteWorkspaceBatch(['a']);
 expect(result.refreshFailed).toBe(true);expect(s.workspaceId).toBe('a');expect(result.results).toEqual([{id:'a',status:'deleted'}]);
});
it('read-only reconciliation retries the list and active switch, never the DELETE',async()=>{
 const s=setup();m.workspaces.mockRejectedValueOnce(new Error('offline')).mockResolvedValue([ws('c')]);
 const first=await s.deleteWorkspaceBatch(['a']);expect(first.refreshFailed).toBe(true);
 expect((s as any).reconcileWorkspaceDeletions).toBeTypeOf('function');
 await (s as any).reconcileWorkspaceDeletions(['a']);expect(m.del).toHaveBeenCalledTimes(1);expect(s.workspaceId).toBe('c');
});
