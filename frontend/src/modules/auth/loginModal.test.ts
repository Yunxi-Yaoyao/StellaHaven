import {it,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import {createPinia} from 'pinia';
import App from '../../App.vue';
import LoginPage from './LoginPage.vue';
import {auth} from '../home/auth';

it('network login failure is visible and leaves the modal retryable',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input)=>{if(input==='/auth/status')return new Response('{"initialized":true}');throw new Error('fixture offline');}));
 const host=document.createElement('div');document.body.append(host);const app=createApp(LoginPage);app.config.errorHandler=()=>{};app.mount(host);
 await new Promise(r=>setTimeout(r,20));(host.querySelector('.submit') as HTMLElement).click();await new Promise(r=>setTimeout(r,20));
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('连接失败');
 expect((host.querySelector('.submit') as HTMLButtonElement).disabled).toBe(false);
 app.unmount();host.remove();vi.unstubAllGlobals();
});
it('opens login over the current public page without navigation and traps focus',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input)=>new Response(JSON.stringify(String(input)==='/auth/status'?{initialized:true,email_enabled:false}:String(input).includes('site-background')?{value:''}:[]),{status:200})));
 Object.assign(auth,{me:null,checked:true,error:'',sessionClosing:false});
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',name:'home',component:{template:'<button id="public-content">Public page</button>'},meta:{public:true}},...['/notes','/status','/settings'].map(path=>({path,component:{render:()=>null}}))]});
 await router.push('/');const host=document.createElement('div');document.body.append(host);
 const app=createApp(App).use(createPinia()).use(router);app.mount(host);
 (host.querySelector('.account') as HTMLElement).click();
 for(let n=0;n<12;n++){await new Promise(r=>setTimeout(r,10));await nextTick();}
 expect(router.currentRoute.value.fullPath).toBe('/');
 expect(document.querySelector('[role="dialog"][aria-modal="true"]')).not.toBeNull();
 expect(host.querySelector('.shell')?.hasAttribute('inert')).toBe(true);
 expect(document.querySelector('[role="dialog"]')?.contains(document.activeElement)).toBe(true);
 app.unmount();host.remove();vi.unstubAllGlobals();
});
