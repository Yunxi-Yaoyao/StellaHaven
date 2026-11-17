import {createApp,defineComponent,h,nextTick,reactive} from 'vue';
import {afterEach,beforeEach,expect,test,vi} from 'vitest';
const state=vi.hoisted(()=>({route:{query:{view:'files'},name:'status'},push:vi.fn()}));
vi.mock('vue-router',()=>({useRoute:()=>state.route,useRouter:()=>({push:state.push})}));
vi.mock('../home/auth',()=>({auth:reactive({me:{id:'owner-one'},sessionGeneration:1,requestEpoch:2,suspended:false,sessionClosing:false})}));
vi.mock('./NodeFilesView.vue',()=>({__esModule:true,default:defineComponent({props:['scopeKey'],setup:p=>()=>h('div',{'data-file-scope':p.scopeKey},'file-view')})}));
import Home from './ServersHome.vue';
import SideBar from './ServersSideBar.vue';
import {auth} from '../home/auth';
let app:ReturnType<typeof createApp>|undefined,host:HTMLDivElement;
async function settle(){for(let i=0;i<20;i++)await Promise.resolve();await nextTick();}
beforeEach(()=>{host=document.createElement('div');document.body.append(host);Object.assign(auth,{me:{id:'owner-one'},sessionGeneration:1,requestEpoch:2,suspended:false,sessionClosing:false});state.push.mockReset();});
afterEach(()=>{app?.unmount();host.remove();app=undefined;localStorage.clear();});
test('files is mounted only under active main-site auth and scope changes with session epochs',async()=>{
 app=createApp(Home);app.mount(host);await settle();
 expect(host.querySelector('[data-file-scope]')?.getAttribute('data-file-scope')).toBe('owner-one:1:2');
 auth.requestEpoch=3;await settle();expect(host.querySelector('[data-file-scope]')?.getAttribute('data-file-scope')).toBe('owner-one:1:3');
 auth.suspended=true;await settle();expect(host.querySelector('[data-file-scope]')).toBeNull();
 auth.suspended=false;auth.sessionGeneration=4;await settle();expect(host.querySelector('[data-file-scope]')?.getAttribute('data-file-scope')).toBe('owner-one:4:3');
 auth.sessionClosing=true;await settle();expect(host.querySelector('[data-file-scope]')).toBeNull();
});
test('desktop and mobile share explicit files navigation',async()=>{
 app=createApp(SideBar);app.mount(host);await settle();
 const buttons=[...host.querySelectorAll<HTMLButtonElement>('aside button')];const item=buttons.find(b=>b.textContent?.trim()==='文件管理');expect(item).toBeTruthy();item!.click();expect(state.push).toHaveBeenCalledWith({path:'/status',query:{view:'files'}});
 // Mobile options belong to the same production component, not a second menu implementation.
 const source=await import('./ServersSideBar.vue?raw');expect(source.default).toContain("{value:'files',label:'文件管理'}");
});
