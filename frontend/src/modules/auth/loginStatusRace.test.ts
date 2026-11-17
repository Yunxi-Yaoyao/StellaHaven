import {it,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import LoginPage from './LoginPage.vue';
import {loginStatus,refreshLoginStatus} from './loginStatus';

it('expired false cache refreshes the mounted initialization guide to password login',async()=>{
 let release!:(value:Response)=>void;
 loginStatus.initialized=false;
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>release=resolve)));
 const host=document.createElement('div');document.body.append(host);const app=createApp(LoginPage);app.mount(host);
 try {
  expect(host.textContent).toContain('港湾还没有主人哦');
  release(new Response(JSON.stringify({initialized:true,email_enabled:true})));
  await refreshLoginStatus();await nextTick();
  expect(host.textContent).toContain('欢迎回港');
  expect(host.querySelector('input[autocomplete="username"]')).not.toBeNull();
  // Later refreshes reconcile both directions without waiting for a remount.
  loginStatus.initialized=false;await nextTick();expect(host.textContent).toContain('开始初始化');
  loginStatus.initialized=true;await nextTick();expect(host.textContent).toContain('欢迎回港');
 } finally {app.unmount();host.remove();vi.unstubAllGlobals();}
});

it('capability updates preserve typed password, explicit initialization and email phases',async()=>{
 loginStatus.initialized=true;loginStatus.emailEnabled=true;
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:503})));
 const host=document.createElement('div');document.body.append(host);const app=createApp(LoginPage);app.mount(host);
 try {
  const password=host.querySelector('input[type="password"]') as HTMLInputElement;
  password.value='fixture-draft';password.dispatchEvent(new Event('input',{bubbles:true}));
  loginStatus.initialized=false;await nextTick();expect(host.querySelector('input[type="password"]')).toBe(password);expect(password.value).toBe('fixture-draft');
  (host.querySelector('.init-link') as HTMLElement).click();await nextTick();
  loginStatus.initialized=true;await nextTick();expect(host.textContent).toContain('创建唯一账号');expect((host.querySelector('input[type="password"]') as HTMLInputElement).value).toBe('fixture-draft');
 } finally {app.unmount();host.remove();vi.unstubAllGlobals();}
 const emailHost=document.createElement('div');document.body.append(emailHost);const emailApp=createApp(LoginPage);emailApp.mount(emailHost);
 try {
  (Array.from(emailHost.querySelectorAll('.forgot')).find(el=>el.textContent==='忘记密码？') as HTMLElement).click();await nextTick();
  loginStatus.initialized=false;await nextTick();expect(emailHost.textContent).toContain('发送重置码');
  loginStatus.initialized=true;await nextTick();expect(emailHost.textContent).toContain('发送重置码');
 } finally {emailApp.unmount();emailHost.remove();vi.unstubAllGlobals();}
});

it('successful login fences a late uninitialized public response',async()=>{
 vi.resetModules();const status=await import('./loginStatus');
 let release!:(value:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>release=resolve)));
 try {
  const pending=status.refreshLoginStatus();status.confirmLoginInitialized();
  release(new Response(JSON.stringify({initialized:false,email_enabled:true})));await pending;
  expect(status.loginStatus.initialized).toBe(true);expect(status.loginStatus.emailEnabled).toBe(false);
 } finally {vi.unstubAllGlobals();}
});
