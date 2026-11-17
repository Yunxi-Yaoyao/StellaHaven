import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Management from './MonitorManagement.vue';
import Editor from './MonitorGroupEditor.vue';
import * as api from '../../api/servers';
import {auth} from '../home/auth';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false})}));
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),listMonitorChecks:vi.fn(),removeMonitor:vi.fn(),dissolveMonitorGroup:vi.fn()}));
const member={id:7,name:'节点 A · 完整名称',node_id:1,type:'tcp',target:'owned.example:443',interval:60,timeout:5,status:'up',visible:true,enabled:true};
const solo={...member,id:8,name:'独立服务',visible:false,enabled:false};
const group={id:2,name:'服务组',child_ids:[7],eligible_child_ids:[7],up_count:1,down_count:0,unknown_count:0,status:'up',failure_policy:'any',rotation_seconds:0,visible:true,enabled:true};
let app:ReturnType<typeof createApp>,host:HTMLElement;
const editGroup=vi.fn(),editMonitor=vi.fn(),saved=vi.fn(),changed=vi.fn();
async function settle(){for(let i=0;i<30;i++)await nextTick();}
async function click(text:string){const b=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();await settle();}
async function mount(which:'management'|'editor'='management',extra:any={}){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>which==='management'?h(Management,{open:true,onEditGroup:editGroup,onEditMonitor:editMonitor,onChanged:changed,...extra}):h(Editor,{monitors:[member,solo] as any,groups:[group] as any,nodes:[{id:1,name:'节点 A'}],nodeName:()=> '节点 A',initialGroupId:2,onSaved:saved,...extra})});app.mount(host);await settle();}
beforeEach(()=>{vi.resetAllMocks();Object.assign(auth,{me:{id:'owner'},suspended:false,sessionClosing:false});vi.mocked(api.listMonitors).mockResolvedValue([member,solo] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);vi.mocked(api.listMonitorChecks).mockResolvedValue([]);for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();});
test('group settings show type/target and secondary menus, then switch to the shared item editor',async()=>{
 await mount('editor');const row=host.querySelector('.child-row')!;expect(row.querySelector('.child-target')?.textContent).toBe('TCP · owned.example:443');expect(row.querySelector('[role=switch]')).toBeNull();expect(row.querySelector('[aria-haspopup=menu]')).toBeTruthy();expect(row.textContent).not.toContain('采样详情');await click('编辑');expect(host.querySelector('[aria-label="编辑监控项"]')).toBeTruthy();expect(host.querySelector<HTMLInputElement>('[aria-label="目标"]')?.value).toBe('owned.example');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('443');expect(host.querySelector('[aria-label="超时（秒）"]')).toBeTruthy();
});
test('member toggle ACK/read failure locks writes and retries GET only',async()=>{
 await mount('editor');host.querySelector<HTMLButtonElement>('[aria-haspopup=menu]')!.click();await settle();vi.mocked(api.updateMonitor).mockResolvedValue({...member,visible:false} as any);vi.mocked(api.listMonitors).mockRejectedValueOnce(new Error('offline')).mockResolvedValue([{...member,visible:false},solo] as any);await click('隐藏于总览');expect(api.updateMonitor).toHaveBeenCalledOnce();expect(host.textContent).toContain('未确认');await click('重新读取确认');expect(api.updateMonitor).toHaveBeenCalledOnce();
});
test('standalone editor reads back ACK without replay, preserves readonly automatic target and history is another dialog',async()=>{
 await mount('editor',{initialGroupId:null,initialMonitorId:7});expect(host.querySelector('.item-window')).toBeTruthy();vi.mocked(api.updateMonitor).mockResolvedValue(member as any);vi.mocked(api.listMonitors).mockRejectedValueOnce(new Error('offline')).mockResolvedValue([member,solo] as any);await click('保存');expect(saved).not.toHaveBeenCalled();await click('重新读取确认');expect(api.updateMonitor).toHaveBeenCalledOnce();expect(saved).toHaveBeenCalledOnce();await click('查看历史');expect(host.querySelector('[aria-label="监控项历史"]')?.getAttribute('open')).not.toBeNull();expect(host.querySelector('select')).toBeNull();
});
test('automatic item keeps protected fields readonly; receipt survives same-owner login suspension',async()=>{
 await mount('editor',{initialGroupId:null,initialMonitorId:7,monitors:[{...member,management:'entry_icmp'}]});expect(host.querySelector<HTMLInputElement>('[aria-label="目标"]')?.readOnly).toBe(true);expect(host.querySelector<HTMLInputElement>('[aria-label="超时（秒）"]')?.readOnly).toBe(true);vi.mocked(api.updateMonitor).mockResolvedValue(member as any);vi.mocked(api.listMonitors).mockRejectedValueOnce(new Error('auth read failed')).mockResolvedValue([member] as any);await click('保存');expect(api.updateMonitor).toHaveBeenCalledExactlyOnceWith(7,{name:member.name});auth.suspended=true;await settle();expect(host.querySelector<HTMLDialogElement>('.item-window')?.open).toBe(false);auth.suspended=false;await settle();await click('重新读取确认');expect(api.updateMonitor).toHaveBeenCalledOnce();expect(saved).toHaveBeenCalledOnce();
});
test('fixed-column tabs directly edit groups or standalone items without nested members',async()=>{
 await mount();expect(host.querySelectorAll('[role=tab]')).toHaveLength(2);expect(host.querySelector('.child-row')).toBeNull();expect(host.textContent).toContain('服务组');expect(host.textContent).not.toContain(member.name);host.querySelector<HTMLButtonElement>('.group-row [aria-haspopup=menu]')!.click();await settle();await click('编辑监控组');expect(editGroup).toHaveBeenCalledWith(2);await click('独立监控 1');expect(host.textContent).toContain('独立服务');expect(host.textContent).not.toContain('服务组');await click('编辑');expect(editMonitor).toHaveBeenCalledWith(8);expect(host.querySelectorAll('[role=switch]')).toHaveLength(2);
});
