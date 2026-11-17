import {createApp,nextTick,h,ref,KeepAlive,type App} from 'vue';
import {it,expect,vi,afterEach} from 'vitest';
import AuthProviderSettings from './AuthProviderSettings.vue';
import {toasts} from '../../composables/useToast';
import {api} from '../../api/client';
import {isAdmin,auth} from '../home/auth';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
vi.mock('../../api/client',()=>({api:vi.fn()}));
vi.mock('../home/auth',async()=>{const {ref,reactive}=await import('vue');return {isAdmin:ref(true),auth:reactive({sessionGeneration:0,requestEpoch:0,sessionClosing:false,suspended:false,me:{id:'fixture-owner'}})};});
let app:App|undefined;
export const tick=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};
afterEach(()=>{toasts.splice(0);app?.unmount();app=undefined;document.body.innerHTML='';vi.resetAllMocks();(isAdmin as any).value=true;Object.assign(auth,{sessionGeneration:0,requestEpoch:0,sessionClosing:false,suspended:false,me:{id:'fixture-owner'}});localStorage.clear();sessionStorage.clear();});
it('folds connected apps and each advanced detail by default, without folding the draft editor or one-time secret',async()=>{
 backend();const root=await mount();const list=root.querySelector<HTMLDetailsElement>('[data-connected-apps]');expect(list).not.toBeNull();expect(list!.open).toBe(false);expect(list!.querySelector('summary')?.textContent).toContain('已连接应用（1）');
 list!.open=true;await tick();const item=root.querySelector<HTMLDetailsElement>('[data-client-details]')!;expect(item.open).toBe(false);expect(item.querySelector('summary')?.textContent).toContain('私人相册');await click(root,'编辑');input(root,'应用名称','未保存的草稿');list!.open=false;await tick();expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('未保存的草稿');expect(root.querySelector('form')?.closest('[data-connected-apps]')).toBeNull();
});
it('edits application origins and purpose paths, keeps sparse and native history, previews exact additions before one PATCH',async()=>{
 const b=backend();b.state.clients[0]!.redirect_uris=['https://photos.test/auth/login','https://photos.p/user-settings','http://localhost/auth/login','app.immich:///oauth-callback'];
 const root=await mount();await click(root,'编辑');
 expect(root.querySelector<HTMLInputElement>('[aria-label="应用地址 1"]')?.value).toBe('https://photos.test');
 expect(root.querySelector<HTMLTextAreaElement>('[aria-label="回调用途路径 2"]')?.value).toBe('/user-settings');
 expect(root.textContent).toContain('Immich移动App');expect(root.querySelector<HTMLDetailsElement>('[data-legacy-callbacks]')?.open).toBe(false);
 input(root,'回调用途路径 1','/auth/login\n/user-settings');input(root,'回调用途路径 2','/user-settings\n/auth/login');await tick();
 await click(root,'预览变更');expect(b.writes).toHaveLength(0);
 const diff=root.querySelector('[aria-label="回调变更摘要"]')!;expect(diff.textContent).toContain('新增 2');expect(diff.textContent).toContain('移除 0');
 await click(root,'保存变更');expect(b.writes).toHaveLength(1);expect(b.writes[0]!.body.redirect_uris).toEqual(['https://photos.test/auth/login','https://photos.p/user-settings','http://localhost/auth/login','app.immich:///oauth-callback','https://photos.test/user-settings','https://photos.p/auth/login']);
});
it('keeps unrecognized legacy registrations out of unrelated metadata PATCH and retains custom scopes',async()=>{
 const b=backend();b.state.clients[0]!.redirect_uris.push('https://old.test/cb?old=1');b.state.clients[0]!.scopes=['openid'];
 const root=await mount();await click(root,'编辑');input(root,'应用名称','保留旧登记');await tick();await click(root,'预览变更');await click(root,'保存变更');
 expect(b.writes[0]!.body).toEqual({name:'保留旧登记'});expect(b.state.clients[0]!.redirect_uris).toContain('https://old.test/cb?old=1');expect(b.state.clients[0]!.scopes).toEqual(['openid']);
});
it('keeps drafts through a declined leave and exposes a real dirty-navigation barrier',async()=>{
 backend();const root=document.createElement('div');document.body.append(root);let vm:any;
 app=createApp({render:()=>h(AuthProviderSettings,{ref:(value:any)=>{vm=value;}})});app.mount(root);await tick();
 await click(root,'编辑');input(root,'应用名称','不能丢的草稿');await tick();
 let result:unknown;const flight=vm.beforeLeave().then((value:boolean)=>{result=value;});await tick();expect(result).toBeUndefined();
 expect(root.querySelector('[role="alertdialog"]')).not.toBeNull();await click(root,'继续编辑');await flight;expect(result).toBe(false);expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('不能丢的草稿');
 const leave=vm.beforeLeave();await tick();await click(root,'放弃草稿并离开');expect(await leave).toBe(true);
});
it('invalidates preview when the user changes a path and never writes an unreviewed callback',async()=>{
 const b=backend(),root=await mount();await click(root,'编辑');input(root,'回调用途路径 1','/new');await tick();await click(root,'预览变更');expect(root.querySelector('[aria-label="变更预览"]')).not.toBeNull();
 input(root,'回调用途路径 1','//evil.test/cb');await tick();expect(root.querySelector('[aria-label="变更预览"]')).toBeNull();await click(root,'预览变更');expect(b.writes).toHaveLength(0);expect(root.querySelector('[role="alert"]')?.textContent).toContain('单个 /');expect(root.querySelector<HTMLTextAreaElement>('[aria-label="回调用途路径 1"]')?.value).toBe('//evil.test/cb');
});
it('generic apps start without guessed callback paths and legacy removal stays preview-only until applied',async()=>{
 const b=backend();b.state.clients[0]!.redirect_uris.push('http://localhost/cb','app.immich:///oauth-callback');
 const root=await mount();await click(root,'连接应用');expect(root.querySelector<HTMLTextAreaElement>('[aria-label="回调用途路径 1"]')?.value).toBe('');await click(root,'取消');
 await click(root,'编辑');const remove=root.querySelector<HTMLButtonElement>('[aria-label="移除旧登记 1"]')!;remove.click();await tick();await click(root,'预览变更');expect(b.writes).toHaveLength(0);expect(root.querySelector('[aria-label="回调变更摘要"]')?.textContent).toContain('移除 1');expect(root.querySelector('[aria-label="回调变更摘要"]')?.textContent).toContain('http://localhost/cb');expect(root.textContent).toContain('app.immich:///oauth-callback');
});
it('real route leave asks before discarding a dirty draft and Escape keeps the form',async()=>{
 backend();const root=document.createElement('div');document.body.append(root);
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',redirect:'/settings'},{path:'/settings',component:AuthProviderSettings},{path:'/elsewhere',component:{render:()=>h('p','Elsewhere')}}]});
 app=createApp({render:()=>h(RouterView)});app.use(router);await router.push('/settings');await router.isReady();app.mount(root);await tick();
 await click(root,'编辑');input(root,'应用名称','离开前的草稿');await tick();
 const leaving=router.push('/elsewhere');await tick();const dialog=root.querySelector<HTMLElement>('[role="alertdialog"]')!;expect(dialog).not.toBeNull();dialog.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await leaving;await tick();expect(router.currentRoute.value.path).toBe('/settings');expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('离开前的草稿');
 const discard=router.push('/elsewhere');await tick();await click(root,'放弃草稿并离开');await discard;expect(router.currentRoute.value.path).toBe('/elsewhere');
});
const fixture=()=>({issuer:'https://stella.test',discovery_url:'https://stella.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.test/auth/oidc/authorize',token_endpoint:'https://stella.test/auth/oidc/token',userinfo_endpoint:'https://stella.test/auth/oidc/userinfo',jwks_uri:'https://stella.test/auth/oidc/jwks',clients:[{client_id:'immich',name:'私人相册',enabled:true,redirect_uris:['https://photos.test/auth/login'],has_secret:true,scopes:['openid','profile','email']}],capabilities:{}});
async function mount(){const root=document.createElement('div');document.body.append(root);app=createApp(AuthProviderSettings);app.mount(root);await tick();return root;}
async function click(root:HTMLElement,text:string){if(['保存变更','创建应用'].includes(text)&&![...root.querySelectorAll('button')].some(b=>b.textContent?.trim()===text)){await click(root,'预览变更');}const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,`button ${text}`).toBeDefined();expect(b!.disabled).toBe(false);b!.click();await tick();}
function input(root:HTMLElement,label:string,value:string){if(label==='回调地址'){const urls=value.split('\n').map(v=>new URL(v));input(root,'应用地址 1',urls[0]!.origin);input(root,'回调用途路径 1',urls.map(url=>url.pathname).join('\n'));return;}const el=root.querySelector<HTMLInputElement|HTMLTextAreaElement>(`[aria-label="${label}"]`)!;expect(el, label).not.toBeNull();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}
function backend(){
 const state=fixture();const writes:{path:string;method:string;body:any}[]=[];let failWrite=false,failRead=false;
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(!options?.method){if(failRead)throw Error('offline');return structuredClone(state);}
  const body=options.body?JSON.parse(String(options.body)):null;writes.push({path,method:options.method,body});if(failWrite)throw {status:422,detail:'回调地址未通过校验'};
  if(options.method==='POST'&&path==='/auth/provider/clients'){state.clients.push({...body,enabled:true,has_secret:true});return {client_id:body.client_id,client_secret:'one-time-secret'};}
  const id=decodeURIComponent(path.split('/')[4]!);const client=state.clients.find(c=>c.client_id===id)!;
  if(options.method==='PATCH')Object.assign(client,body);
  if(options.method==='DELETE')state.clients.splice(state.clients.indexOf(client),1);
  if(path.endsWith('/rotate-secret'))return {client_id:id,client_secret:'rotated-once'};
  return structuredClone(client);
 });
 return {state,writes,set failWrite(v:boolean){failWrite=v;},set failRead(v:boolean){failRead=v;}};
}
it('creates an app in one save with exact callbacks and shows secret once, never persisting it',async()=>{
 const b=backend(),root=await mount();await click(root,'连接应用');input(root,'应用名称','文档库');input(root,'Client ID','outline');input(root,'回调地址','https://notes.test/callback\nhttps://notes.test/another');await tick();
 await click(root,'创建应用');expect(b.writes).toEqual([{path:'/auth/provider/clients',method:'POST',body:{client_id:'outline',name:'文档库',redirect_uris:['https://notes.test/callback','https://notes.test/another'],scopes:['openid','profile','email']}}]);
 expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toBe('/auth/provider/config');expect(root.textContent).toContain('one-time-secret');expect(root.textContent).toContain('仅显示这一次');await click(root,'隐藏密钥');expect(root.textContent).not.toContain('one-time-secret');expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
});
it('edits callbacks in one PATCH, previews only changed fields and preserves drafts on validation failure',async()=>{
 const b=backend(),root=await mount();await click(root,'编辑');input(root,'应用名称','家庭相册');input(root,'回调地址','https://photos.test/new/callback');await tick();
 expect(root.querySelector('[aria-label="变更摘要"]')?.textContent).toContain('回调地址');expect(root.querySelector('[aria-label="变更摘要"]')?.textContent).not.toContain('授权范围');
 b.failWrite=true;await click(root,'保存变更');expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('家庭相册');expect(root.textContent).toContain('回调地址未通过校验');
 b.failWrite=false;await click(root,'保存变更');expect(b.writes.at(-1)).toEqual({path:'/auth/provider/clients/immich',method:'PATCH',body:{name:'家庭相册',redirect_uris:['https://photos.test/new/callback']}});expect(toasts.map(t=>t.text).join(' ')).toContain('变更已保存');expect(b.state.clients[0]?.redirect_uris).toEqual(['https://photos.test/new/callback']);
});
it('toggles enabled through explicit PATCH then verifies aggregate',async()=>{
 const b=backend(),root=await mount();await click(root,'停用');expect(b.writes[0]?.body.enabled).toBe(false);expect(b.writes[0]?.path).toBe('/auth/provider/clients/immich');expect(root.textContent).toContain('已停用');await click(root,'启用');expect(b.state.clients[0]?.enabled).toBe(true);
});
it('requires targeted rotation confirmation, shows new secret once and copies only on request',async()=>{
 const b=backend(),root=await mount();const copy=vi.fn().mockResolvedValue(undefined);Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copy}});
 await click(root,'轮换密钥');expect(b.writes).toHaveLength(0);const dialog=root.querySelector<HTMLElement>('[role="dialog"]')!;expect(dialog.textContent).toContain('私人相册');expect(dialog.textContent).toContain('immich');expect(dialog.textContent).toContain('旧密钥');
 await click(root,'确认轮换');expect(b.writes).toEqual([{path:'/auth/provider/clients/immich/rotate-secret',method:'POST',body:null}]);expect(root.textContent).toContain('rotated-once');expect(copy).not.toHaveBeenCalled();await click(root,'复制密钥');expect(copy).toHaveBeenCalledWith('rotated-once');await click(root,'隐藏密钥');expect(root.textContent).not.toContain('rotated-once');
});
it('deletes only after exact Client ID confirmation and reads absence back',async()=>{
 const b=backend(),root=await mount();await click(root,'删除');const dialog=root.querySelector('[role="dialog"]')!;expect(dialog.textContent).toContain('私人相册');expect(b.writes).toHaveLength(0);
 input(root,'输入 Client ID 确认删除','Immich');await tick();expect([...root.querySelectorAll('button')].find(b=>b.textContent==='确认删除')?.disabled).toBe(true);
 input(root,'输入 Client ID 确认删除','immich');await tick();await click(root,'确认删除');expect(b.writes).toEqual([{path:'/auth/provider/clients/immich',method:'DELETE',body:null}]);expect(b.state.clients).toHaveLength(0);expect(toasts.map(t=>t.text).join(' ')).toContain('应用已删除');
});
it('holds every mutation after failed readback and retries only GET without losing draft or one-time secret',async()=>{
 const b=backend(),root=await mount();await click(root,'连接应用');input(root,'应用名称','待回读');input(root,'Client ID','pending');input(root,'回调地址','https://app.test/callback');b.failRead=true;await click(root,'创建应用');
 expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('待回读');expect(root.querySelector('fieldset')?.disabled).toBe(true);expect(root.textContent).toContain('one-time-secret');expect(root.textContent).not.toContain('应用已创建');
 b.failRead=false;await click(root,'重试读取结果');expect(b.writes).toHaveLength(1);expect(toasts.map(t=>t.text).join(' ')).toContain('应用已创建');
});
it('reconciles uncertain creation without replay, explains unrecoverable secret and keeps config mismatch drafts',async()=>{
 const state=fixture();let posts=0;vi.mocked(api).mockImplementation(async(_path,options)=>{if(options?.method==='POST'){posts++;state.clients.push({...JSON.parse(String(options.body)),enabled:true,has_secret:true});throw Error('timeout');}return structuredClone(state);});
 const root=await mount();await click(root,'连接应用');input(root,'应用名称','未知结果');input(root,'Client ID','uncertain');input(root,'回调地址','https://app.test/callback');await click(root,'创建应用');expect(posts).toBe(1);expect(toasts.map(t=>t.text).join(' ')).toContain('应用已创建');expect(root.textContent).toContain('密钥未收到');expect(root.textContent).toContain('查看现有密钥');expect(root.textContent).not.toContain('请明确轮换');expect(root.textContent).not.toContain('undefined');
});
it('does not claim a mismatched PATCH readback was saved and permits explicit continued editing',async()=>{
 const state=fixture();vi.mocked(api).mockResolvedValue(state);const root=await mount();await click(root,'编辑');input(root,'应用名称','未写入的名称');await tick();await click(root,'保存变更');expect(root.textContent).not.toContain('变更已保存');expect(root.querySelector('fieldset')?.disabled).toBe(true);await click(root,'继续编辑，不重发');expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('未写入的名称');expect(root.querySelector('fieldset')?.disabled).toBe(false);
});
it('renders explicit management gate on denied config with retry, and distinguishes unavailable service',async()=>{
 vi.mocked(api).mockRejectedValue({status:403,detail:{code:'admin_elevation_required'}});const root=await mount();expect(root.textContent).toContain('当前会话无权读取认证配置（403）');expect(root.textContent).not.toContain('尚未连接应用');
 vi.mocked(api).mockResolvedValue(fixture());await click(root,'重试读取');expect(root.textContent).toContain('私人相册');
});
it('ordinary session sees explicit gate without prompting or requesting privileged config, then loads on unlock',async()=>{
 (isAdmin as any).value=false;vi.mocked(api).mockResolvedValue(fixture());const root=await mount();expect(api).not.toHaveBeenCalled();expect(root.textContent).toContain('请登录用户账号');expect(root.textContent).not.toContain('尚未连接应用');(isAdmin as any).value=true;await tick();expect(root.textContent).toContain('私人相册');
});
it('copies actual issuer and discovery, keeps secret presence masked, and reports clipboard errors in place',async()=>{
 const value={...fixture(),clients:[{...fixture().clients[0]!,client_secret:'must-never-render'}]};vi.mocked(api).mockResolvedValue(value);const root=await mount();const copy=vi.fn().mockResolvedValue(undefined);Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copy}});expect(root.textContent).not.toContain('must-never-render');await click(root,'复制 Issuer');expect(copy).toHaveBeenLastCalledWith(value.issuer);await click(root,'复制自动发现');expect(copy).toHaveBeenLastCalledWith(value.discovery_url);copy.mockRejectedValue(Error('denied'));await click(root,'复制 Issuer');expect(root.textContent).toContain('复制失败');
});
it('focuses exact delete confirmation, traps Tab, cancels with Escape and restores trigger focus',async()=>{
 backend();const root=await mount();const trigger=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()==='删除')!;trigger.focus();await click(root,'删除');const dialog=root.querySelector<HTMLElement>('[role="dialog"]')!;expect(document.activeElement?.getAttribute('aria-label')).toBe('输入 Client ID 确认删除');const first=dialog.querySelector<HTMLInputElement>('input')!;first.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(dialog.contains(document.activeElement)).toBe(true);dialog.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await tick();expect(document.activeElement).toBe(trigger);
});
it('supports existing Dropdown arrow navigation and Escape without submitting an edit',async()=>{
 const b=backend(),root=await mount();await click(root,'编辑');const trigger=root.querySelector<HTMLButtonElement>('.dd-btn')!;trigger.click();await tick();trigger.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));await tick();expect(document.activeElement?.classList.contains('dd-item')).toBe(true);document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await tick();expect(document.activeElement).toBe(trigger);expect(b.writes).toHaveLength(0);
});
it('clears visible secret and config immediately when management locks, retaining nonsecret failed drafts',async()=>{
 const b=backend(),root=await mount();await click(root,'轮换密钥');await click(root,'确认轮换');expect(root.textContent).toContain('rotated-once');(isAdmin as any).value=false;await tick();expect(root.textContent).not.toContain('rotated-once');expect(root.textContent).not.toContain('私人相册');expect(b.writes).toHaveLength(1);
});
it('does not restore one-time secrets from the retained Settings tab',async()=>{
 backend();const active=ref(true),root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(KeepAlive,{},()=>active.value?h(AuthProviderSettings):null)});app.mount(root);await tick();await click(root,'轮换密钥');await click(root,'确认轮换');expect(root.textContent).toContain('rotated-once');active.value=false;await tick();active.value=true;await tick();expect(root.textContent).not.toContain('rotated-once');
});
for(const lifecycle of ['management lock/unlock','KeepAlive deactivation/reactivation'] as const){
 it(`replaces a held initial config GET after ${lifecycle} without rendering the obsolete response`,async()=>{
  let releaseOld!:(value:unknown)=>void,releaseNew!:(value:unknown)=>void;
  vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{releaseOld=resolve;})).mockImplementationOnce(()=>new Promise(resolve=>{releaseNew=resolve;}));
  const active=ref(true),root=document.createElement('div');document.body.append(root);
  app=createApp({render:()=>h(KeepAlive,{},()=>active.value?h(AuthProviderSettings):null)});app.mount(root);await tick();
  expect(api).toHaveBeenCalledTimes(1);
  if(lifecycle==='management lock/unlock'){
   (isAdmin as any).value=false;await tick();expect(root.textContent).toContain('请登录用户账号');
   (isAdmin as any).value=true;await tick();
  }else{active.value=false;await tick();active.value=true;await tick();}
  // One flight at a time, but a newer access generation must not lose its read.
  expect(api).toHaveBeenCalledTimes(1);
  const obsolete=fixture();obsolete.clients[0]!.name='过期响应';releaseOld(obsolete);await tick();
  expect(root.textContent).not.toContain('过期响应');expect(root.textContent).not.toContain('私人相册');
  expect(api).toHaveBeenCalledTimes(2);expect(root.textContent).toContain('读取认证配置');
  releaseNew(fixture());await tick();
  expect(root.textContent).toContain('私人相册');expect(root.textContent).not.toContain('读取认证配置');
  expect([...root.querySelectorAll('button')].find(b=>b.textContent?.trim()==='编辑')?.disabled).toBe(false);
  expect(vi.mocked(api).mock.calls.map(([path,options])=>[path,options?.method])).toEqual([['/auth/provider/config',undefined],['/auth/provider/config',undefined]]);
 });
}
it('fences a held GET even when management locks and unlocks in the same render tick',async()=>{
 let release!:(value:unknown)=>void;
 vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;})).mockResolvedValue(fixture());
 const root=await mount();(isAdmin as any).value=false;(isAdmin as any).value=true;
 const obsolete=fixture();obsolete.clients[0]!.name='过期响应';release(obsolete);await tick();
 expect(root.textContent).not.toContain('过期响应');expect(root.textContent).toContain('私人相册');expect(api).toHaveBeenCalledTimes(2);
});
it('coalesces repeated access changes, ignores stale errors, and offers a GET-only retry when replacement fails',async()=>{
 let rejectOld!:(reason:unknown)=>void,rejectNew!:(reason:unknown)=>void;
 vi.mocked(api).mockImplementationOnce(()=>new Promise((_resolve,reject)=>{rejectOld=reject;})).mockImplementationOnce(()=>new Promise((_resolve,reject)=>{rejectNew=reject;})).mockResolvedValue(fixture());
 const root=await mount();
 for(let i=0;i<3;i++){(isAdmin as any).value=false;await tick();(isAdmin as any).value=true;await tick();}
 expect(api).toHaveBeenCalledTimes(1);rejectOld({status:403});await tick();
 expect(api).toHaveBeenCalledTimes(2);expect(root.textContent).not.toContain('需要管理验证');expect(root.querySelector('[role="alert"]')).toBeNull();
 rejectNew(Error('offline'));await tick();expect(root.textContent).toContain('认证配置读取失败');
 await click(root,'重试读取');expect(root.textContent).toContain('私人相册');expect(root.querySelector('[role="alert"]')).toBeNull();
 expect(vi.mocked(api).mock.calls.map(([path,options])=>[path,options?.method])).toEqual(Array.from({length:3},()=>['/auth/provider/config',undefined]));
});
it('does not drain a queued config reload while inactive, and resumes with a fresh GET on activation',async()=>{
 let release!:(value:unknown)=>void;
 vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;})).mockResolvedValue(fixture());
 const active=ref(true),root=document.createElement('div');document.body.append(root);
 app=createApp({render:()=>h(KeepAlive,{},()=>active.value?h(AuthProviderSettings):null)});app.mount(root);await tick();
 active.value=false;await tick();active.value=true;await tick();active.value=false;await tick();release(fixture());await tick();
 expect(api).toHaveBeenCalledTimes(1);expect(root.textContent).not.toContain('私人相册');
 active.value=true;await tick();expect(api).toHaveBeenCalledTimes(2);expect(root.textContent).toContain('私人相册');
});
it('does not drain an obsolete config reload after its owner unmounts',async()=>{
 let release!:(value:unknown)=>void;
 vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
 await mount();(isAdmin as any).value=false;await tick();(isAdmin as any).value=true;await tick();
 app!.unmount();app=undefined;release(fixture());await tick();expect(api).toHaveBeenCalledTimes(1);
});
it('rejects malformed Client ID without repairing it or submitting any write',async()=>{
 const b=backend(),root=await mount();await click(root,'连接应用');input(root,'应用名称','草稿');input(root,'Client ID',' bad id ');input(root,'回调地址','https://app.test/callback');await click(root,'预览变更');expect(b.writes).toHaveLength(0);expect(root.querySelector<HTMLInputElement>('[aria-label="Client ID"]')?.value).toBe(' bad id ');expect(root.textContent).toContain('Client ID 需以字母或数字开头');
});
it('never retains another app secret when an uncertain creation loses its own one-time response',async()=>{
 const state=fixture();vi.mocked(api).mockImplementation(async(path,options)=>{if(path.endsWith('/rotate-secret'))return {client_id:'immich',client_secret:'previous-app-secret'};if(options?.method==='POST'){state.clients.push({...JSON.parse(String(options.body)),enabled:true,has_secret:true});throw Error('timeout');}return structuredClone(state);});const root=await mount();await click(root,'轮换密钥');await click(root,'确认轮换');await click(root,'连接应用');input(root,'应用名称','另一应用');input(root,'Client ID','another');input(root,'回调地址','https://app.test/callback');await click(root,'创建应用');expect(root.textContent).not.toContain('previous-app-secret');expect(root.textContent).toContain('密钥未收到');
});
it('returns focus to rotation trigger after successful confirmation',async()=>{
 backend();const root=await mount();const trigger=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()==='轮换密钥')!;trigger.focus();await click(root,'轮换密钥');await click(root,'确认轮换');expect(document.activeElement).toBe(trigger);
});
it('explicitly reveals the existing secret without rotation or automatic copy and hides on request',async()=>{
 const b=backend();vi.mocked(api).mockImplementationOnce(async()=>fixture());
 const root=await mount(),copy=vi.fn().mockResolvedValue(undefined);
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copy}});
 expect(root.querySelector('.secret-panel')).toBeNull();expect(b.writes).toHaveLength(0);
 vi.mocked(api).mockResolvedValueOnce({client_id:'immich',client_secret:'synthetic-existing-value'});
 await click(root,'查看现有密钥');
 expect(vi.mocked(api).mock.calls.at(-1)).toEqual(['/auth/provider/clients/immich/reveal-secret',{method:'POST',cache:'no-store'}]);
 expect(root.querySelector('.secret-panel')?.textContent).toContain('现有密钥');
 expect(root.querySelector('.secret-panel code')?.textContent).toBe('synthetic-existing-value');expect(copy).not.toHaveBeenCalled();
 await click(root,'复制密钥');expect(copy).toHaveBeenCalledExactlyOnceWith('synthetic-existing-value');
 await click(root,'隐藏密钥');expect(root.querySelector('.secret-panel')).toBeNull();
 expect(localStorage.length).toBe(0);expect(sessionStorage.length).toBe(0);
});

for(const field of ['sessionGeneration','requestEpoch'] as const){
 it(`clears visible and held reveals across ${field} even if management stays allowed`,async()=>{
  backend();const root=await mount();
  vi.mocked(api).mockResolvedValueOnce({client_id:'immich',client_secret:'synthetic-existing-value'});
  await click(root,'查看现有密钥');expect(root.querySelector('.secret-panel')).not.toBeNull();
  auth[field]++;await tick();expect(root.querySelector('.secret-panel')).toBeNull();
  let release!:(value:any)=>void;
  vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await click(root,'查看现有密钥');auth[field]++;await tick();
  release({client_id:'immich',client_secret:'synthetic-stale-value'});await tick();
  expect(root.querySelector('.secret-panel')).toBeNull();
 });
}
it('clears a reveal when its confirmation closes instead of leaving an old credential in memory',async()=>{
 backend();const root=await mount();vi.mocked(api).mockResolvedValueOnce({client_id:'immich',client_secret:'synthetic-existing-value'});
 await click(root,'查看现有密钥');await click(root,'轮换密钥');await click(root,'取消');
 expect(root.querySelector('.secret-panel')).toBeNull();
});
it('clears the secret on real route leave even when the retained component instance survives',async()=>{
 backend();const root=document.createElement('div');document.body.append(root);
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',redirect:'/settings'},{path:'/settings',component:AuthProviderSettings},{path:'/elsewhere',component:{render:()=>h('p','Elsewhere')}}]});
 app=createApp({render:()=>h(RouterView as any,{},({Component}:any)=>h(KeepAlive,{},()=>h(Component)))});app.use(router);
 await router.push('/settings');await router.isReady();app.mount(root);await tick();
 vi.mocked(api).mockResolvedValueOnce({client_id:'immich',client_secret:'synthetic-existing-value'});
 await click(root,'查看现有密钥');await router.push('/elsewhere');await tick();await router.push('/settings');await tick();
 expect(root.querySelector('.secret-panel')).toBeNull();
});

for(const boundary of ['management lock','logout','session expiry'] as const){
 it(`clears visible and pending reveals on ${boundary}`,async()=>{
  backend();const root=await mount();
  const leave=()=>{if(boundary==='management lock')(isAdmin as any).value=false;else if(boundary==='logout')auth.sessionClosing=true;else auth.suspended=true;};
  const resume=()=>{(isAdmin as any).value=true;auth.sessionClosing=false;auth.suspended=false;};
  vi.mocked(api).mockResolvedValueOnce({client_id:'immich',client_secret:'synthetic-existing-value'});
  await click(root,'查看现有密钥');leave();await tick();expect(root.querySelector('.secret-panel')).toBeNull();
  resume();await tick();let release!:(value:any)=>void;
  vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  await click(root,'查看现有密钥');leave();await tick();resume();await tick();
  release({client_id:'immich',client_secret:'synthetic-stale-value'});await tick();
  expect(root.querySelector('.secret-panel')).toBeNull();
 });
}
it('failed reveal removes an earlier value without generating, rotating, or copying anything',async()=>{
 const b=backend(),root=await mount(),copy=vi.fn();Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copy}});
 vi.mocked(api).mockResolvedValueOnce({client_id:'immich',client_secret:'synthetic-existing-value'});await click(root,'查看现有密钥');
 vi.mocked(api).mockRejectedValueOnce({status:403});await click(root,'查看现有密钥');
 expect(root.querySelector('.secret-panel')).toBeNull();expect(root.textContent).toContain('未生成或轮换密钥');expect(b.writes).toHaveLength(0);expect(copy).not.toHaveBeenCalled();
});
it('does not request or generate a secret for an app without an existing value',async()=>{
 const b=backend();b.state.clients[0]!.has_secret=false;const root=await mount();
 const button=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()==='查看现有密钥')!;
 expect(button.disabled).toBe(true);button.click();await tick();expect(api).toHaveBeenCalledTimes(1);expect(b.writes).toHaveLength(0);
});
it('elevated session reads compact provider overview and connected clients without invented activity or secrets',async()=>{
 vi.mocked(api).mockResolvedValue(fixture());const root=await mount();
 expect(vi.mocked(api).mock.calls.map(c=>c[0])).toEqual(['/auth/provider/config']);
 expect(root.textContent).toContain('https://stella.test');expect(root.textContent).toContain('私人相册');expect(root.textContent).toContain('immich');expect(root.textContent).toContain('已启用');expect(root.textContent).toContain('https://photos.test/auth/login');
 expect(root.textContent).toContain('已设置');expect(root.textContent).not.toMatch(/最近使用|上次使用|Authentik/);expect(root.querySelector('iframe, select')).toBeNull();expect(root.querySelector('details')?.open).toBe(false);
});
