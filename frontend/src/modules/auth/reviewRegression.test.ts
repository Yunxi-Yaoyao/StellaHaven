import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import {createApp,defineComponent,h,nextTick,ref} from 'vue';
import {auth,fetchMe,refreshAccess,acceptLogin,logout,loggedIn} from '../../modules/home/auth';
import {installSessionFence,privateRequest} from '../../modules/auth/sessionFence';
import {backgroundMedia,quality,useBackgroundMedia} from '../../modules/home/backgroundMedia';
import {protectedPage} from '../../router/protectedPage';
vi.mock('../../modules/home/settings',()=>({homeSettings:{},siteBackground:{value:''},DEFAULT_HOME_BG:'/assets/homebg/default.webp'}));
const owner={id:'fixture-owner',username:'fixture',display_name:'fresh-profile',home_bg:'fixture',avatar_url:'',is_admin:false,email:'',email_verified:false};
let restore:(()=>void)|undefined;let app:ReturnType<typeof createApp>|undefined;
beforeEach(()=>{Object.assign(auth,{me:{...owner},sessionGeneration:100,requestEpoch:0,sessionClosing:false,suspended:false,checked:true,error:''});});
afterEach(()=>{restore?.();restore=undefined;app?.unmount();app=undefined;vi.useRealTimers();vi.unstubAllGlobals();document.body.innerHTML='';});
it('review: public background metadata remains fetchable for a checked guest',async()=>{
 Object.assign(auth,{me:null});
 const native=vi.fn(async()=>new Response(JSON.stringify({url:'/assets/homebg/review.mp4',status:'ready',variants:{original:'/assets/homebg/review.mp4',compressed1:'/assets/homebg/review-compressed1.mp4'}})));
 vi.stubGlobal('fetch',native);restore=installSessionFence();
 await expect(fetch('/homebg/media?url=%2Fassets%2Fhomebg%2Freview.mp4')).resolves.toBeDefined();
});
it('review: real background consumer keeps compressed variant for guest',async()=>{
 Object.assign(auth,{me:null});quality.value='compressed1';
 const url='/assets/homebg/review-consumer.mp4';
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({url,status:'ready',variants:{original:url,compressed1:'/assets/homebg/review-consumer-small.mp4'}}))));restore=installSessionFence();
 const host=document.createElement('div');document.body.append(host);let consumer:any;
 app=createApp({setup(){consumer=useBackgroundMedia(ref(url));return ()=>h('div');}});app.mount(host);
 await new Promise(r=>setTimeout(r,20));
 expect({status:backgroundMedia[url]?.status,source:consumer.source.value}).toEqual({status:'ready',source:'/assets/homebg/review-consumer-small.mp4'});
});
it('review: old auth/me body must not overwrite profile after expiry and same-owner resume',async()=>{
 let release!:(r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(async(input)=>String(input)==='/auth/me'?new Promise<Response>(resolve=>release=resolve):new Response('{}',{status:401})));
 restore=installSessionFence();
 const old=fetchMe();await refreshAccess();expect(auth.suspended).toBe(true);
 acceptLogin({...owner,display_name:'new-profile'});expect(auth.sessionGeneration).toBe(100);
 release(new Response(JSON.stringify({...owner,display_name:'stale-profile'})));await old;
 expect(auth.me?.display_name).toBe('new-profile');
});
it('review: pending logout blocks cookie-issuing authentication until response completes',async()=>{
 let release!:(r:Response)=>void;
 const native=vi.fn(()=>new Promise<Response>(resolve=>release=resolve));
 vi.stubGlobal('fetch',native);restore=installSessionFence();
 const pending=logout();expect(loggedIn.value).toBe(false);
 expect(()=>acceptLogin({...owner,display_name:'reauthenticated'})).toThrow();
 for(const path of ['/auth/login','/auth/register','/auth/login-code','/auth/register-invite']){
  await expect(fetch(path,{method:'POST'})).rejects.toThrow();
 }
 expect(native).toHaveBeenCalledTimes(1);
 release(new Response('{}'));await pending;
 acceptLogin({...owner,display_name:'reauthenticated'});expect(loggedIn.value).toBe(true);
 expect(auth.me?.display_name).toBe('reauthenticated');
});
it('review: stale logout completion cannot mutate a newer request epoch',async()=>{
 let release!:(r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>release=resolve)));
 const pending=logout();
 // Simulate an external identity reset, not an allowed concurrent HTTP login.
 auth.requestEpoch++;auth.sessionClosing=false;auth.me={...owner,display_name:'reauthenticated'};
 release(new Response('{}'));await pending;
 expect(auth.me?.display_name).toBe('reauthenticated');
});
it('review: only exact public background metadata GET is exempt',()=>{
 expect(privateRequest('/homebg/media?url=x')).toBe(false);
 for(const [path,method] of [['/homebg/','GET'],['/homebg/media','POST'],['/homebg/media/x','GET'],['/homebg/media','DELETE'],['/homebg/id/optimize','POST']])expect(privateRequest(path!,method)).toBe(true);
});
it('review: rejected logout leaves an interactive retryable session',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:503})));restore=installSessionFence();
 await expect(logout()).rejects.toThrow();
 expect({loggedIn:loggedIn.value,closing:auth.sessionClosing}).toEqual({loggedIn:true,closing:false});
});
it('review: transport-failed logout retains identity and allows a successful retry',async()=>{
 const native=vi.fn().mockRejectedValueOnce(new TypeError('Fixture transport failure')).mockResolvedValueOnce(new Response('{}'));
 vi.stubGlobal('fetch',native);
 await expect(logout()).rejects.toThrow('Fixture transport failure');
 expect(loggedIn.value).toBe(true);expect(auth.sessionClosing).toBe(false);expect(auth.logoutError).toContain('退出未成功');
 await logout();expect(auth.me).toBeNull();expect(auth.sessionClosing).toBe(false);expect(native).toHaveBeenCalledTimes(2);
});
it('review: rejected guest refresh completes the initial identity check',async()=>{
 Object.assign(auth,{me:null,checked:false});
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:401})));
 expect(await fetchMe()).toBe(false);expect(auth.checked).toBe(true);expect(auth.suspended).toBe(false);
});
it('review: node detail wrapper forwards nodeId and keeps component on suspension',async()=>{
 const values:number[]=[];let mounts=0;
 const page=defineComponent({props:{nodeId:Number},setup(p){mounts++;return()=>{values.push(p.nodeId!);return h('div',String(p.nodeId));};}});
 const Wrapper=protectedPage('status-node',async()=>({default:page,__esModule:true}));const id=ref(19);
 const host=document.createElement('div');document.body.append(host);
 app=createApp({render:()=>h(Wrapper,{nodeId:id.value})});app.mount(host);
 await vi.waitFor(()=>expect(host.textContent).toBe('19'),{timeout:1000});
 id.value=20;await nextTick();expect(host.textContent).toBe('20');
 auth.suspended=true;await nextTick();expect(host.textContent).toBe('20');
 acceptLogin(owner);await nextTick();expect(mounts).toBe(1);
});
