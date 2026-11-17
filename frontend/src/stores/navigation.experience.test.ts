import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { loadNavigation, navigation, resetNavigation, saveNavigation, type NavigationSnapshot, type NavRow } from './navigation';
vi.mock('../api/client', () => ({ api: vi.fn() }));
function deferred<T>() { let resolve!: (value:T)=>void; let reject!: (reason:unknown)=>void; const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;}); return {promise,resolve,reject}; }
const snapshot=(title:string,revision=0,mutation_id:string|null=null):NavigationSnapshot=>({entries:[{id:'home',title,icon:'home',visible:true}],modules:[],legacy_routes:{},revision,mutation_id});
const row=(title:string):NavRow=>({id:'home',label:title,icon:'home',visible:true,to:'/',builtin:true});
beforeEach(()=>{ resetNavigation();vi.mocked(api).mockReset(); });
afterEach(()=>{ resetNavigation();vi.useRealTimers(); });
it('coalesces concurrent startup callers and commits only the complete snapshot', async()=>{
 const config=deferred<NavigationSnapshot>();
 vi.mocked(api).mockReturnValue(config.promise);
 const first=loadNavigation(),second=loadNavigation();
 expect(api).toHaveBeenCalledTimes(1);expect(vi.mocked(api).mock.calls[0]![0]).toBe('/navigation');
 await Promise.resolve();expect(navigation.loaded).toBe(false);expect(navigation.entries).toEqual([]);
 // One complete wire snapshot replaces the retired two-source dependency.
 config.resolve(snapshot('首页'));expect(await first).toBe(true);expect(await second).toBe(true);
 expect(navigation.entries).toEqual([{id:'home',title:'首页',icon:'home',visible:true}]);expect(navigation.loaded).toBe(true);
 expect(await loadNavigation()).toBe(true);expect(api).toHaveBeenCalledTimes(1);
});
it('applies the committed write ACK without joining or being overwritten by a pre-write request', async()=>{
 vi.mocked(api).mockResolvedValueOnce(snapshot('原名称'));expect(await loadNavigation()).toBe(true);
 const old=deferred<NavigationSnapshot>();let reads=0,writes=0;
 vi.mocked(api).mockImplementation((path,options)=>{
  if(options?.method==='PUT'){
   writes++;const p=JSON.parse(options.body as string);expect(p.expected_revision).toBe(0);
   return Promise.resolve(snapshot('新名称',1,p.mutation_id));
  }
  expect(path).toBe('/navigation');reads++;return old.promise;
 });
 const stale=loadNavigation({force:true});await saveNavigation([row('新名称')]);
 expect(reads).toBe(1);expect(writes).toBe(1);
 old.resolve(snapshot('旧名称'));await stale;
 expect(navigation.entries).toEqual([{id:'home',title:'新名称',icon:'home',visible:true}]);expect(navigation.revision).toBe(1);
});
it('reset rejects late session results and a pending write cannot refresh the next session', async()=>{
 vi.mocked(api).mockResolvedValueOnce(snapshot('原会话'));expect(await loadNavigation()).toBe(true);
 const old=deferred<NavigationSnapshot>(),write=deferred<NavigationSnapshot>();let mutation='';
 vi.mocked(api).mockImplementation((_path,options)=>{if(options?.method==='PUT'){mutation=JSON.parse(options.body as string).mutation_id;return write.promise;}return old.promise;});
 const request=loadNavigation({force:true}),save=saveNavigation([row('private')]);const rejected=expect(save).rejects.toThrow();
 resetNavigation();vi.mocked(api).mockResolvedValueOnce({entries:[],modules:[],legacy_routes:{},revision:0,mutation_id:null});
 expect(await loadNavigation()).toBe(true);const calls=vi.mocked(api).mock.calls.length;
 old.resolve(snapshot('private'));write.resolve(snapshot('private',1,mutation));await request;await rejected;
 expect(api).toHaveBeenCalledTimes(calls);expect(navigation.entries).toEqual([]);expect(navigation.revision).toBe(0);
});
it('bounds stalled loading and preserves the previous complete snapshot on refresh error', async()=>{
 vi.useFakeTimers();vi.mocked(api).mockResolvedValueOnce(snapshot('完整'));
 expect(await loadNavigation()).toBe(true);vi.mocked(api).mockImplementation(()=>new Promise(()=>{}));
 const refresh=loadNavigation({force:true});await vi.advanceTimersByTimeAsync(15000);
 expect(navigation.error).toContain('重试');expect(navigation.loaded).toBe(true);
 expect(navigation.entries).toEqual([{id:'home',title:'完整',icon:'home',visible:true}]);expect(await refresh).toBe(false);
});
