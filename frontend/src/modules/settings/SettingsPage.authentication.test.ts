import {createApp,nextTick,h,KeepAlive,type App} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import {it,expect,vi,afterEach} from 'vitest';
vi.mock('./AvatarCropper.vue',()=>({default:{template:'<div />'}}));
vi.mock('./NavigationSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../../shell/SettingsPanel.vue',()=>({default:{template:'<div />'}}));
vi.mock('./PerformanceSettings.vue',()=>({default:{template:'<div>性能</div>'}}));
vi.mock('./SecuritySettings.vue',()=>({default:{template:'<div>管理保护</div>'}}));
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'owner',display_name:'云曦',username:'owner'}}),isAdmin:ref(true),currentAvatar:ref(''),logout:vi.fn()};});
vi.mock('../../api/client',()=>({api:vi.fn().mockResolvedValue({issuer:'https://stella.test',discovery_url:'https://stella.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.test/auth/oidc/authorize',token_endpoint:'https://stella.test/auth/oidc/token',userinfo_endpoint:'https://stella.test/auth/oidc/userinfo',jwks_uri:'https://stella.test/auth/oidc/jwks',clients:[],capabilities:{}})}));
vi.mock('../../api/servers',()=>({getPublicHost:vi.fn().mockResolvedValue({value:''}),setPublicHost:vi.fn()}));
import SettingsPage from './SettingsPage.vue';
let app:App|undefined;
afterEach(()=>{app?.unmount();document.body.innerHTML='';vi.unstubAllGlobals();});
async function mount(section:string){
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>[]}));
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage}]});
 await router.push('/settings?section='+section);await router.isReady();const root=document.createElement('div');document.body.append(root);app=createApp(SettingsPage);app.use(router);app.mount(root);await new Promise(r=>setTimeout(r,0));await nextTick();return {root,router};
}
it('keeps unsaved application drafts when moving between native Settings sections',async()=>{
 const {root,router}=await mount('authentication');
 [...root.querySelectorAll<HTMLButtonElement>('button,a')].find(b=>b.textContent?.trim()==='连接应用')!.click();await nextTick();const name=root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')!;name.value='保留的应用草稿';name.dispatchEvent(new Event('input',{bubbles:true}));
 await router.replace('/settings?section=profile');await new Promise(r=>setTimeout(r,0));
 await router.replace('/settings?section=authentication');await new Promise(r=>setTimeout(r,0));expect(root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')?.value).toBe('保留的应用草稿');
});
it.each(['/settings?section=appearance','/settings?section=servers','/settings?tab=servers'])('uses the real callback discard dialog exactly once for %s and retained route reactivation',async destination=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>[]}));
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage},{path:'/elsewhere',component:{template:'<p>Elsewhere</p>'}}]});
 await router.push('/settings?section=authentication');await router.isReady();const root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(RouterView,{}, {default:({Component}:any)=>h(KeepAlive,{},()=>h(Component))})});app.use(router);app.mount(root);
 const tick=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};await tick();
 const click=async(text:string)=>{[...root.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===text)!.click();await tick();};
 await click('连接应用');const name=root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')!;name.value='必须保留';name.dispatchEvent(new Event('input',{bubbles:true}));await tick();
 const rejected=router.replace(destination);await tick();expect(root.querySelectorAll('[role="alertdialog"]')).toHaveLength(1);await click('继续编辑');await rejected;expect(router.currentRoute.value.query.section).toBe('authentication');expect(name.value).toBe('必须保留');
 const discard=router.replace('/settings?section=appearance');await tick();await click('放弃草稿并离开');await discard;await new Promise(r=>setTimeout(r,300));await router.replace('/settings?section=authentication');await tick();expect(root.querySelector('[aria-label="应用名称"]')).toBeNull();
 await router.push('/elsewhere');await router.push('/settings?section=authentication');await tick();await click('连接应用');const retained=root.querySelector<HTMLInputElement>('[aria-label="应用名称"]')!;retained.value='重新激活的草稿';retained.dispatchEvent(new Event('input',{bubbles:true}));await tick();
 const leaving=router.push('/elsewhere');await tick();expect(root.querySelectorAll('[role="alertdialog"]')).toHaveLength(1);await click('继续编辑');await leaving;expect(router.currentRoute.value.path).toBe('/settings');expect(retained.value).toBe('重新激活的草稿');
});
it('opens native authentication section directly with security and session controls, not an iframe',async()=>{
 const {root,router}=await mount('authentication');
 expect(root.textContent).toContain('账号与登录');expect(root.textContent).not.toContain('管理保护');expect(root.textContent).toContain('登录记录');expect(root.textContent).toContain('Stella 单点登录');expect(root.querySelector('iframe')).toBeNull();
 expect([...root.querySelectorAll<HTMLButtonElement>('button,a')].filter(b=>b.textContent==='修改密码')).toHaveLength(1);
 await router.replace('/settings?section=profile');await new Promise(r=>setTimeout(r,0));expect(router.currentRoute.value.query.section).toBe('profile');expect(root.textContent).toContain('登录记录');expect(root.textContent).not.toContain('管理保护');
});
