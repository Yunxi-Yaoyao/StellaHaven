import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Editor from './MonitorCreateDialog.vue';
import * as api from '../../api/servers';
import {auth} from '../home/auth';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},suspended:false,sessionClosing:false,requestEpoch:0,sessionGeneration:0})}));
vi.mock('../../api/servers',()=>({createMonitorBatch:vi.fn(),getMonitorBatchReceipt:vi.fn(),createMonitorGroup:vi.fn(),getMonitorGroupReceipt:vi.fn(),getMonitorGroupDeletionState:vi.fn(),listMonitors:vi.fn(),listMonitorGroups:vi.fn()}));
let app:ReturnType<typeof createApp>,host:HTMLElement;const saved=vi.fn(),closed=vi.fn();
async function settle(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
async function mount(extra:any={}){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Editor,{nodes:[{id:1,name:'节点'}],onSaved:saved,onClose:closed,...extra})});app.mount(host);await settle();}
async function input(label:string,value:string){const el=host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;expect(el).toBeTruthy();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));await settle();}
async function select(type:string){const el=host.querySelector<HTMLInputElement>(`input[value="${type}"]`)!;el.click();await settle();}
async function click(text:string){const el=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(el).toBeTruthy();el!.click();await settle();}
beforeEach(()=>{vi.resetAllMocks();Object.assign(auth,{me:{id:'owner'},suspended:false,sessionClosing:false});for(const [method,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,method,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();});
test('switching standalone/group preserves separate editable drafts, ports and selected types',async()=>{
 await mount();await input('监控项名称','独立');await input('目标','solo.example');await input('端口','8080');await click('监控组');await input('监控组名称','组');await input('监控项名称','组成员');await input('目标','group.example');await select('udp');await click('独立监控项');expect(host.querySelector<HTMLInputElement>('[aria-label="监控项名称"]')?.value).toBe('独立');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('8080');await click('监控组');expect(host.querySelector<HTMLInputElement>('[aria-label="目标"]')?.value).toBe('group.example');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('80/53');
});
test('lost batch ACK keeps draft and GET-only receipt recovery; no extra group or mutation replay',async()=>{
 await mount();await input('监控项名称','服务');await input('目标','example.com');await select('https');
 vi.mocked(api.createMonitorBatch).mockRejectedValueOnce(new Error('lost ACK'));
 await click('创建监控');expect(api.createMonitorBatch).toHaveBeenCalledOnce();expect(api.createMonitorGroup).not.toHaveBeenCalled();expect(saved).not.toHaveBeenCalled();expect(host.textContent).toContain('创建尚未确认');
 vi.mocked(api.getMonitorBatchReceipt).mockResolvedValue({group_id:null,monitor_ids:[7,8]});vi.mocked(api.listMonitors).mockResolvedValue([{id:7},{id:8}] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);
 await click('重新读取确认');expect(api.createMonitorBatch).toHaveBeenCalledOnce();expect(saved).toHaveBeenCalledOnce();
});
test('cancel performs zero writes and owner change fences held creation and scrubs draft',async()=>{
 await mount();await input('监控项名称','private');await input('目标','example.com');await click('取消');expect(api.createMonitorBatch).not.toHaveBeenCalled();
 let finish!:(v:any)=>void;vi.mocked(api.createMonitorBatch).mockImplementation(()=>new Promise(r=>finish=r));
 await click('创建监控');auth.me={id:'other'} as any;await settle();finish({group_id:null,monitor_ids:[7]});await settle();expect(api.listMonitors).not.toHaveBeenCalled();expect(saved).not.toHaveBeenCalled();expect(host.textContent).not.toContain('private');
});
test('group child batch resolves immutable identity before write and confirms membership, keeping existing group',async()=>{
 vi.mocked(api.getMonitorGroupDeletionState).mockResolvedValue({group_exists:true,stable_uuid:'uuid',protected:false,children:[]} as any);
 await mount({groupId:2,groupName:'现有组'});await input('监控项名称','服务');await input('目标','example.com');await select('udp');
 vi.mocked(api.createMonitorBatch).mockResolvedValue({group_id:2,monitor_ids:[7,8]});vi.mocked(api.listMonitors).mockResolvedValue([{id:7},{id:8}] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([{id:2,child_ids:[7,8]}] as any);
 await click('创建监控');expect(api.createMonitorBatch).toHaveBeenCalledWith(expect.objectContaining({group_id:2,expected_group_uuid:'uuid',items:[expect.objectContaining({type:'tcp',target:'example.com:80'}),expect.objectContaining({type:'udp',target:'example.com:53'})]}),expect.any(Function));expect(saved).toHaveBeenCalledOnce();expect(api.createMonitorGroup).not.toHaveBeenCalled();
});
test('actual prefilled input value is editable by segment and keyed types keep drafts across remove/reselect',async()=>{
 await mount();expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('80');
 await select('ping');await select('udp');await select('http');await select('https');
 expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('80/53/80/443');
 await input('端口','8080/5353/8000/8443');await select('udp');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('8080/8000/8443');await select('tcp');await select('udp');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('5353/8000/8443');await select('tcp');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('8080/5353/8000/8443');
 await input('监控项名称','服务');await input('目标','example.com');expect(host.textContent).toContain('https://example.com:8443');
});
