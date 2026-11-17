import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Management from './MonitorManagement.vue';
import * as api from '../../api/servers';
vi.mock('../home/auth',async()=>{const {reactive}=await import('vue');return {auth:reactive({me:{id:'owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false})};});
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),listMonitorChecks:vi.fn()}));
const item={id:7,name:'独立监控',node_id:1,type:'ping',target:'owned.example',visible:false,enabled:false,effective_enabled:false,status:'down'};
let app:ReturnType<typeof createApp>,host:HTMLDivElement;
const changed=vi.fn();
async function settle(){for(let i=0;i<50;i++)await Promise.resolve();await nextTick();}
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Management,{open:true,monitors:[],groups:[],nodes:[],onChanged:changed})});app.mount(host);await settle();await button('独立监控 1');}
async function button(text:string){const b=[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();await settle();}
beforeEach(()=>{Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.open=true;}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.open=false;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.resetAllMocks();});
test('lists retained hidden/disabled items and real filtered history',async()=>{
 vi.mocked(api.listMonitors).mockResolvedValue([item] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);vi.mocked(api.listMonitorChecks).mockResolvedValue([{id:1,monitor_id:7,ts:'2026-10-20T01:00:00Z',success:false,latency_ms:null,loss_pct:100}]);
 await mount();expect(document.body.textContent).toContain('独立监控');expect(document.body.textContent).toContain('已停用');host.querySelector<HTMLButtonElement>('[aria-haspopup=menu]')!.click();await settle();await button('查看历史');expect(api.listMonitorChecks).toHaveBeenCalledWith(7);expect(document.body.textContent).toContain('异常');
});
test('ACK then failed GET locks mutation and retry is GET only',async()=>{
 vi.mocked(api.listMonitors).mockResolvedValueOnce([item] as any).mockRejectedValueOnce(new Error('read failed')).mockResolvedValue([{...item,visible:true}] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);vi.mocked(api.updateMonitor).mockResolvedValue({...item,visible:true} as any);
 await mount();host.querySelector<HTMLButtonElement>('[role=switch][aria-label="总览显示 独立监控"]')!.click();await settle();expect(api.updateMonitor).toHaveBeenCalledExactlyOnceWith(7,{visible:true});expect(changed).not.toHaveBeenCalled();expect(document.body.textContent).toContain('尚未确认');await button('重新读取');expect(api.updateMonitor).toHaveBeenCalledOnce();expect(changed).toHaveBeenCalledOnce();
});
