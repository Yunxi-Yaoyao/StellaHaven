import {afterEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App, type Ref} from 'vue';
import {createMemoryHistory,createRouter} from 'vue-router';
vi.mock('./AvatarCropper.vue',()=>({default:{template:'<div />'}}));
vi.mock('./NavigationSettings.vue',()=>({default:{template:'<div>导航与网站原功能</div>'}}));
vi.mock('../../shell/SettingsPanel.vue',()=>({default:{template:'<div />'}}));
vi.mock('./SecuritySettings.vue',()=>({default:{template:'<div>管理保护</div>'}}));
vi.mock('./AuthProviderSettings.vue',()=>({default:{template:'<div>认证原功能</div>'}}));
vi.mock('./AppearanceSettings.vue',()=>({default:{template:'<div>外观原功能</div>'}}));
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'fixture-owner',display_name:'云曦',username:'fixture'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false}),isAdmin:ref(true),currentAvatar:ref(''),logout:vi.fn()};});
vi.mock('../../api/servers',()=>({getPublicHost:vi.fn().mockResolvedValue({value:''}),setPublicHost:vi.fn()}));
import {isAdmin} from '../home/auth';
import SettingsPage from './SettingsPage.vue';
let app:App|undefined;
const requests:{url:string;options:RequestInit}[]=[];
const snapshot=()=>({config:{revision:1,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0},records:[],job:null,storage:{node:'fixture',available:true,free_bytes:10000,error:null},next_run:null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}});
let responder:(url:string,options:RequestInit)=>Promise<Response>;
const response=(body:unknown)=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});
async function settle(){for(let i=0;i<5;i++){await new Promise(r=>setTimeout(r,0));await nextTick();}}
async function mount(){
  responder=async(url)=>response(url.startsWith('/operations/backups')?snapshot():[]);
  vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit={})=>{requests.push({url,options});return responder(url,options);}));
  Object.defineProperty(performance,'getEntriesByType',{configurable:true,value:()=>[]});
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage}]});await router.push('/settings?section=profile');await router.isReady();const root=document.createElement('div');document.body.append(root);app=createApp(SettingsPage);app.use(router);app.mount(root);await settle();return {root,router};
}
function button(root:ParentNode,label:string){const el=[...root.querySelectorAll<HTMLButtonElement>('button,a')].find(b=>b.textContent?.trim()===label);expect(el,`button ${label}`).toBeDefined();return el!;}
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';requests.length=0;(isAdmin as Ref<boolean>).value=true;vi.unstubAllGlobals();});
it('wires a dedicated native backups section without replacing existing settings or duplicating health mounts',async()=>{
  const {root,router}=await mount();expect(requests.filter(r=>r.url.startsWith('/operations/backups'))).toHaveLength(0);
  expect([...root.querySelectorAll('.tab')].map(b=>b.textContent)).toEqual(['账号与登录','外观与显示','导航与网站','站点与服务','备份与恢复','性能与存储']);
  button(root,'备份与恢复').click();await settle();expect(router.currentRoute.value.query.section).toBe('backups');expect(root.querySelectorAll('.backup-center')).toHaveLength(1);expect(root.textContent).not.toContain('本页性能');
  button(root,'性能与存储').click();await settle();expect(root.textContent).toContain('本页性能');expect(requests.some(r=>r.url==='/operations/backup-health')).toBe(false);
  button(root,'外观与显示').click();await settle();expect(root.textContent).toContain('外观原功能');
});
it('native section deactivate aborts pending reads, preserves unsaved directory and reads fresh on return',async()=>{
  const {root}=await mount();button(root,'备份与恢复').click();await settle();const directory=root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')!;directory.value='/retained-tab';directory.dispatchEvent(new Event('input',{bubbles:true}));
  let resolve!:(r:Response)=>void;let signal:AbortSignal|undefined;responder=async(_url,options)=>{if(!_url.startsWith('/operations/backups'))return response([]);signal=options.signal as AbortSignal;return new Promise(r=>{resolve=r;});};button(root,'刷新备份状态').click();await nextTick();
  button(root,'账号与登录').click();await settle();expect(signal?.aborted).toBe(true);
  responder=async()=>response(snapshot());button(root,'备份与恢复').click();await settle();expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/retained-tab');resolve(response({...snapshot(),config:{...snapshot().config,directory:'/late-read'}}));await settle();expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/retained-tab');
});
it('lost owner permission aborts pending writes and retains input without late success or automatic POST/PATCH',async()=>{
  const {root}=await mount();button(root,'备份与恢复').click();await settle();const directory=root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')!;directory.value='/keep-on-lock';directory.dispatchEvent(new Event('input',{bubbles:true}));
  let resolve!:(r:Response)=>void;let signal:AbortSignal|undefined;responder=async(_url,options)=>{if(!_url.startsWith('/operations/backups'))return response([]);signal=options.signal as AbortSignal;return new Promise(r=>{resolve=r;});};button(root,'应用目录与计划').click();await nextTick();(isAdmin as Ref<boolean>).value=false;await nextTick();expect(signal?.aborted).toBe(true);expect(root.textContent).not.toContain('解锁管理权限');expect(root.textContent).toContain('当前会话无权执行此操作');expect(button(root,'重新读取状态').disabled).toBe(false);expect(button(root,'应用目录与计划').disabled).toBe(true);
  resolve(response({...snapshot().config,directory:'/late-lock',revision:2}));await settle();expect(root.textContent).not.toContain('目录与计划已确认');expect(root.querySelector<HTMLInputElement>('[aria-label="备份目录"]')?.value).toBe('/keep-on-lock');expect(requests.filter(r=>r.options.method==='PATCH')).toHaveLength(1);
});
