import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,nextTick,reactive} from 'vue';
import Detail from './MonitorDetailModal.vue';
import * as api from '../../api/servers';
vi.mock('./chartRuntime',()=>({init:()=>({setOption:vi.fn(),dispose:vi.fn(),resize:vi.fn()})}));
vi.mock('../../api/servers',async original=>({...await original<any>(),getMonitorSeries:vi.fn(),listMonitorMtr:vi.fn(),runMonitorMtr:vi.fn(),listComponentInstalls:vi.fn(),installComponent:vi.fn()}));
let app:ReturnType<typeof createApp>|undefined,host:HTMLElement;
const settle=async()=>{for(let i=0;i<50;i++){await Promise.resolve();await nextTick();}};
const button=(text:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!;
const monitor={id:7,node_id:55,name:'受控测试监控',type:'ping',target:'fixture.test',interval:60,timeout:2,status:'up'};
const node=()=>({id:55,name:'探测节点',status:'online',last_seen_at:new Date().toISOString(),components:{mtr:{installed:false}}});
async function mount(n:any=node(),tab='mtr',refresh=()=>{}){host=document.createElement('div');document.body.append(host);app=createApp(Detail,{monitor,nodeName:'探测节点',node:n,initialTab:tab,onRefresh:refresh} as any);app.mount(host);await settle();}
beforeEach(()=>{vi.useFakeTimers();vi.resetAllMocks();vi.mocked(api.getMonitorSeries).mockResolvedValue([]);vi.mocked(api.listMonitorMtr).mockResolvedValue([]);vi.mocked(api.listComponentInstalls).mockResolvedValue([]);});
afterEach(()=>{app?.unmount();app=undefined;host?.remove();vi.useRealTimers();});
test('missing MTR offers actual installer on exact probe node; done then inventory enables execution',async()=>{
 const n=reactive(node());let refresh=0;
 vi.mocked(api.installComponent).mockResolvedValue({id:41,status:'pending'} as any);
 vi.mocked(api.listComponentInstalls).mockResolvedValue([{id:41,status:'done'}] as any);
 await mount(n,'mtr',()=>{refresh++;n.components.mtr.installed=true;});
 expect(button('立即 MTR').disabled).toBe(true);expect(host.textContent).toContain('未安装 MTR');
 button('安装').click();button('安装中…')?.click();await settle();
 expect(api.installComponent).toHaveBeenCalledTimes(1);expect(api.installComponent).toHaveBeenCalledWith(55,'mtr');expect(refresh).toBe(1);
 expect(button('立即 MTR').disabled).toBe(false);
 vi.mocked(api.runMonitorMtr).mockResolvedValue({id:80,status:'pending'} as any);
 vi.mocked(api.listMonitorMtr).mockResolvedValue([{id:80,status:'done',result_json:{report:{hubs:[]}}}] as any);
 button('立即 MTR').click();await settle();expect(api.runMonitorMtr).toHaveBeenCalledWith(7);
});
test('failed install retains capability and exposes actual failure',async()=>{
 vi.mocked(api.installComponent).mockResolvedValue({id:41,status:'pending'} as any);
 vi.mocked(api.listComponentInstalls).mockResolvedValue([{id:41,node_id:55,component:'mtr',status:'failed',error:'fixture package manager failed'}] as any);
 await mount();button('安装').click();await settle();expect(host.textContent).toContain('fixture package manager failed');expect(button('立即 MTR').disabled).toBe(true);expect(api.runMonitorMtr).not.toHaveBeenCalled();
});
test.each([false,{installed:false}])('legacy and current missing inventory both block execution (%j)',async capability=>{
 const n=node() as any;n.components.mtr=capability;await mount(n);expect(button('立即 MTR').disabled).toBe(true);expect(button('安装')).toBeTruthy();
});
test('offline source disables execution and install',async()=>{await mount({...node(),status:'offline'});expect(button('立即 MTR').disabled).toBe(true);expect(button('安装')).toBeUndefined();});
test('MTR history failure is not an empty history and retry recovers',async()=>{
 vi.mocked(api.listMonitorMtr).mockRejectedValueOnce(new Error('fixture history offline'));await mount();expect(host.textContent).toContain('fixture history offline');expect(host.textContent).not.toContain('还没有 MTR 记录');button('重试').click();await settle();expect(host.textContent).not.toContain('fixture history offline');expect(host.textContent).toContain('还没有 MTR 记录');
});
test('chart failure is visible and retry clears error',async()=>{
 vi.mocked(api.getMonitorSeries).mockRejectedValueOnce(new Error('fixture series offline'));await mount(node(),'chart');expect(host.textContent).toContain('fixture series offline');button('重试').click();await settle();expect(host.textContent).not.toContain('fixture series offline');
});
