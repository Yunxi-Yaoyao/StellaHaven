import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Editor from './MonitorGroupEditor.vue';
import ItemEditor from './MonitorItemEditor.vue';
import Management from './MonitorManagement.vue';
import * as api from '../../api/servers';
import {auth} from '../home/auth';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},suspended:false,sessionClosing:false,requestEpoch:0,sessionGeneration:0})}));
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),removeMonitor:vi.fn(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),dissolveMonitorGroup:vi.fn(),listMonitorChecks:vi.fn()}));
const member={id:7,name:'服务 A',node_id:1,type:'tcp',target:'owned.example:443',interval:60,timeout:5,status:'up',visible:true,enabled:true};
const group={id:2,name:'业务组',child_ids:[7],failure_policy:'any',rotation_seconds:0,status:'up',down_count:0,unknown_count:0};
let app:ReturnType<typeof createApp>,host:HTMLElement;
const saved=vi.fn(),changed=vi.fn(),closed=vi.fn();
async function settle(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
async function click(text:string,root:ParentNode=host){const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();await settle();}
async function mount(which:'item'|'group'|'management'='item',extra:any={}){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>which==='item'?h(ItemEditor,{monitor:member as any,nodeName:'节点 A',onSaved:saved,onClose:closed,...extra}):which==='group'?h(Editor,{monitors:[member] as any,groups:[group] as any,initialGroupId:2,nodeName:()=> '节点 A',onChanged:changed,onSaved:saved,onClose:closed,...extra}):h(Management,{open:true,onChanged:changed,onClose:closed,...extra})});app.mount(host);await settle();}
beforeEach(()=>{vi.resetAllMocks();Object.assign(auth,{me:{id:'owner'},suspended:false,sessionClosing:false});vi.mocked(api.listMonitors).mockResolvedValue([member] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();});
test('group row deletes even its last member without editing or detaching; confirmation cancel is inert',async()=>{
 await mount('group');expect(host.textContent).not.toContain('移出监控组');const row=host.querySelector('.child-row')!;await click('删除',row);expect(host.querySelector('[aria-label="编辑监控项"]')).toBeNull();const confirm=host.querySelector<HTMLDialogElement>('[aria-label="确认删除监控项"]')!;expect(confirm.open).toBe(true);expect(confirm.textContent).toContain('业务组');expect(confirm.textContent).toContain('不会变为独立监控');await click('取消',confirm);expect(api.removeMonitor).not.toHaveBeenCalled();expect(host.querySelector('.child-row')?.textContent).toContain(member.name);
 await click('删除',host.querySelector('.child-row')!);vi.mocked(api.removeMonitor).mockResolvedValue();vi.mocked(api.listMonitors).mockResolvedValue([]);vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[]}] as any);await click('确认删除');expect(api.removeMonitor).toHaveBeenCalledExactlyOnceWith(7);expect(api.saveMonitorGroup).not.toHaveBeenCalled();expect(host.querySelectorAll('.child-row')).toHaveLength(0);expect(host.textContent).toContain('没有监控项');expect(changed).toHaveBeenCalledOnce();
});
test('standalone list has a direct delete confirmation and refreshes without entering edit',async()=>{
 vi.mocked(api.listMonitorGroups).mockResolvedValue([]);await mount('management');await click('独立监控 1');await click('删除',host.querySelector('.item-row')!);expect(host.querySelector('[aria-label="编辑监控项"]')).toBeNull();expect(host.querySelector<HTMLDialogElement>('[aria-label="确认删除监控项"]')?.open).toBe(true);vi.mocked(api.removeMonitor).mockResolvedValue();vi.mocked(api.listMonitors).mockResolvedValue([]);await click('确认删除');expect(api.removeMonitor).toHaveBeenCalledExactlyOnceWith(7);expect(host.querySelector('.item-row')).toBeNull();expect(changed).toHaveBeenCalledOnce();
});
test('ACK then failed read retains task, locks close and retries GET without replay',async()=>{
 await mount('group');await click('删除',host.querySelector('.child-row')!);vi.mocked(api.removeMonitor).mockResolvedValue();vi.mocked(api.listMonitors).mockRejectedValueOnce(new Error('offline')).mockResolvedValue([]);vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[]}] as any);await click('确认删除');expect(changed).not.toHaveBeenCalled();expect(host.textContent).toContain('删除尚未确认');const confirm=host.querySelector<HTMLDialogElement>('[aria-label="确认删除监控项"]')!;expect([...confirm.querySelectorAll('button')].find(b=>b.textContent==='取消')?.disabled).toBe(true);confirm.dispatchEvent(new Event('cancel',{cancelable:true}));await settle();expect(confirm.open).toBe(true);await click('重新读取确认');expect(api.removeMonitor).toHaveBeenCalledOnce();expect(changed).toHaveBeenCalledOnce();
});
test('confirmed deletion survives failed group refresh with a read-only retry',async()=>{
 await mount('group');await click('删除',host.querySelector('.child-row')!);vi.mocked(api.removeMonitor).mockResolvedValue();vi.mocked(api.listMonitors).mockResolvedValue([]);vi.mocked(api.listMonitorGroups).mockRejectedValueOnce(new Error('group read offline')).mockResolvedValue([{...group,child_ids:[]}] as any);await click('确认删除');expect(host.querySelector('.child-row')).toBeNull();expect(changed).not.toHaveBeenCalled();await click('重新读取监控项');expect(api.removeMonitor).toHaveBeenCalledOnce();expect(api.saveMonitorGroup).not.toHaveBeenCalled();expect(changed).toHaveBeenCalledOnce();
});
test('definite rejection keeps monitor and offers retry, not success',async()=>{
 await mount('group');await click('删除',host.querySelector('.child-row')!);vi.mocked(api.removeMonitor).mockRejectedValueOnce({status:403});await click('确认删除');expect(host.textContent).toContain('删除被拒绝');expect(changed).not.toHaveBeenCalled();expect(host.querySelector('[aria-label="确认删除监控项"]')).toBeTruthy();vi.mocked(api.removeMonitor).mockResolvedValue();vi.mocked(api.listMonitors).mockResolvedValue([]);vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[]}] as any);await click('确认删除');expect(api.removeMonitor).toHaveBeenCalledTimes(2);expect(changed).toHaveBeenCalledOnce();
});
test('unknown DELETE result never replays and same owner login resumes verification',async()=>{
 await mount('item',{deleteOnly:true});vi.mocked(api.removeMonitor).mockRejectedValueOnce(new Error('connection lost'));await click('确认删除');auth.suspended=true;await settle();expect(host.querySelector<HTMLDialogElement>('.item-window')?.open).toBe(false);auth.suspended=false;await settle();vi.mocked(api.listMonitors).mockResolvedValue([]);await click('重新读取确认');expect(api.removeMonitor).toHaveBeenCalledOnce();expect(saved).toHaveBeenCalledOnce();
});
test('owner change fences in-flight deletion response and clears private content',async()=>{
 let finish!:()=>void;vi.mocked(api.removeMonitor).mockImplementation(()=>new Promise<void>(r=>{finish=r;}));await mount('item',{deleteOnly:true});await click('确认删除');auth.me={id:'another'} as any;await settle();finish();await settle();expect(saved).not.toHaveBeenCalled();expect(closed).toHaveBeenCalledOnce();expect(api.listMonitors).not.toHaveBeenCalled();expect(host.querySelector<HTMLDialogElement>('.item-window')?.open).toBe(false);
});
test('system groups never expose member deletion even for ordinary-looking children',async()=>{
 await mount('group',{groups:[{...group,automatic:true}]});expect(host.querySelector('[aria-label="删除监控项 服务 A"]')).toBeNull();expect(api.removeMonitor).not.toHaveBeenCalled();
});
test('automatic standalone monitor has no delete entry',async()=>{
 vi.mocked(api.listMonitorGroups).mockResolvedValue([]);vi.mocked(api.listMonitors).mockResolvedValue([{...member,management:'entry_icmp'}] as any);await mount('management');await click('独立监控 1');expect(host.querySelector('[aria-label="删除监控项 服务 A"]')).toBeNull();expect(api.removeMonitor).not.toHaveBeenCalled();
});
test('automatic monitor remains undeletable even in direct delete mode',async()=>{
 await mount('item',{deleteOnly:true,monitor:{...member,management:'entry_icmp'}});expect(host.textContent).toContain('不可手动删除');expect([...host.querySelectorAll('button')].find(b=>b.textContent==='确认删除')).toBeUndefined();expect(api.removeMonitor).not.toHaveBeenCalled();
});
test('item editor exposes delete directly, names irreversible scope and cancel performs no mutation',async()=>{
 await mount();expect(host.querySelector('[aria-label="监控项操作"]')).toBeNull();await click('删除监控项');const confirm=host.querySelector<HTMLDialogElement>('[aria-label="确认删除监控项"]')!;expect(confirm.open).toBe(true);expect(confirm.textContent).toContain('服务 A');expect(confirm.textContent).toContain('历史');await click('取消',confirm);expect(confirm.open).toBe(false);expect(api.removeMonitor).not.toHaveBeenCalled();
});
