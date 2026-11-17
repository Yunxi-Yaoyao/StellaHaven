import {it,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import {createPinia} from 'pinia';
import App from '../../App.vue';
import {auth} from '../home/auth';
import {loginPrompt} from './loginPrompt';
import LoginPage from './LoginPage.vue';
import {loginStatus} from './loginStatus';

it('successful initialization invalidates the cached uninitialized guide before reopening',async()=>{
 loginStatus.initialized=false;
 vi.stubGlobal('fetch',vi.fn(async(input)=>new Response(JSON.stringify(String(input)==='/auth/status'?{initialized:false,email_enabled:false}:{id:'fixture-owner',username:'fixture',display_name:'Fixture',home_bg:''}))));
 const host=document.createElement('div');document.body.append(host);const app=createApp(LoginPage);app.mount(host);
 try {
  (host.querySelector('.submit') as HTMLElement).click();await nextTick();
  (host.querySelector('.submit') as HTMLElement).click();await new Promise(r=>setTimeout(r,30));
  expect(loginStatus.initialized).toBe(true);
 } finally {app.unmount();host.remove();vi.unstubAllGlobals();Object.assign(auth,{me:null,sessionClosing:false,suspended:false});loginStatus.initialized=null;}
});

it('real App renders complete login immediately while status is unresolved, without replacing typed inputs',async()=>{
 let resolveStatus!:(response:Response)=>void;
 const pending=new Promise<Response>(resolve=>{resolveStatus=resolve;});
 vi.stubGlobal('fetch',vi.fn(async(input)=>String(input)==='/auth/status'?pending:new Response(JSON.stringify([]))));
 Object.assign(auth,{me:null,checked:true,suspended:false,sessionClosing:false});loginPrompt.requested=false;
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',name:'home',component:{template:'<button>Public page</button>'},meta:{public:true}},...['/notes','/status','/settings'].map(path=>({path,component:{render:()=>null}}))]});
 await router.push('/');const host=document.createElement('div');document.body.append(host);
 const app=createApp(App).use(createPinia()).use(router);app.mount(host);
 try {
  (host.querySelector('.account') as HTMLElement).click();await nextTick();
  const dialog=document.querySelector('[role="dialog"]');
  expect(dialog?.textContent).toContain('欢迎回港');
  const input=dialog?.querySelector('input[autocomplete="username"]') as HTMLInputElement;
  input.value='typed-before-status';input.dispatchEvent(new Event('input',{bubbles:true}));
  resolveStatus(new Response(JSON.stringify({initialized:false,email_enabled:true})));
  await new Promise(resolve=>setTimeout(resolve,30));await nextTick();
  expect(document.querySelector('input[autocomplete="username"]')).toBe(input);
  expect(input.value).toBe('typed-before-status');
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('开始初始化');
 } finally {app.unmount();host.remove();vi.unstubAllGlobals();loginPrompt.requested=false;}
});
