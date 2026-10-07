import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {auth,fetchMe,refreshAccess,logout} from './auth';
const owner={id:'old-owner',username:'fixture',display_name:'fixture',is_admin:false,avatar_url:'',home_bg:'/fixture.png',email:'',email_verified:false};
function deferred<T>(){let resolve!:(v:T)=>void,reject!:(e:Error)=>void;const promise=new Promise<T>((r,j)=>{resolve=r;reject=j});return {promise,resolve,reject};}
beforeEach(()=>{Object.assign(auth,{me:{...owner},checked:true,error:'',sessionGeneration:auth.sessionGeneration+1,sessionClosing:false});localStorage.clear();});
afterEach(()=>vi.unstubAllGlobals());
for(const [name,request] of [['fetchMe',fetchMe],['refreshAccess',refreshAccess]] as const){
 for(const kind of ['success','unauthorized','server-error','exception','delayed-json'] as const){
  it(name+' discards stale '+kind+' after completed logout/new identity',async()=>{
   const response=deferred<Response>(),body=deferred<any>();
   const mock=vi.fn().mockImplementation((url:string)=>url==='/auth/logout'?Promise.resolve(new Response('{}')):response.promise);vi.stubGlobal('fetch',mock);
   const old=request();
   if(kind==='delayed-json'){response.resolve({ok:true,json:()=>body.promise} as Response);await Promise.resolve();await Promise.resolve();}
   await logout();expect(auth.me).toBeNull();
   Object.assign(auth,{me:{...owner,id:'new-owner'},error:'new-state',checked:false});auth.sessionGeneration++;
   if(kind==='exception')response.reject(new Error('old transport'));
   else if(kind==='delayed-json')body.resolve(owner);
   else response.resolve(new Response(JSON.stringify(owner),{status:kind==='success'?200:kind==='unauthorized'?401:500}));
   expect(await old).toBe(false);expect(auth.me?.id).toBe('new-owner');expect(auth.error).toBe('new-state');expect(auth.checked).toBe(false);
  });
 }
 it(name+' does not start while logout is in progress',async()=>{
  auth.sessionClosing=true;const mock=vi.fn();vi.stubGlobal('fetch',mock);expect(await request()).toBe(false);expect(mock).not.toHaveBeenCalled();
 });
}
it('legacy background readback cannot restore identity after logout',async()=>{
 localStorage.setItem('stella_home_bg','/old-fixture.png');const patched=deferred<Response>();let patchStarted=false;
 vi.stubGlobal('fetch',vi.fn((url:string,options?:RequestInit)=>{if(url==='/auth/logout')return Promise.resolve(new Response('{}'));if(options?.method==='PATCH'){patchStarted=true;return patched.promise;}return Promise.resolve(new Response(JSON.stringify({...owner,home_bg:''})));}));
 expect(await fetchMe()).toBe(true);expect(patchStarted).toBe(true);await logout();
 patched.resolve(new Response(JSON.stringify({...owner,home_bg:'/old-fixture.png'})));await new Promise(r=>setTimeout(r,0));expect(auth.me).toBeNull();
});
it('an old refresh completion cannot clear or join the new session refresh flight',async()=>{
 const oldResponse=deferred<Response>(),newResponse=deferred<Response>();let calls=0;
 vi.stubGlobal('fetch',vi.fn((url:string)=>{if(url==='/auth/logout')return Promise.resolve(new Response('{}'));calls++;return calls===1?oldResponse.promise:newResponse.promise;}));
 const old=refreshAccess();await logout();auth.sessionGeneration++;auth.me={...owner,id:'new-owner'};
 const next=refreshAccess();expect(calls).toBe(2);expect(next).not.toBe(old);
 oldResponse.resolve(new Response(JSON.stringify(owner)));expect(await old).toBe(false);
 const joined=refreshAccess();expect(joined).toBe(next);expect(calls).toBe(2);
 newResponse.resolve(new Response(JSON.stringify({...owner,id:'new-owner'})));expect(await next).toBe(true);expect(auth.me?.id).toBe('new-owner');
});
