import {installSessionFence} from './sessionFence';
import {api} from '../../api/client';
import {it,expect,vi,beforeEach} from 'vitest';
import {auth,refreshAccess,login,loggedIn,logout} from '../home/auth';
const me={id:'owner',username:'fixture',display_name:'Fixture',is_admin:false,home_bg:'fixture',avatar_url:'',email:'',email_verified:false};
beforeEach(()=>{Object.assign(auth,{me:{...me},sessionClosing:false,suspended:false,checked:true,error:''});vi.restoreAllMocks();});
it('confirmed expiry suspends identity without destroying the mounted owner draft',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:401})));
 expect(await refreshAccess()).toBe(false);
 expect(loggedIn.value).toBe(false);
 expect(auth.suspended).toBe(true);
 expect(auth.me?.id).toBe('owner');
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(me),{status:200})));
 const generation=auth.sessionGeneration;
 expect(await login('fixture','fixture-only',true)).toBeNull();
 expect(auth.suspended).toBe(false);
 expect(auth.sessionGeneration).toBe(generation);
});
it('suspended private calls never reach the network',async()=>{
 auth.suspended=true;const fetch=vi.fn(async()=>new Response('{"secret":"new content"}',{status:200}));vi.stubGlobal('fetch',fetch);
 await expect(api('/documents/')).rejects.toThrow();expect(fetch).not.toHaveBeenCalled();
});
it('a response started before suspension cannot overwrite a resumed session',async()=>{
 let release!:(r:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{release=resolve;})));
 const pending=api('/documents/');auth.suspended=true;
 const oldFetch=fetch;vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(me))));await login('fixture','fixture-only',true);vi.stubGlobal('fetch',oldFetch);
 release(new Response('{"secret":"stale private result"}'));await expect(pending).rejects.toThrow();
});
it('native fetch rejects late content and blocks suspended polling, but permits login',async()=>{
 let release!:(r:Response)=>void;
 const native=vi.fn(()=>new Promise<Response>(resolve=>{release=resolve;}));vi.stubGlobal('fetch',native);
 const restore=installSessionFence();
 try{
  const pending=fetch('/documents/');auth.suspended=true;release(new Response('{"secret":"late"}'));
  await expect(pending).rejects.toThrow();
  await expect(fetch('/nodes/')).rejects.toThrow();expect(native).toHaveBeenCalledTimes(1);
  const entry=fetch('/auth/login',{method:'POST'});release(new Response('{}'));await expect(entry).resolves.toBeDefined();
 }finally{restore();}
});
it('logout clears even a suspended owner',async()=>{
 auth.suspended=true;vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:200})));
 await logout();expect(auth.me).toBeNull();expect(auth.suspended).toBe(false);
});
