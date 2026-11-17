import {createApp,h,nextTick,KeepAlive,type App} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import {it,expect,vi,afterEach} from 'vitest';
const barrier=vi.hoisted(()=>vi.fn());
vi.mock('./AuthProviderSettings.vue',()=>({default:{setup(_:unknown,{expose}:any){expose({beforeLeave:barrier});return()=>h('div',{'data-callback-editor':''});}}}));
vi.mock('./NavigationSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../../shell/SettingsPanel.vue',()=>({default:{template:'<div />'}}));
vi.mock('./PerformanceSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('./SecuritySettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'owner',username:'owner'},sessionGeneration:0,requestEpoch:0}),isAdmin:ref(true),currentAvatar:ref(''),logout:vi.fn()};});
vi.mock('../../api/servers',()=>({getPublicHost:vi.fn().mockResolvedValue({value:''}),setPublicHost:vi.fn()}));
import SettingsPage from './SettingsPage.vue';
let app:App|undefined;
const tick=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};
afterEach(()=>{app?.unmount();document.body.innerHTML='';vi.unstubAllGlobals();barrier.mockReset();});
async function mount(){vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>[]}));const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage},{path:'/elsewhere',component:{template:'<p>Elsewhere</p>'}}]});await router.push('/settings?section=authentication');await router.isReady();const root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(RouterView,{}, {default:({Component}:any)=>h(KeepAlive,{},()=>h(Component))})});app.use(router);app.mount(root);await tick();return {root,router};}
it('owns the callback barrier for query navigation and route leave after retained reactivation',async()=>{const {router}=await mount();barrier.mockResolvedValue(false);await router.replace('/settings?section=appearance');expect(router.currentRoute.value.query.section).toBe('authentication');expect(barrier).toHaveBeenCalledTimes(1);barrier.mockResolvedValue(true);await router.replace('/settings?section=appearance');await router.replace('/settings?section=authentication');await tick();barrier.mockClear();barrier.mockResolvedValue(false);await router.push('/elsewhere');expect(router.currentRoute.value.path).toBe('/settings');expect(barrier).toHaveBeenCalledTimes(1);barrier.mockResolvedValue(true);await router.push('/elsewhere');await router.push('/settings?section=authentication');await tick();barrier.mockClear();barrier.mockResolvedValue(false);await router.replace('/settings?section=services');expect(router.currentRoute.value.query.section).toBe('authentication');expect(barrier).toHaveBeenCalledTimes(1);});
it('waits for the actual callback decision rather than navigating before its result',async()=>{const {router}=await mount();let release!:(value:boolean)=>void;barrier.mockImplementation(()=>new Promise(resolve=>{release=resolve;}));const navigation=router.replace('/settings?section=appearance');await tick();expect(router.currentRoute.value.query.section).toBe('authentication');expect(barrier).toHaveBeenCalledTimes(1);release(false);await navigation;expect(router.currentRoute.value.query.section).toBe('authentication');});
