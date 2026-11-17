import {createApp,h,KeepAlive,nextTick,type App} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import {it,expect,vi,afterEach,beforeEach} from 'vitest';
vi.mock('./AvatarCropper.vue',()=>({default:{template:'<div />'}}));
vi.mock('./NavigationSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../../shell/SettingsPanel.vue',()=>({default:{template:'<div />'}}));
vi.mock('./PerformanceSettings.vue',()=>({default:{template:'<div data-performance />'}}));
vi.mock('./SecuritySettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('./AuthProviderSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('./NodeMonitoringPolicySettings.vue',()=>({default:{template:'<section data-policy>节点自动监控</section>'}}));
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'owner',display_name:'测试',username:'owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false}),isAdmin:ref(true),currentAvatar:ref(''),logout:vi.fn()};});
vi.mock('../../api/servers',()=>({getPublicHost:vi.fn().mockResolvedValue({value:''}),setPublicHost:vi.fn()}));
import {auth,isAdmin} from '../home/auth';
import SettingsPage from './SettingsPage.vue';
let app:App|undefined;
const unexpectedRequests:string[]=[];
const row=(id:string,current=false)=>({id,current,device:id,ip:'192.0.2.1',remember:true,created_at:'2026-10-19T00:00:00Z',last_seen:'2026-10-19T00:00:00Z',expires_at:'2026-11-18T00:00:00Z',owner:'owner',mine:true});
const flush=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};
// Only the first refresh belongs to the retired lifetime. Hold newer bodies
// until after the privacy assertion so fresh data cannot mask a stale commit.
function delayedSessions(){
 let resolve!:(value:unknown)=>void,reject!:(error:Error)=>void,releaseFresh!:()=>void,started=0,delivered=0;
 const pending=new Promise((yes,no)=>{resolve=yes;reject=no;});
 const fresh=new Promise<void>(yes=>{releaseFresh=yes;});
 const bodies:Promise<unknown>[]=[];
 const handler=(url:string)=>{
  if(started++>=3)return fresh.then(()=>url.includes('current_only')?[row('FRESH-CURRENT',true)]:[]);
  const body=(async()=>{try{return await pending;}finally{delivered++;}})();
  bodies.push(body);return body;
 };
 return {handler,resolve,reject,releaseFresh,started:()=>started,delivered:()=>delivered,settled:()=>Promise.allSettled(bodies)};
}
async function mount(section='authentication',handler:(url:string)=>Promise<unknown>=async u=>u.includes('current_only')?[row('pinned',true)]:u.includes('page_size=1&')?[row('lookahead')]:u.includes('page=2&')?[row('page-two')]:Array.from({length:20},(_,i)=>row('other-'+i)),retained=false){
 const fetchMock=vi.fn(async(url:string,init?:RequestInit)=>{
  const method=init?.method??'GET';
  if(method==='GET'&&/^\/auth\/sessions\?(?:current_only=true|page=[1-9]\d*&page_size=(?:20|1)&exclude_current=true)$/.test(url))return {ok:true,json:()=>handler(url)};
  if(method==='GET'&&url==='/auth/avatars')return {ok:true,json:async()=>[]};
  if(method==='GET'&&url==='/auth/email-service')return {ok:true,json:async()=>({ready:false})};
  unexpectedRequests.push(`${method} ${url}`);throw Error(`Unexpected fixture request: ${method} ${url}`);
 });vi.stubGlobal('fetch',fetchMock);
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage},{path:'/status',component:{template:'<div data-overview />'}},{path:'/help',component:{template:'<div />'}}]});await router.push('/settings?section='+section);await router.isReady();
 const root=document.createElement('div');document.body.append(root);
 app=createApp({render:()=>h(RouterView,{}, {default:({Component}:any)=>retained?h(KeepAlive,{},()=>h(Component)):h(Component)})});
 app.use(router);app.mount(root);await flush();return {root,router,fetchMock};
}
beforeEach(()=>{unexpectedRequests.length=0;vi.spyOn(document,'hasFocus').mockReturnValue(true);Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});(isAdmin as unknown as {value:boolean}).value=true;Object.assign(auth,{me:{id:'owner',display_name:'测试',username:'owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});});
afterEach(()=>{app?.unmount();document.body.innerHTML='';vi.unstubAllGlobals();vi.restoreAllMocks();expect(unexpectedRequests).toEqual([]);});
it('redirects obsolete server settings to the existing monitor overview without mounting a second policy surface',async()=>{const {root,router}=await mount('servers');await flush();expect(router.currentRoute.value.fullPath).toBe('/status?view=overview#service-monitors');expect(root.querySelector('[data-policy]')).toBeNull();expect(root.querySelector('[data-performance]')).toBeNull();expect([...root.querySelectorAll('.tab')].some(e=>e.textContent==='服务器')).toBe(false);expect([...root.querySelectorAll('.tab')].some(e=>e.textContent==='笔记')).toBe(false);});
it('redirects the legacy tab link even when management is locked',async()=>{(isAdmin as unknown as {value:boolean}).value=false;const {root,router}=await mount('profile');await router.replace('/settings?tab=servers');await flush();expect(router.currentRoute.value.fullPath).toBe('/status?view=overview#service-monitors');expect(root.querySelector('[data-policy]')).toBeNull();expect(root.textContent).not.toContain('解锁管理保护后配置节点自动监控。');});
it('pins independently queried older current across other pages and explains expiry without claiming online',async()=>{
 const {root,fetchMock}=await mount();expect(fetchMock).toHaveBeenCalledWith('/auth/sessions?current_only=true');expect(root.querySelector('.sess-device')?.textContent).toContain('pinned');expect(root.textContent).toContain('到期');expect(root.textContent).not.toContain('不随 refresh 续期');root.querySelector<HTMLButtonElement>('[aria-label="登录记录说明"]')!.click();await flush();expect(document.querySelector('[role="tooltip"]')?.textContent).toContain('不随 refresh 续期');
 const next=[...root.querySelectorAll('button')].find(e=>e.textContent==='下一页')!;next.click();await flush();expect(root.querySelector('.sess-device')?.textContent).toContain('pinned');expect(root.textContent).toContain('page-two');expect(root.textContent).not.toContain('other-0');expect(root.querySelector('[data-other-sessions]')?.textContent).not.toContain('pinned');
});
it('ignores retired management-grant changes and keeps access-owned current without extra reads',async()=>{const {root,fetchMock}=await mount();expect(root.querySelector('.session-state.is-current')).not.toBeNull();(isAdmin as unknown as {value:boolean}).value=false;await flush();expect(root.querySelector('.session-state.is-current')).not.toBeNull();expect(fetchMock.mock.calls.filter(([u])=>u==='/auth/sessions?current_only=true')).toHaveLength(1);});
it.each(['owner','session','epoch','suspended','closing','route'] as const)('rejects old success across %s fence',async kind=>{
 const delayed=delayedSessions();const {root,router}=await mount('authentication',delayed.handler);
 expect(delayed.started()).toBe(3);
 if(kind==='owner')auth.me={...auth.me!,id:'other-owner'};if(kind==='session')auth.sessionGeneration++;if(kind==='epoch')auth.requestEpoch++;if(kind==='suspended')auth.suspended=true;if(kind==='closing')auth.sessionClosing=true;
 // profile and authentication are aliases of account, not a privacy boundary.
 if(kind==='route'){
  await router.replace('/settings?section=performance');expect(root.querySelector('[data-performance]')).not.toBeNull();
  await router.replace('/settings?section=account');expect(root.querySelector('#sessions')).not.toBeNull();
 }
 await flush();delayed.resolve([row('STALE-PRIVATE',true)]);await delayed.settled();await flush();
 expect(delayed.delivered()).toBe(3);expect(root.textContent).not.toContain('STALE-PRIVATE');
 if(kind==='suspended')auth.suspended=false;if(kind==='closing')auth.sessionClosing=false;
 delayed.releaseFresh();await flush();expect(root.textContent).toContain('FRESH-CURRENT');expect(root.textContent).not.toContain('STALE-PRIVATE');
});
it.each(['owner','session','epoch','suspended','closing','route'] as const)('rejects old failure across %s fence',async kind=>{
 const delayed=delayedSessions();const {root,router}=await mount('authentication',delayed.handler);
 expect(delayed.started()).toBe(3);
 if(kind==='owner')auth.me={...auth.me!,id:'other-owner'};if(kind==='session')auth.sessionGeneration++;if(kind==='epoch')auth.requestEpoch++;if(kind==='suspended')auth.suspended=true;if(kind==='closing')auth.sessionClosing=true;
 if(kind==='route'){
  await router.replace('/settings?section=performance');expect(root.querySelector('[data-performance]')).not.toBeNull();
  await router.replace('/settings?section=account');expect(root.querySelector('#sessions')).not.toBeNull();
 }
 await flush();delayed.reject(new Error('old failure'));await delayed.settled();await flush();
 expect(delayed.delivered()).toBe(3);expect(root.textContent).not.toContain('会话读取失败');expect(root.textContent).not.toContain('会话更新失败');
 if(kind==='suspended')auth.suspended=false;if(kind==='closing')auth.sessionClosing=false;
 delayed.releaseFresh();await flush();expect(root.textContent).toContain('FRESH-CURRENT');expect(root.textContent).not.toContain('会话更新失败');
});
it.each(['/settings?section=profile','/settings?section=account#login-security','/settings?section=authentication&view=other#sessions'])('keeps the same account read across alias/query navigation to %s',async target=>{
 const delayed=delayedSessions();const {root,router}=await mount('authentication',delayed.handler);
 const profile=root.querySelector('.profile-settings');expect(profile).not.toBeNull();expect(delayed.started()).toBe(3);
 await router.replace(target);await flush();expect(router.currentRoute.value.fullPath).toBe(target);
 expect(root.querySelector('.profile-settings')).toBe(profile);expect(delayed.started()).toBe(3);
 delayed.resolve([row('CURRENT-PRIVATE',true)]);await delayed.settled();await flush();
 expect(delayed.delivered()).toBe(3);expect(root.textContent).toContain('CURRENT-PRIVATE');
});
it.each([false,true])('rejects a late success after route leave and return (retained=%s)',async retained=>{
 const delayed=delayedSessions();const {root,router}=await mount('authentication',delayed.handler,retained);
 const page=root.querySelector('.page');expect(page).not.toBeNull();expect(delayed.started()).toBe(3);
 await router.push('/status');await flush();expect(root.querySelector('[data-overview]')).not.toBeNull();expect(root.querySelector('#sessions')).toBeNull();
 // Reactivate before delivery: hiding the old DOM alone cannot pass this test.
 await router.push('/settings?section=account');await flush();
 if(retained)expect(root.querySelector('.page')).toBe(page);else expect(root.querySelector('.page')).not.toBe(page);
 delayed.resolve([row('STALE-PRIVATE',true)]);await delayed.settled();await flush();
 expect(delayed.delivered()).toBe(3);expect(root.textContent).not.toContain('STALE-PRIVATE');expect(page?.textContent).not.toContain('STALE-PRIVATE');
 delayed.releaseFresh();await flush();expect(root.textContent).toContain('FRESH-CURRENT');
});
it.each([false,true])('rejects a late failure after route leave and return (retained=%s)',async retained=>{
 const delayed=delayedSessions();const {root,router}=await mount('authentication',delayed.handler,retained);
 expect(delayed.started()).toBe(3);await router.push('/status');await flush();expect(root.querySelector('[data-overview]')).not.toBeNull();
 await router.push('/settings?section=account');await flush();
 delayed.reject(new Error('old failure'));await delayed.settled();await flush();
 expect(delayed.delivered()).toBe(3);expect(root.textContent).not.toContain('会话读取失败');expect(root.textContent).not.toContain('会话更新失败');
 delayed.releaseFresh();await flush();expect(root.textContent).toContain('FRESH-CURRENT');
});
it('shows a current read failure so the stale-failure oracle cannot pass on obsolete copy',async()=>{
 const delayed=delayedSessions();const {root}=await mount('authentication',delayed.handler);
 expect(delayed.started()).toBe(3);delayed.reject(new Error('current failure'));await delayed.settled();await flush();
 expect(delayed.delivered()).toBe(3);expect(root.textContent).toContain('会话更新失败');
});
