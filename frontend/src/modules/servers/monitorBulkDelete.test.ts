import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Delete from './MonitorBulkDelete.vue';
import Management from './MonitorManagement.vue';
import Group from './MonitorGroupEditor.vue';
import * as api from '../../api/servers';
import {auth} from '../home/auth';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},suspended:false,sessionClosing:false,requestEpoch:0,sessionGeneration:0})}));
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),removeMonitor:vi.fn(),listMonitorChecks:vi.fn()}));
const m=(id:number,name:string,extra:any={})=>({id,name,type:'ping',target:'example.com',node_id:1,interval:60,timeout:5,status:'up',...extra});
let app:ReturnType<typeof createApp>,host:HTMLElement;const changed=vi.fn(),closed=vi.fn();
async function settle(){for(let i=0;i<50;i++)await Promise.resolve();await nextTick();}
async function mount(kind='delete',extra:any={}){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>kind==='delete'?h(Delete,{monitors:[m(7,'A'),m(8,'B')] as any,onChanged:changed,onClose:closed,...extra}):kind==='group'?h(Group,{monitors:[m(7,'A')] as any,groups:[{id:2,name:'组',child_ids:[7],failure_policy:'any',rotation_seconds:0}] as any,initialGroupId:2,nodeName:()=> '节点',...extra}):h(Management,{open:true,...extra})});app.mount(host);await settle();}
async function click(text:string){const el=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(el,text).toBeTruthy();el!.click();await settle();}
beforeEach(()=>{vi.resetAllMocks();Object.assign(auth,{me:{id:'owner'},suspended:false,sessionClosing:false});vi.mocked(api.listMonitors).mockResolvedValue([m(7,'A'),m(8,'B')] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);for(const [method,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,method,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();});
test('cancel has zero writes; selected frozen IDs only; unknown ACK recovers GET-only, partial failures remain',async()=>{
 await mount();await click('取消');expect(api.removeMonitor).not.toHaveBeenCalled();
 vi.mocked(api.removeMonitor).mockImplementation(async id=>{if(id===8)throw new Error('lost ACK')});vi.mocked(api.listMonitors).mockResolvedValue([m(8,'B')] as any);
 await click('确认批量删除');expect(vi.mocked(api.removeMonitor).mock.calls.map(c=>c[0])).toEqual([7,8]);expect(changed).toHaveBeenCalledWith([7]);expect(host.textContent).toContain('已删除');expect(host.textContent).toContain('仍存在');
 vi.mocked(api.listMonitors).mockResolvedValue([]);await click('重新读取确认');expect(api.removeMonitor).toHaveBeenCalledTimes(2);expect(changed).toHaveBeenLastCalledWith([8]);
});
test('permission rejection halts unsent siblings and keeps their visible scope',async()=>{
 vi.mocked(api.removeMonitor).mockRejectedValue({status:403});await mount();await click('确认批量删除');expect(vi.mocked(api.removeMonitor).mock.calls.map(c=>c[0])).toEqual([7]);expect(host.textContent).toContain('B');expect(changed).not.toHaveBeenCalled();
});
test('logout during first DELETE blocks unsent sibling and fences late response',async()=>{
 let finish!:()=>void;vi.mocked(api.removeMonitor).mockImplementation(()=>new Promise<void>(r=>finish=r));await mount();await click('确认批量删除');auth.suspended=true;await settle();finish();await settle();expect(vi.mocked(api.removeMonitor).mock.calls.map(c=>c[0])).toEqual([7]);expect(changed).not.toHaveBeenCalled();expect(host.querySelector<HTMLDialogElement>('[aria-label="批量删除监控项"]')?.open).toBe(false);
});
test('current visible list select-all excludes filtered out and protected items, cancel retains rows',async()=>{
 vi.mocked(api.listMonitors).mockResolvedValue([m(7,'only-A'),m(8,'B'),m(9,'only-A自动',{management:'entry_icmp'})] as any);await mount('management');await click('独立监控 3');const search=host.querySelector<HTMLInputElement>('[aria-label="搜索监控"]')!;search.value='only-A';search.dispatchEvent(new Event('input',{bubbles:true}));await settle();const all=host.querySelector<HTMLInputElement>('[aria-label="全选当前列表"]')!;expect(all).toBeTruthy();all.click();await settle();await click('批量删除 (1)');const confirmation=host.querySelector('[aria-label="批量删除监控项"]')!;expect(confirmation.textContent).toContain('A');expect(confirmation.textContent).not.toContain('B');await click('取消');expect(api.removeMonitor).not.toHaveBeenCalled();
});
test('group member selection deletes actual items without dissolving empty group',async()=>{
 await mount('group');const all=host.querySelector<HTMLInputElement>('[aria-label="全选当前列表"]')!;expect(all).toBeTruthy();all.click();await settle();await click('批量删除 (1)');expect(host.querySelector('[aria-label="批量删除监控项"]')?.textContent).toContain('空组保留');
});
