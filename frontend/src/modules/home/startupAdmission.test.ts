import {beforeEach,afterEach,it,expect,vi} from 'vitest';
vi.mock('./settings',()=>({homeSettings:{},siteBackground:{value:'baseline'},DEFAULT_HOME_BG:''}));
import {auth,loadSiteConfig,fetchMe,refreshAccess,acceptLogin} from './auth';
import {siteBackground} from './settings';
const owner={id:'owner',home_bg:'fixture'} as any;
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}
beforeEach(()=>{Object.assign(auth,{me:null,sessionGeneration:auth.sessionGeneration+1,requestEpoch:0,checked:false,suspended:false,sessionClosing:false,error:''});siteBackground.value='baseline';});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
it('same identity site config reads join a single in-flight pair',async()=>{
 const response=deferred<Response>();const fetch=vi.fn(()=>response.promise);vi.stubGlobal('fetch',fetch);
 const one=loadSiteConfig(),two=loadSiteConfig();expect(fetch).toHaveBeenCalledTimes(2);
 response.resolve({ok:true,json:async()=>({initialized:true,value:'fresh'})} as Response);await Promise.all([one,two]);expect(siteBackground.value).toBe('fresh');
});
it('late public config cannot replace a new owner background',async()=>{
 const response=deferred<Response>();vi.stubGlobal('fetch',vi.fn(()=>response.promise));const old=loadSiteConfig();
 acceptLogin(owner);siteBackground.value='new-owner';response.resolve({ok:true,json:async()=>({value:'stale'})} as Response);await old;expect(siteBackground.value).toBe('new-owner');
});
it.each([401,403])('confirmed guest refresh %s has one refresh and no retry timer',async status=>{
 vi.useFakeTimers();const fetch=vi.fn(async(_url:string)=>new Response('{}',{status}));vi.stubGlobal('fetch',fetch);
 const result=fetchMe();await vi.advanceTimersByTimeAsync(0);expect(fetch.mock.calls.filter(c=>c[0]==='/auth/refresh')).toHaveLength(1);expect(vi.getTimerCount()).toBe(0);
 await vi.advanceTimersByTimeAsync(301);expect(await result).toBe(false);expect(auth.checked).toBe(true);expect(auth.error).toBe('');
});
it('known-owner 401 retains one bounded rotation-race retry',async()=>{
 auth.me=owner;vi.useFakeTimers();let calls=0;vi.stubGlobal('fetch',vi.fn(async()=>++calls===1?new Response('{}',{status:401}):new Response(JSON.stringify(owner))));
 const result=refreshAccess();await vi.advanceTimersByTimeAsync(299);expect(calls).toBe(1);await vi.advanceTimersByTimeAsync(1);expect(await result).toBe(true);expect(calls).toBe(2);
});
it('known owner with an explicitly missing refresh cookie does not retry',async()=>{
 auth.me=owner;vi.useFakeTimers();const fetch=vi.fn(async()=>new Response(JSON.stringify({detail:'无刷新令牌'}),{status:401}));vi.stubGlobal('fetch',fetch);
 const result=refreshAccess();await vi.advanceTimersByTimeAsync(0);expect(vi.getTimerCount()).toBe(0);await vi.advanceTimersByTimeAsync(300);expect(await result).toBe(false);expect(fetch).toHaveBeenCalledTimes(1);
});
it('cold cross-tab rotation evidence retains a bounded retry without a cached identity',async()=>{
 vi.useFakeTimers();let calls=0;vi.stubGlobal('fetch',vi.fn(async()=>++calls===1?new Response(JSON.stringify({detail:'会话已失效'}),{status:401}):new Response(JSON.stringify(owner))));
 const result=refreshAccess();await vi.advanceTimersByTimeAsync(300);expect(await result).toBe(true);expect(calls).toBe(2);
});
it('parallel cold identity callers share one me probe and one refresh',async()=>{
 const reply=deferred<Response>();const fetch=vi.fn(()=>reply.promise);vi.stubGlobal('fetch',fetch);
 const first=fetchMe(),second=fetchMe();expect(fetch).toHaveBeenCalledTimes(1);
 reply.resolve(new Response(JSON.stringify(owner)));expect(await first).toBe(true);expect(await second).toBe(true);
});
it('transport failure remains retryable rather than confirmed guest',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new TypeError('offline')));expect(await fetchMe()).toBe(false);expect(auth.error).not.toBe('');expect(auth.suspended).toBe(false);
});
