/** Requires automatic retention (parent 3a885ea), exercises the REAL cache + page. */
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createRouter,createMemoryHistory,type Router} from 'vue-router';
import ExternalModuleCache from './ExternalModuleCache.vue';
import {auth} from '../modules/home/auth';
import {navigation,resetNavigation,type Website} from '../stores/navigation';
import {getWebsite,launchWebsite} from '../api/integrations';
vi.mock('../api/integrations',async original=>({...await original<typeof import('../api/integrations')>(),getWebsite:vi.fn(),launchWebsite:vi.fn()}));
vi.mock('../api/websiteSettings',()=>({checkWebsiteDraft:vi.fn().mockResolvedValue({embedding:{status:'allowed'}})}));
let app:App|undefined,host:HTMLDivElement,router:Router;
const item=(id:string,keep_alive?:boolean):Website=>({id,name:id,icon:'globe',mode:'iframe',adapter:'generic',browser_url:`https://${id}.test/`,origin:`https://${id}.test`,enabled:true,keep_alive,background:'home',injection:{active:{enabled:true,css:'',js:'/* stella:background-ready:v1 */',version:'v1',timing:'dom_ready',csp_policy:'reject'},draft:null,previous:null}});
async function flush(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
async function open(id:string){await router.push('/apps/'+id);await flush();await vi.dynamicImportSettled();await flush();}
const frame=(id:string)=>host.querySelector(`iframe[name="stella-external-module-frame-${id}"]`) as HTMLIFrameElement;
function send(f:HTMLIFrameElement,data:unknown,id:string){window.dispatchEvent(new MessageEvent('message',{data,origin:`https://${id}.test`,source:f.contentWindow}));}
function request(f:HTMLIFrameElement,id:string){const post=vi.spyOn(f.contentWindow!,'postMessage');f.dispatchEvent(new Event('load'));send(f,{type:'stella-bg-request'},id);return post.mock.calls.at(-1)![0];}
beforeEach(()=>{localStorage.clear();resetNavigation();vi.clearAllMocks();Object.assign(auth,{me:{id:'owner',home_bg:'https://media.test/pattern.jpg'},sessionGeneration:0,sessionClosing:false,suspended:false});vi.mocked(getWebsite).mockImplementation(async id=>item(id));vi.mocked(launchWebsite).mockImplementation(async id=>({mode:'iframe',method:'GET',url:`https://${id}.test/`,target_origin:`https://${id}.test`,source_origin:location.origin}));});
afterEach(()=>{app?.unmount();app=undefined;host?.remove();resetNavigation();vi.useRealTimers();});
it.each([false,undefined])('retains legacy keep_alive=%s with a fresh foreground background budget and fences hidden/cross-site late ACKs',async keep_alive=>{
 vi.useFakeTimers();navigation.modules=[item('one',keep_alive),item('two',keep_alive)];navigation.loaded=true;
 router=createRouter({history:createMemoryHistory(),routes:[{path:'/apps/:id',name:'external-module',component:{render:()=>null}},{path:'/settings',component:{render:()=>null}}]});await router.push('/apps/one');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp(ExternalModuleCache).use(router);app.mount(host);await vi.dynamicImportSettled();await flush();
 const one=frame('one'),old=request(one,'one');expect(one.style.visibility).toBe('visible');await open('two');
 expect(frame('one')).toBe(one);const two=frame('two'),other=request(two,'two');expect(two.style.visibility).toBe('visible');
 send(one,{...old,type:'stella-bg-ready'},'one');send(one,{...other,type:'stella-bg-ready'},'one');await flush();expect(one.style.visibility).toBe('visible');expect(two.style.visibility).toBe('visible');
 await vi.advanceTimersByTimeAsync(20001);await flush();expect(one.closest('section')!.querySelector('[role=alert]')).toBeNull();expect(two.closest('section')!.querySelector('[role=alert]')?.textContent).toContain('背景样式未就绪');
 send(two,{...other,type:'stella-bg-ready'},'two');await flush();expect(two.style.visibility).toBe('visible');await open('one');expect(frame('one')).toBe(one);
 const fresh=request(one,'one');expect(fresh.request_id).not.toBe(old.request_id);send(one,{...old,type:'stella-bg-ready'},'one');send(two,{...fresh,type:'stella-bg-ready'},'two');await flush();expect(one.style.visibility).toBe('visible');
 await vi.advanceTimersByTimeAsync(19999);await flush();expect(one.closest('section')!.querySelector('[role=alert]')).toBeNull();send(one,{...fresh,type:'stella-bg-ready'},'one');await flush();expect(one.style.visibility).toBe('visible');await vi.advanceTimersByTimeAsync(2);expect(one.closest('section')!.querySelector('[role=alert]')).toBeNull();expect(launchWebsite).toHaveBeenCalledTimes(2);
});
