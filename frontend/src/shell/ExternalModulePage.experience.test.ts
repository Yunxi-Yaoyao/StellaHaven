import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, reactive, type App } from 'vue';
import ExternalModulePage from './ExternalModulePage.vue';
import { auth } from '../modules/home/auth';
import { navigation, resetNavigation, type Website } from '../stores/navigation';
import { getWebsite, launchWebsite } from '../api/integrations';
vi.mock('../api/integrations',async importOriginal=>({...await importOriginal<typeof import('../api/integrations')>(),getWebsite:vi.fn(),launchWebsite:vi.fn()}));
vi.mock('../api/websiteSettings',()=>({checkWebsiteDraft:vi.fn().mockResolvedValue({embedding:{status:'allowed'}})}));
const id='synthetic-website';
let app:App,host:HTMLDivElement;
const props=reactive({id,active:true});
const module=():Website=>({id,name:'测试网站',icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:'https://child.test/',origin:'https://child.test',enabled:true,keep_alive:true,background:'solid'});
async function flush(){for(let i=0;i<25;i++)await Promise.resolve();await nextTick();}
async function mount(item=module()){
 navigation.modules=[item];navigation.loaded=true;
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
it('reuses the loaded module without a duplicate GET and updates background on the retained frame',async()=>{
 await mount();expect(getWebsite).not.toHaveBeenCalled();expect(launchWebsite).toHaveBeenCalledTimes(1);
 const frame=host.querySelector('iframe');navigation.modules=[{...module(),background:'home'}];await flush();
 expect(host.querySelector('.home-background')).not.toBeNull();expect(host.querySelector('iframe')).toBe(frame);
 props.active=false;await flush();auth.me={...auth.me!};props.active=true;await flush();
 expect(host.querySelector('iframe')).toBe(frame);expect(launchWebsite).toHaveBeenCalledTimes(1);
 auth.me!.home_bg='https://media.test/scene.webm?version=2#clip';await flush();
 const video=host.querySelector('video');expect(video?.getAttribute('src')).toContain('scene.webm');expect(video?.autoplay).toBe(true);expect(video?.muted).toBe(true);
 props.active=false;await flush();expect(host.querySelector('video')).toBeNull();
 props.active=true;await flush();expect(host.querySelector('video')).not.toBeNull();
});
it('keeps a cancelled pending launch paused until an explicit reconnect',async()=>{
 let resolve!:(value:any)=>void;vi.mocked(launchWebsite).mockImplementationOnce(()=>new Promise(yes=>{resolve=yes;}));
 await mount();props.active=false;await flush();resolve({mode:'isolated_proxy',method:'GET',url:'https://child.test/late'});await flush();expect(host.querySelector('iframe')).toBeNull();
 props.active=true;await flush();expect(launchWebsite).toHaveBeenCalledTimes(1);
 (host.querySelector('.recovery-actions button') as HTMLButtonElement).click();await flush();expect(launchWebsite).toHaveBeenCalledTimes(2);expect(host.querySelector('iframe')?.getAttribute('src')).toBe('https://child.test/');
});
const readyModule=():Website=>({...module(),background:'home',injection:{active:{enabled:true,js:'/* stella:background-ready:v1 */',css:'',timing:'dom_ready',csp_policy:'reject',version:'v1'},draft:null,previous:null}});
function message(frame:HTMLIFrameElement,data:unknown,origin='https://child.test',source:Window|null=frame.contentWindow){window.dispatchEvent(new MessageEvent('message',{data,origin,source}));}
it('hides an opted-in home iframe before load and accepts only the exact style-ready ACK',async()=>{
 await mount(readyModule());const frame=host.querySelector('iframe')!;
 expect(getComputedStyle(frame).visibility).toBe('hidden');
 const post=vi.spyOn(frame.contentWindow!,'postMessage');frame.dispatchEvent(new Event('load'));await flush();
 expect(getComputedStyle(frame).visibility).toBe('hidden');
 message(frame,{type:'stella-bg-request'});await flush();const [request,origin]=post.mock.calls.at(-1)!;
 expect(origin).toBe('https://child.test');expect(request).toMatchObject({type:'stella-bg-mode',module_id:id,mode:'image',request_id:expect.any(String)});
 const ack={...request,type:'stella-bg-ready'};
 for(const invalid of [{...ack,module_id:'wrong'},{...ack,request_id:'old'},{...ack,mode:'solid'}]){message(frame,invalid);await flush();expect(getComputedStyle(frame).visibility).toBe('hidden');}
 message(frame,ack,'https://evil.test');message(frame,ack,'https://child.test',window);await flush();expect(getComputedStyle(frame).visibility).toBe('hidden');
 message(frame,ack);await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
 navigation.modules=[{...readyModule(),background:'solid'}];await flush();expect(post.mock.calls.at(-1)?.[0]).toMatchObject({mode:'solid'});
 navigation.modules=[readyModule()];await flush();const fresh=post.mock.calls.at(-1)?.[0];expect(fresh.request_id).not.toBe(request.request_id);
 message(frame,ack);await flush();expect(getComputedStyle(frame).visibility).toBe('hidden');
 message(frame,{...fresh,type:'stella-bg-ready'});await flush();expect(getComputedStyle(frame).visibility).toBe('visible');
});
it('bounds missing style ACK with an explicit reconnect error without revealing the solid frame',async()=>{
 vi.useFakeTimers();await mount(readyModule());const frame=host.querySelector('iframe')!;frame.dispatchEvent(new Event('load'));await flush();
 await vi.advanceTimersByTimeAsync(20000);expect(host.querySelector('[role=alert]')?.textContent).toContain('背景');expect(getComputedStyle(frame).visibility).toBe('hidden');
 const reconnect=host.querySelector('.recovery-actions button') as HTMLButtonElement;expect(reconnect.disabled).toBe(false);reconnect.click();await flush();expect(launchWebsite).toHaveBeenCalledTimes(2);expect(host.querySelector('iframe')).not.toBe(frame);
});
it.each(['missing','disabled'])('leaves a %s readiness template native and never gates on template_id',async(kind)=>{
 const item=readyModule();item.template_id='openlist';if(kind==='missing')item.injection!.active!.js='';else item.injection!.active!.enabled=false;
 await mount(item);expect(getComputedStyle(host.querySelector('iframe')!).visibility).not.toBe('hidden');
});
it('does not apply a legacy preference to another ordinary website or a deleted alias',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');navigation.legacy_routes={drive:'removed'};await mount();
 expect(host.querySelector('.home-background')).toBeNull();
});
