import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, nextTick, type App } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import SideBar from './SideBar.vue';
import { auth, fetchMe } from '../modules/home/auth';
import { api } from '../api/client';
import { loadNavigation, navigation, resetNavigation } from '../stores/navigation';
vi.mock('./NotificationBell.vue',()=>({default:{render:()=>null}}));
vi.mock('./Icon.vue',()=>({default:{render:()=>null}}));
vi.mock('../api/client',()=>({api:vi.fn()}));
let app:App,host:HTMLDivElement;
const owner={id:'owner',username:'test',display_name:'test',is_admin:false,avatar_url:'',home_bg:'',email:'',email_verified:true};
// Literal owning expectation, not copied from resolveNavigation/builtinNavigation.
const completeMenu=[['个人主页','/'],['导航','/nav'],['笔记','/notes'],['服务器','/status'],['设置','/settings']];
const snapshot=()=>({entries:[{id:'home',title:'个人主页',icon:'home',visible:true},{id:'nav',title:'导航',icon:'compass',visible:true},{id:'notes',title:'笔记',icon:'note',visible:true},{id:'status',title:'服务器',icon:'server',visible:true},{id:'settings',title:'设置',icon:'settings',visible:true}],modules:[],legacy_routes:{},revision:1,mutation_id:null});
async function mount(){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});await router.push('/');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp(SideBar,{collapsed:false,mobileOpen:false}).use(router);app.mount(host);await nextTick();
}
const links=()=>Array.from(host.querySelectorAll('.nav-item')).map(el=>[el.textContent?.trim(),el.getAttribute('href')]);
beforeEach(()=>{resetNavigation();Object.assign(auth,{me:null,checked:false,sessionClosing:false,error:''});vi.mocked(api).mockReset();});
afterEach(()=>{app?.unmount();host?.remove();resetNavigation();vi.unstubAllGlobals();});
it.each(['unavailable','refresh-unavailable','offline'])('does not mistake %s identity for a confirmed guest and retries authentication',async(kind)=>{
 let calls=0;const fetch=vi.fn().mockImplementation(()=>{calls++;if(kind==='offline')return Promise.reject(new Error('offline'));return Promise.resolve(new Response('{}',{status:kind==='refresh-unavailable'&&calls===1?401:503}));});vi.stubGlobal('fetch',fetch);
 await fetchMe();await mount();expect(links()).toEqual([]);expect(host.querySelector('[role=alert]')?.textContent).toContain('重试');
 fetch.mockResolvedValue(new Response(JSON.stringify({...owner,home_bg:'https://example.test/bg.jpg'})));vi.mocked(api).mockResolvedValueOnce(snapshot());
 (host.querySelector('.nav button') as HTMLButtonElement).click();for(let i=0;i<40;i++)await Promise.resolve();await nextTick();
 expect(auth.me?.id).toBe(owner.id);expect(links()).toEqual(completeMenu);
});
it('renders guest navigation only after a confirmed unauthenticated response',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{}',{status:401})));await fetchMe();await mount();expect(links()).toEqual(completeMenu);
});
it('shows only noninteractive loading until identity and the complete navigation snapshot ACK arrive',async()=>{
 await mount();expect(links()).toEqual([]);expect(host.querySelector('[role=status]')).not.toBeNull();
 auth.me=owner;auth.checked=true;await nextTick();expect(links()).toEqual([]);
 let finishSnapshot!:(v:unknown)=>void;
 vi.mocked(api).mockImplementation(path=>{if(path!=='/navigation')throw new Error('Unexpected API '+path);return new Promise(resolve=>{finishSnapshot=resolve;});});
 const pending=loadNavigation();await nextTick();expect(links()).toEqual([]);expect(host.querySelector('[role=status]')).not.toBeNull();
 const config=snapshot();config.entries=[{id:'home',title:'首页',icon:'home',visible:true},{id:'website',title:'网站',icon:'globe',visible:true},...config.entries.slice(1).map(e=>e.id==='notes'?{...e,visible:false}:e)];
 finishSnapshot({...config,modules:[{id:'website',name:'网站',icon:'globe',mode:'iframe',adapter:'generic',browser_url:'https://fixture.test/',enabled:true,runtime_revision:'opaque-website-v1'}]});await pending;await nextTick();
 expect(vi.mocked(api).mock.calls.map(([path])=>path)).toEqual(['/navigation']);
 const configuredMenu=[['首页','/'],['网站','/apps/website'],['导航','/nav'],['服务器','/status'],['设置','/settings']];
 expect(links()).toEqual(configuredMenu);
 auth.me={...owner};await nextTick();expect(links()).toEqual(configuredMenu);
});
it('offers retry without exposing a partial menu, and keeps a complete snapshot on refresh failure',async()=>{
 auth.me=owner;auth.checked=true;vi.mocked(api).mockRejectedValue(new Error('offline'));await loadNavigation();await mount();
 expect(links()).toEqual([]);expect(host.querySelector('[role=alert]')?.textContent).toContain('重试');
 vi.mocked(api).mockResolvedValueOnce(snapshot());
 (host.querySelector('.nav button') as HTMLButtonElement).click();for(let i=0;i<10;i++)await Promise.resolve();await nextTick();
 expect(navigation.loaded).toBe(true);expect(links()).toEqual(completeMenu);
 vi.mocked(api).mockRejectedValue(new Error('offline'));await loadNavigation({force:true});await nextTick();
 expect(links()).toEqual(completeMenu);expect(host.querySelector('[role=alert]')).not.toBeNull();
 auth.sessionClosing=true;await nextTick();expect(links()).toEqual([]);
});
