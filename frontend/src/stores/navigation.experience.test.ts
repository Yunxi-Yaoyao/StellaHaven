import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { loadNavigation, navigation, resetNavigation, saveNavigation } from './navigation';
vi.mock('../api/client', () => ({ api: vi.fn() }));
function deferred<T>() { let resolve!: (value:T)=>void; let reject!: (reason:unknown)=>void; const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;}); return {promise,resolve,reject}; }
beforeEach(()=>{ resetNavigation();vi.mocked(api).mockReset(); });
afterEach(()=>{ resetNavigation();vi.useRealTimers(); });
it('coalesces concurrent startup callers and commits only the complete snapshot', async()=>{
 const config=deferred<any>(),modules=deferred<any>();
 vi.mocked(api).mockImplementation(path=>path==='/navigation'?config.promise:modules.promise);
 const first=loadNavigation(),second=loadNavigation();
 expect(api).toHaveBeenCalledTimes(2);
 config.resolve({entries:[{id:'home',title:'首页'}]});await Promise.resolve();
 expect(navigation.loaded).toBe(false);expect(navigation.entries).toEqual([]);
 modules.resolve([]);expect(await first).toBe(true);expect(await second).toBe(true);
 expect(navigation.entries[0]?.title).toBe('首页');expect(navigation.loaded).toBe(true);
});
it('starts readback after a write instead of joining a pre-write request', async()=>{
 const old=deferred<any>();let reads=0;
 vi.mocked(api).mockImplementation((path,options)=>{
  if(options?.method==='PUT')return Promise.resolve({});
  if(path==='/navigation')return ++reads===1?old.promise:Promise.resolve({entries:[{id:'home',title:'新名称'}]});
  return Promise.resolve([]);
 });
 const stale=loadNavigation();const save=saveNavigation([]);
 for(let i=0;i<10;i++)await Promise.resolve();
 expect(reads).toBe(2);
 await save;old.resolve({entries:[{id:'home',title:'旧名称'}]});await stale;
 expect(navigation.entries[0]?.title).toBe('新名称');
});
it('reset rejects late session results and a pending write cannot refresh the next session', async()=>{
 const old=deferred<any>(),write=deferred<any>();
 vi.mocked(api).mockImplementation((_path,options)=>options?.method==='PUT'?write.promise:old.promise);
 const request=loadNavigation(),save=saveNavigation([]);const rejected=expect(save).rejects.toThrow();
 resetNavigation();vi.mocked(api).mockResolvedValueOnce({entries:[]}).mockResolvedValueOnce([]);
 await loadNavigation();const calls=vi.mocked(api).mock.calls.length;
 old.resolve({entries:[{id:'home',title:'private'}]});write.resolve({});await request;await rejected;
 expect(api).toHaveBeenCalledTimes(calls);expect(navigation.entries).toEqual([]);
});
it('bounds stalled loading and preserves the previous complete snapshot on refresh error', async()=>{
 vi.useFakeTimers();vi.mocked(api).mockResolvedValueOnce({entries:[{id:'home',title:'完整'}]}).mockResolvedValueOnce([]);
 await loadNavigation();vi.mocked(api).mockImplementation(()=>new Promise(()=>{}));
 const refresh=loadNavigation();await vi.advanceTimersByTimeAsync(15000);
 expect(navigation.error).toContain('重试');expect(navigation.loaded).toBe(true);
 expect(navigation.entries[0]?.title).toBe('完整');expect(await refresh).toBe(false);
});
