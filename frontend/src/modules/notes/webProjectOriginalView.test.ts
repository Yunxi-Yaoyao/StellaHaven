import {createApp,h} from 'vue';import {afterEach,expect,it,vi} from 'vitest';
const api=vi.hoisted(()=>({launch:vi.fn(),prepare:vi.fn(async()=>true)}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
vi.mock('../../api/webProjects',()=>({launchProject:api.launch,renewProject:vi.fn(),getProjectState:vi.fn(),saveProjectState:vi.fn(),resetProjectState:vi.fn(),getProjectSource:vi.fn(),saveProjectSource:vi.fn()}));
vi.mock('./ProjectFiles.vue',async()=>({default:(await import('vue')).defineComponent({setup(_,ctx){ctx.expose({prepareNavigation:api.prepare});return()=>h('section',{'data-original-files':''},'项目文件');}})}));
import Pane from './WebProjectPane.vue';
let app:any,host:HTMLElement;afterEach(()=>{app?.unmount();host?.remove();vi.clearAllMocks();});
it('root renders original HTML without a second always-open file directory; existing files remain accessible',async()=>{
 api.launch.mockResolvedValue({url:'https://pages.test/p/'+('a'.repeat(43))+'/index.html',capability:'a'.repeat(43),source_origin:location.origin,target_origin:'https://pages.test',state:{revision:0,epoch:0,data:{}},expires_in:900});
 host=document.createElement('div');document.body.append(host);app=createApp(Pane,{project:{id:'root',workspace_id:'w',title:'原资料包',entry:'index.html',files:[]},fileId:'root',active:true});app.mount(host);
 await vi.waitFor(()=>expect(host.querySelector('iframe')).not.toBeNull());
 expect(host.querySelector('[data-original-files]')).toBeNull();
 const toggle=()=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()==='项目文件');
 expect(toggle()).toBeTruthy();toggle()!.click();await vi.waitFor(()=>expect(host.querySelector('[data-original-files]')).not.toBeNull());
 api.prepare.mockResolvedValueOnce(false);toggle()!.click();await vi.waitFor(()=>expect(api.prepare).toHaveBeenCalledTimes(1));expect(host.querySelector('[data-original-files]')).not.toBeNull();
 toggle()!.click();await vi.waitFor(()=>expect(host.querySelector('[data-original-files]')).toBeNull());expect(host.querySelector('iframe')).not.toBeNull();
});
