import {createApp,nextTick,type App} from 'vue';
import {afterEach,expect,it,vi} from 'vitest';
import LoginPage from './LoginPage.vue';
import {login,register} from '../home/auth';
import {loginStatus} from './loginStatus';
import {getBrowserId} from './browserId';
let app:App|undefined;
afterEach(()=>{app?.unmount();document.body.innerHTML='';vi.unstubAllGlobals();});
it('includes the same browser UUID in password and initial registration requests',async()=>{
 const fetch=vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'fixture'})});vi.stubGlobal('fetch',fetch);
 await login('fixture','fixture',false);await register('fixture','fixture');
 for(const call of fetch.mock.calls){const body=JSON.parse(call[1].body);expect(body.browser_id).toBe(getBrowserId());expect(body.entry_origin).toBe(window.location.origin);}
});
it('adds browser UUID only on code verification, not on unauthenticated status/metadata probes',async()=>{
 const calls:{path:string;body:any}[]=[];vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{calls.push({path,body:init?.body?JSON.parse(String(init.body)):null});return {ok:true,json:async()=>path==='/auth/status'?{initialized:true,email_enabled:true}:{id:'fixture',username:'fixture'}};}));
 loginStatus.initialized=true;loginStatus.emailEnabled=true;const root=document.createElement('div');document.body.append(root);app=createApp(LoginPage);app.mount(root);await nextTick();
 const click=async(text:string)=>{[...root.querySelectorAll<HTMLElement>('button,a')].find(b=>b.textContent?.trim()===text)!.click();await new Promise(r=>setTimeout(r,0));await nextTick();};
 const fill=(selector:string,value:string)=>{const el=root.querySelector<HTMLInputElement>(selector)!;el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));};
 await click('验证码登录');fill('input[placeholder="你验证过的邮箱"]','fixture@example.test');await click('发送登录码');fill('input[placeholder="6 位数字"]','123456');await nextTick();await click('进港');
 expect(calls.find(c=>c.path==='/auth/login-code')?.body.entry_origin).toBe(window.location.origin);
 expect(calls.find(c=>c.path==='/auth/login-code')?.body.browser_id).toBe(getBrowserId());expect(calls.filter(c=>c.path.includes('metadata'))).toEqual([]);
});
