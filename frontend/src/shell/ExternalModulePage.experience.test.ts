import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, reactive, type App } from 'vue';
import ExternalModulePage from './ExternalModulePage.vue';
import { auth } from '../modules/home/auth';
import { navigation, resetNavigation, type Website, type WebsiteSummary } from '../stores/navigation';
import { getWebsite, launchWebsite } from '../api/integrations';
import {checkWebsiteDraft} from '../api/websiteSettings';
vi.mock('../api/integrations',async importOriginal=>({...await importOriginal<typeof import('../api/integrations')>(),getWebsite:vi.fn(),launchWebsite:vi.fn()}));
vi.mock('../api/websiteSettings',()=>({checkWebsiteDraft:vi.fn().mockResolvedValue({embedding:{status:'allowed'}})}));
const id='synthetic-website';
let app:App,host:HTMLDivElement;
const props=reactive({id,active:true});
const module=():Website=>({id,name:'测试网站',icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:'https://child.test/',origin:'https://child.test',enabled:true,keep_alive:true,background:'solid'});
function summary(item:Website):WebsiteSummary & {background?:Website['background'];runtime_revision:string}{
 const {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id,background}=item;
 return {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id,background,runtime_revision:'opaque-runtime-v1'};
}
async function flush(){for(let i=0;i<25;i++)await Promise.resolve();await nextTick();}
async function mount(item=module()){
 navigation.modules=[summary(item)];navigation.loaded=true;
 vi.mocked(getWebsite).mockResolvedValue(item);vi.mocked(launchWebsite).mockResolvedValue({mode:item.mode,url:'https://child.test/',method:'GET'});
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(ExternalModulePage,props)});app.component('RouterLink',{render(){return null;}});app.mount(host);await flush();
}
beforeEach(()=>{
 localStorage.clear();resetNavigation();vi.clearAllMocks();props.id=id;props.active=true;
 Object.assign(auth,{me:{id:'owner',home_bg:'https://media.test/pattern.jpg'},sessionGeneration:0,sessionClosing:false});
});
afterEach(()=>{app?.unmount();host?.remove();resetNavigation();vi.useRealTimers();});
it.each([
 ['image',null,'home'],['solid','image','solid'],[null,'image','home'],['invalid','image','home'],[null,null,'solid'],['invalid','invalid','solid'],
])('resolves legacy device background (%s, %s) only through the live alias',async(current,legacy,expected)=>{
 if(current)localStorage.setItem('stella_drive_bg_mode',current);if(legacy)localStorage.setItem('__stella_drive_bg_mode__',legacy);
 navigation.legacy_routes={drive:id};await mount();
 expect(host.querySelector('.external-page')?.classList.contains('home-background')).toBe(expected==='home');
 if(expected==='home')expect((host.querySelector('.external-page') as HTMLElement).style.backgroundImage).toContain('pattern.jpg');
 expect(localStorage.getItem('stella_drive_bg_mode')).toBe(current);
});
it('fetches current full detail once and updates background on the retained frame',async()=>{
 await mount();expect(getWebsite).toHaveBeenCalledTimes(1);expect(launchWebsite).toHaveBeenCalledTimes(1);
 expect(navigation.modules[0]).not.toHaveProperty('injection');expect(navigation.modules[0]).not.toHaveProperty('origin');
 const frame=host.querySelector('iframe');navigation.modules=[summary({...module(),background:'home'})];await flush();
 expect(host.querySelector('.home-background')).not.toBeNull();expect(host.querySelector('iframe')).toBe(frame);
 props.active=false;await flush();auth.me={...auth.me!};props.active=true;await flush();
 expect(host.querySelector('iframe')).toBe(frame);expect(launchWebsite).toHaveBeenCalledTimes(1);
 auth.me!.home_bg='https://media.test/scene.webm?version=2#clip';await flush();
 const video=host.querySelector('video');expect(video?.getAttribute('src')).toContain('scene.webm');expect(video?.autoplay).toBe(true);expect(video?.muted).toBe(true);
 props.active=false;await flush();expect(host.querySelector('video')).toBeNull();
 props.active=true;await flush();expect(host.querySelector('video')).not.toBeNull();
});
it('does not launch from a summary while the full detail is pending',async()=>{
 let finish!:(value:Website)=>void;vi.mocked(getWebsite).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await mount(readyModule());expect(getWebsite).toHaveBeenCalledTimes(1);expect(navigation.modules[0]).not.toHaveProperty('injection');
 expect(launchWebsite).not.toHaveBeenCalled();expect(host.querySelector('iframe')).toBeNull();expect(host.querySelector('[role=status]')?.textContent).toContain('正在读取');
 finish(readyModule());await flush();expect(launchWebsite).toHaveBeenCalledTimes(1);expect(host.querySelector('iframe')).not.toBeNull();
 const frame=host.querySelector('iframe')!,post=vi.spyOn(frame.contentWindow!,'postMessage');message(frame,{type:'stella-bg-request'});await flush();
 expect(post.mock.calls.at(-1)?.[0]).toMatchObject({type:'stella-bg-mode',mode:'image',module_id:id});
});
it('retains the owned detail background when an optional summary background is absent',async()=>{
 await mount(readyModule());const frame=host.querySelector('iframe');const withoutBackground=summary(readyModule());delete withoutBackground.background;
 navigation.modules=[withoutBackground];await flush();
 expect(host.querySelector('.home-background')).not.toBeNull();expect(host.querySelector('iframe')).toBe(frame);expect(getWebsite).toHaveBeenCalledTimes(1);expect(launchWebsite).toHaveBeenCalledTimes(1);
});
it('keeps a cancelled pending launch paused until an explicit reconnect',async()=>{
 let resolve!:(value:any)=>void;vi.mocked(launchWebsite).mockImplementationOnce(()=>new Promise(yes=>{resolve=yes;}));
 await mount();props.active=false;await flush();resolve({mode:'isolated_proxy',method:'GET',url:'https://child.test/late'});await flush();expect(host.querySelector('iframe')).toBeNull();
 props.active=true;await flush();expect(launchWebsite).toHaveBeenCalledTimes(1);
 (host.querySelector('.recovery-actions button') as HTMLButtonElement).click();await flush();expect(launchWebsite).toHaveBeenCalledTimes(2);expect(host.querySelector('iframe')?.getAttribute('src')).toBe('https://child.test/');
});
it.each(['iframe','link'] as const)('keeps %s recovery inside Stella without silently converting a legacy link',async mode=>{
 vi.useFakeTimers();await mount({...readyModule(),mode});
 if(mode==='iframe'){host.querySelector('iframe')!.dispatchEvent(new Event('load'));await vi.advanceTimersByTimeAsync(20000);await flush();expect(host.querySelector('.connection-notice')).not.toBeNull();}
 expect(host.querySelector('a[target="_blank"]')).toBeNull();
 expect(host.textContent).not.toContain('新窗口');
 expect(navigation.modules[0]?.mode).toBe(mode);
 if(mode==='link'){
  expect(host.querySelector('iframe')).toBeNull();
  expect(host.querySelector('.connection-notice')?.textContent).toContain('连接设置');
 }
});
const readyModule=():Website=>({...module(),background:'home',injection:{active:{enabled:true,js:'/* stella:background-ready:v1 */',css:'',timing:'dom_ready',csp_policy:'reject',version:'v1'},draft:null,previous:null}});
function message(frame:HTMLIFrameElement,data:unknown,origin='https://child.test',source:Window|null=frame.contentWindow){window.dispatchEvent(new MessageEvent('message',{data,origin,source}));}
it('shows an opted-in home iframe before style-ready ACK',async()=>{
 await mount(readyModule());const frame=host.querySelector('iframe')!;
 expect(getComputedStyle(frame).visibility).toBe('visible');
 const post=vi.spyOn(frame.contentWindow!,'postMessage');frame.dispatchEvent(new Event('load'));await flush();
 expect(getComputedStyle(frame).visibility).toBe('visible');
 message(frame,{type:'stella-bg-request'});await flush();const [request,origin]=post.mock.calls.at(-1)!;
 expect(origin).toBe('https://child.test');expect(request).toMatchObject({type:'stella-bg-mode',module_id:id,mode:'image',request_id:expect.any(String)});
 const ack={...request,type:'stella-bg-ready'};
 for(const invalid of [{...ack,module_id:'wrong'},{...ack,request_id:'old'},{...ack,mode:'solid'}]){message(frame,invalid);await flush();expect(getComputedStyle(frame).visibility).toBe('visible');}
 message(frame,ack,'https://evil.test');message(frame,ack,'https://child.test',window);await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
 message(frame,ack);await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
 navigation.modules=[summary({...readyModule(),background:'solid'})];await flush();expect(post.mock.calls.at(-1)?.[0]).toMatchObject({mode:'solid'});
 navigation.modules=[summary(readyModule())];await flush();const fresh=post.mock.calls.at(-1)?.[0];expect(fresh.request_id).not.toBe(request.request_id);
 message(frame,ack);await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
 message(frame,{...fresh,type:'stella-bg-ready'});await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
});
it('sends the actual host canvas scheme without changing the selected theme',async()=>{
 const previous=document.documentElement.style.colorScheme;
 try{
  document.documentElement.style.colorScheme='dark';await mount(readyModule());const frame=host.querySelector('iframe')!;
  const post=vi.spyOn(frame.contentWindow!,'postMessage');message(frame,{type:'stella-bg-request'});await flush();
  expect(post.mock.calls.at(-1)?.[0]).toMatchObject({type:'stella-bg-mode',color_scheme:'dark'});
  expect(document.documentElement.style.colorScheme).toBe('dark');
  document.documentElement.style.colorScheme='normal';message(frame,{type:'stella-bg-request'});await flush();
  expect(post.mock.calls.at(-1)?.[0]).toMatchObject({color_scheme:'normal'});
 }finally{document.documentElement.style.colorScheme=previous;}
});
it('bounds missing style ACK without hiding the directory or relaunching content',async()=>{
 vi.useFakeTimers();await mount(readyModule());const frame=host.querySelector('iframe')!;frame.dispatchEvent(new Event('load'));await flush();
 await vi.advanceTimersByTimeAsync(20000);expect(host.querySelector('[role=alert]')?.textContent).toContain('背景');expect(getComputedStyle(frame).visibility).toBe('visible');
 const reconnect=host.querySelector('.recovery-actions button') as HTMLButtonElement;expect(reconnect.disabled).toBe(false);expect(reconnect.textContent).toContain('重试外观');reconnect.click();await flush();expect(launchWebsite).toHaveBeenCalledTimes(1);expect(host.querySelector('iframe')).toBe(frame);
});
it.each(['missing','disabled'])('leaves a %s readiness template native and never gates on template_id',async(kind)=>{
 const item=readyModule();item.template_id='openlist';if(kind==='missing')item.injection!.active!.js='';else item.injection!.active!.enabled=false;
 await mount(item);expect(getComputedStyle(host.querySelector('iframe')!).visibility).not.toBe('hidden');
});
it('binds a registered private launch and postMessage to its returned target, not the stored public origin',async()=>{
 const submit=vi.spyOn(HTMLFormElement.prototype,'submit').mockImplementation(()=>{});
 vi.mocked(launchWebsite).mockResolvedValueOnce({mode:'isolated_proxy',method:'POST',url:'https://child.p.test/__stella/bootstrap',fields:{ticket:'synthetic'},source_origin:location.origin,target_origin:'https://child.p.test'});
 try{
  await mount(readyModule());expect(submit).toHaveBeenCalledOnce();
  const frame=host.querySelector('iframe')!;expect(frame).not.toBeNull();
  const post=vi.spyOn(frame.contentWindow!,'postMessage');frame.dispatchEvent(new Event('load'));await flush();
  const [request,target]=post.mock.calls.at(-1)!;expect(target).toBe('https://child.p.test');
  message(frame,{...request,type:'stella-bg-ready'});await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
  message(frame,{...request,type:'stella-bg-ready'},'https://child.p.test');await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
 }finally{submit.mockRestore();}
});
it('uses a direct private launch origin for the background handshake rather than its stored public URL',async()=>{
 vi.mocked(launchWebsite).mockResolvedValueOnce({mode:'iframe',method:'GET',url:'https://child.p.test/private',target_origin:'https://child.p.test'});
 await mount({...readyModule(),mode:'iframe'});const frame=host.querySelector('iframe')!;
 const post=vi.spyOn(frame.contentWindow!,'postMessage');frame.dispatchEvent(new Event('load'));await flush();
 expect(post.mock.calls.at(-1)?.[1]).toBe('https://child.p.test');
 const request=post.mock.calls.at(-1)![0];message(frame,{...request,type:'stella-bg-ready'},'https://child.p.test');await flush();
 expect(getComputedStyle(frame).visibility).toBe('visible');
});
it.each([
 {source_origin:'https://wrong-parent.test',target_origin:'https://child.p.test'},
 {source_origin:location.origin,target_origin:'https://wrong-child.test'},
])('rejects a direct launch with mismatched source/target before mounting or messaging its frame: %j',async binding=>{
 vi.mocked(launchWebsite).mockResolvedValueOnce({mode:'iframe',method:'GET',url:'https://child.p.test/private',...binding});
 await mount({...readyModule(),mode:'iframe'});
 expect(host.querySelector('iframe')).toBeNull();
 expect(host.querySelector('[role=alert]')).not.toBeNull();
});
it.each(['https://wrong-parent.test', 'null'])('rejects mismatched launch source %s before submitting ticket',async(source_origin)=>{
 const submit=vi.spyOn(HTMLFormElement.prototype,'submit').mockImplementation(()=>{});
 vi.mocked(launchWebsite).mockResolvedValueOnce({mode:'isolated_proxy',method:'POST',url:'https://child.p.test/__stella/bootstrap',source_origin,target_origin:'https://child.p.test'});
 try{await mount();expect(submit).not.toHaveBeenCalled();expect(host.querySelector('iframe')).toBeNull();expect(host.querySelector('[role=alert]')).not.toBeNull();}finally{submit.mockRestore();}
});
it('centres first launch stages, exits on document load without claiming internal readiness, and keeps content during reconnect',async()=>{
 let resolve!:(value:any)=>void;
 vi.mocked(launchWebsite).mockImplementationOnce(()=>new Promise(yes=>{resolve=yes;}));
 await mount();
 expect(host.querySelector('.external-loading--center')).not.toBeNull();
 expect(host.querySelector('[role=status]')?.textContent).toContain('正在启动');
 resolve({mode:'isolated_proxy',method:'GET',url:'https://child.test/'});await flush();
 expect(host.querySelector('[role=status]')?.textContent).toContain('等待页面');
 const frame=host.querySelector('iframe')!;frame.dispatchEvent(new Event('load'));await flush();
 await vi.waitFor(()=>expect(host.querySelector('.external-loading')).toBeNull());
 expect(host.textContent).not.toContain('内容就绪');
 window.dispatchEvent(new Event('offline')); // no automatic reconnect/authorization
 expect(launchWebsite).toHaveBeenCalledTimes(1);
 // Exposed reconnect is also used by the recovery action; preserve the old browsing context while launching.
 vi.mocked(launchWebsite).mockImplementationOnce(()=>new Promise(yes=>{resolve=yes;}));
 await (app as any)._instance.subTree.component.exposed.reconnect();await flush();
 expect(host.querySelector('iframe')).toBe(frame);
 expect(host.querySelector('.external-loading--center')).toBeNull();
 expect(host.querySelector('.external-loading--compact')).not.toBeNull();
 resolve({mode:'isolated_proxy',method:'GET',url:'https://child.test/reconnected'});await flush();
 expect(host.querySelector('iframe')).not.toBe(frame);
 host.querySelector('iframe')!.dispatchEvent(new Event('load'));await flush();
 await vi.waitFor(()=>expect(host.querySelector('.external-loading')).toBeNull());
});
it('bounds a stalled launch, ignores its late result, and allows a manual retry',async()=>{
 vi.useFakeTimers();let resolve!:(value:any)=>void;
 vi.mocked(launchWebsite).mockImplementationOnce(()=>new Promise(yes=>{resolve=yes;}));
 await mount();await vi.advanceTimersByTimeAsync(20000);await flush();
 expect(host.querySelector('.recovery-actions button')).not.toBeNull();
 expect((host.querySelector('.recovery-actions button') as HTMLButtonElement).disabled).toBe(false);
 resolve({mode:'isolated_proxy',method:'GET',url:'https://child.test/late'});await flush();
 expect(host.querySelector('iframe')).toBeNull();
 (host.querySelector('.recovery-actions button') as HTMLButtonElement).click();await flush();
 expect(launchWebsite).toHaveBeenCalledTimes(2);
 expect(host.querySelector('iframe')?.getAttribute('src')).toBe('https://child.test/');
});
it('removes the blocking loader on document load before any appearance ACK',async()=>{
 await mount(readyModule());const frame=host.querySelector('iframe')!;
 frame.dispatchEvent(new Event('load'));await flush();
 await vi.waitFor(()=>expect(host.querySelector('.external-loading--center')).toBeNull());
 const post=vi.spyOn(frame.contentWindow!,'postMessage');message(frame,{type:'stella-bg-request'});await flush();
 message(frame,{...post.mock.calls.at(-1)![0],type:'stella-bg-ready'});await flush();
 await vi.waitFor(()=>expect(host.querySelector('.external-loading')).toBeNull());
});
it('does not wait for a draft probe before mounting an ordinary iframe',async()=>{
 vi.mocked(checkWebsiteDraft).mockImplementationOnce(()=>new Promise(()=>{}));
 await mount({...module(),mode:'iframe'});expect(host.querySelector('iframe')?.getAttribute('src')).toBe('https://child.test/');expect(checkWebsiteDraft).not.toHaveBeenCalled();
});
it.each(['origin','source','module','nonce','mode','color_scheme'] as const)('rejects invalid appearance ACK %s without hiding content',async field=>{
 vi.useFakeTimers();await mount(readyModule());const frame=host.querySelector('iframe')!;
 const post=vi.spyOn(frame.contentWindow!,'postMessage');frame.dispatchEvent(new Event('load'));message(frame,{type:'stella-bg-request'});await flush();
 const ack={...post.mock.calls.at(-1)![0],type:'stella-bg-ready'};
 if(field==='module')ack.module_id='wrong';if(field==='nonce')ack.request_id='old';if(field==='mode')ack.mode='solid';if(field==='color_scheme')ack.color_scheme='invalid';
 message(frame,ack,field==='origin'?'https://evil.test':'https://child.test',field==='source'?window:frame.contentWindow);
 await vi.advanceTimersByTimeAsync(20000);await flush();expect(host.querySelector('[role=alert]')?.textContent).toContain('背景');expect(getComputedStyle(frame).visibility).toBe('visible');
});
it('does not apply a legacy preference to another ordinary website or a deleted alias',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');navigation.legacy_routes={drive:'removed'};await mount();
 expect(host.querySelector('.home-background')).toBeNull();
});
