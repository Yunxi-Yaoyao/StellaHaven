import {beforeEach,afterEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Editor from './MonitorGroupEditor.vue';
import Overview from './OverviewView.vue';
import {createRouter,createMemoryHistory} from 'vue-router';
vi.mock('./chartRuntime',()=>({init:()=>({resize(){},setOption(){},dispose(){}}),getInstanceByDom:()=>undefined}));
vi.mock('./ServerWorldMap.vue',()=>({__esModule:true,default:{render:()=>null}}));
vi.mock('./AlertIncidentList.vue',()=>({__esModule:true,default:{render:()=>null}}));
import * as api from '../../api/servers';
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),removeMonitor:vi.fn(),listMonitorGroups:vi.fn(),listMonitors:vi.fn(),listNodes:vi.fn(async()=>[]),getMonitorSeries:vi.fn(async()=>[])}));
const member={id:21,name:'端口探测',node_id:7,type:'tcp',target:'owned.example:443',interval:60,timeout:5,status:'down',status_reason:'failure',visible:true,enabled:true};
const group={id:8,name:'业务组',child_ids:[21,22],failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,unknown_count:0,visible:true,enabled:true};
let app:ReturnType<typeof createApp>,host:HTMLDivElement;
const saved=vi.fn(),changed=vi.fn();
async function settle(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Editor,{monitors:[member,{...member,id:22,name:'正常项',status:'up',status_reason:'healthy'}] as any,groups:[group] as any,initialGroupId:8,nodeName:()=> '节点',onSaved:saved,onChanged:changed})});app.mount(host);await settle();}
beforeEach(async()=>{const {auth}=await import('../home/auth');auth.me={id:'fixture'} as any;auth.suspended=false;auth.sessionClosing=false;for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.resetAllMocks();});
test('compact members show binary status, reason, sampling on demand and readback-gated switches',async()=>{
 await mount();const row=host.querySelector('.child-row')!;expect(row.textContent).toContain('异常');expect(row.querySelector('.child-target')?.textContent).toContain('TCP · owned.example:443');expect(row.querySelector('details')).toBeNull();row.querySelector<HTMLButtonElement>('[aria-haspopup=menu]')!.click();await settle();
 const toggle=[...row.querySelectorAll<HTMLButtonElement>('[role=menuitem]')].find(b=>b.textContent==='隐藏于总览');expect(toggle).toBeTruthy();
 vi.mocked(api.updateMonitor).mockResolvedValue({...member,visible:false} as any);vi.mocked(api.listMonitors).mockResolvedValue([{...member,visible:false}] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);
 toggle!.click();await settle();expect(api.updateMonitor).toHaveBeenCalledWith(21,{visible:false});expect(changed).toHaveBeenCalledOnce();expect(host.textContent).not.toContain('未确认');expect(api.removeMonitor).not.toHaveBeenCalled();
});
test('membership is not detached and group visibility/enabled are explicitly saved and read back',async()=>{
 await mount();expect(host.textContent).not.toContain('移出监控组');expect(host.querySelector('[aria-label="删除监控项 端口探测"]')).toBeTruthy();expect(api.removeMonitor).not.toHaveBeenCalled();
 for(const label of ['隐藏监控组','停用监控组']){host.querySelector<HTMLButtonElement>('[aria-label="监控组操作"]')!.click();await settle();[...host.querySelectorAll<HTMLButtonElement>('[role=menuitem]')].find(b=>b.textContent===label)!.click();await settle();}
 vi.mocked(api.listMonitors).mockResolvedValue([member,{...member,id:22}] as any);const stored={...group,visible:false,enabled:false};vi.mocked(api.saveMonitorGroup).mockResolvedValue(stored as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([stored] as any);
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();expect(api.saveMonitorGroup).toHaveBeenCalledWith(8,{name:'业务组',failure_policy:'any',rotation_seconds:0,visible:false,enabled:false});expect(saved).toHaveBeenCalledOnce();
});
test('overview uses eligible children, hides disabled objects, keeps target and sampling inspectable',async()=>{
 Object.defineProperty(document,'hidden',{value:false,configurable:true});
 vi.mocked(api.listNodes).mockResolvedValue([]);vi.mocked(api.getMonitorSeries).mockResolvedValue([]);
 vi.mocked(api.listMonitors).mockResolvedValue([member,{...member,id:22,visible:false},{...member,id:23,enabled:false},{...member,id:24,name:'hidden group member'},{...member,id:25,name:'disabled solo',enabled:false}] as any);
 vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[21,22,23],eligible_child_ids:[21]},{...group,id:9,name:'hidden group',child_ids:[24],visible:false}] as any);
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]});await router.push('/');host=document.createElement('div');document.body.append(host);app=createApp(Overview);app.use(router);app.mount(host);await settle();
 expect(host.querySelectorAll('.mon-card')).toHaveLength(1);expect(host.querySelector('.mon-current .mon-child-picker')).toBeTruthy();expect(host.querySelector('.mon-target')?.getAttribute('title')).toContain(member.target);expect(host.querySelector('.mon-inspect')).toBeNull();expect(host.querySelector('.mon-latency')?.getAttribute('title')).toContain('异常');expect(host.querySelector('.mon-metrics')).toBeTruthy();
});
test('failed switch readback does not claim success and preserves a retryable error',async()=>{
 await mount();vi.mocked(api.updateMonitor).mockResolvedValue({...member,enabled:false} as any);vi.mocked(api.listMonitors).mockResolvedValue([member] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);
 host.querySelector<HTMLButtonElement>('[aria-haspopup=menu]')!.click();await settle();[...host.querySelectorAll<HTMLButtonElement>('[role=menuitem]')].find(b=>b.textContent==='停用监控')!.click();await settle();expect(changed).not.toHaveBeenCalled();expect(host.querySelector('[role=alert]')?.textContent).toContain('未确认');
});
