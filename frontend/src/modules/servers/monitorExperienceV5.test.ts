import {auth} from '../home/auth';
import {beforeEach,afterEach, expect, test, vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Picker from './MonitorChildPicker.vue';
import Editor from './MonitorGroupEditor.vue';
import * as api from '../../api/servers';
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),createMonitorGroup:vi.fn(),getMonitorGroupReceipt:vi.fn(),listMonitors:vi.fn(),listMonitorGroups:vi.fn()}));
const monitor={id:21,name:'new item',node_id:7,type:'ping',target:'one.example',interval:60,timeout:5,status:'unknown'};
const group={id:8,name:'new group',child_ids:[21],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:1};
let app:ReturnType<typeof createApp>,host:HTMLDivElement;
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Editor,{monitors:[{...monitor,name:'existing item'}] as any,groups:[{...group,name:'existing group'}] as any,nodeName:()=> 'node',nodes:[{id:7,name:'node'}]})});app.mount(host);await settle();}
function input(label:string,value:string){const el=host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;expect(el,label).toBeTruthy();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}
async function button(text:string){const el=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(el,text).toBeTruthy();el!.click();await settle();}
// Current user request overrides forced grouping; the atomic group contract
// remains unchanged when group mode is explicitly selected.
async function draft(){await button('监控组');input('监控组名称','new group');input('监控项名称','new item');input('目标','one.example');input('端口','443');await settle();}
beforeEach(()=>{auth.me={id:'fixture-owner'} as any;auth.suspended=false;auth.sessionClosing=false;for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.clearAllMocks();});
test('item picker shows the specific failure reason instead of unknown or legacy hierarchy',async()=>{
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Picker,{modelValue:21,children:[monitor,{...monitor,id:22,status_reason:'outside_scope'}] as any,seconds:0,parentName:'group'})});app.mount(host);await settle();host.querySelector<HTMLButtonElement>('button')!.click();await settle();expect(document.querySelector('[role=listbox]')?.textContent).toContain('目标范围受限');expect(document.querySelector('[role=listbox]')?.innerHTML).not.toContain('子项');
});
test('new-item sampling configuration is optional and collapsed rather than crowding the basic form',async()=>{
 await mount();const sampling=host.querySelector<HTMLDetailsElement>('details');expect(sampling).toBeTruthy();expect(sampling!.open).toBe(false);expect(sampling!.textContent).toContain('采样设置');
});
test('invalid TCP target stays in the draft and shows an actionable port error without POST',async()=>{
 await mount();await draft();input('端口','');await settle();await button('创建监控');expect(api.createMonitorGroup).not.toHaveBeenCalled();expect(host.querySelector('[role=alert]')?.textContent).toContain('端口');
});
test('creation contains only a new group and new item draft, one atomic POST then exact readback',async()=>{
 vi.mocked(api.createMonitorGroup).mockResolvedValue(group as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);vi.mocked(api.listMonitors).mockResolvedValue([monitor] as any);
 await mount();expect(host.querySelectorAll('input[type=checkbox]:checked')).toHaveLength(1);expect(host.textContent).not.toContain('编辑对象');expect(host.textContent).not.toContain('existing');
 await draft();expect(api.createMonitorGroup).not.toHaveBeenCalled();await button('创建监控');
 expect(api.createMonitorGroup).toHaveBeenCalledTimes(1);expect(api.createMonitorGroup).toHaveBeenCalledWith(expect.objectContaining({name:'new group',items:[expect.objectContaining({name:'new item',target:'one.example:443',node_id:7})],request_key:expect.any(String)}),expect.any(Function));
});
test.each([401,403,404,500])('new-group committed POST then GET %s never sends a second POST',async status=>{
 vi.mocked(api.createMonitorGroup).mockResolvedValue(group as any);vi.mocked(api.listMonitorGroups).mockReset().mockRejectedValueOnce({status}).mockResolvedValue([group] as any);vi.mocked(api.listMonitors).mockResolvedValue([monitor] as any);
 await mount();await draft();await button('创建监控');expect(host.querySelector('[role=alert]')).toBeTruthy();await button('重新读取确认');expect(api.createMonitorGroup).toHaveBeenCalledTimes(1);
});
test('unknown new-group POST recovers only using session receipt GET, never infers success by name',async()=>{
 vi.mocked(api.createMonitorGroup).mockRejectedValue(new TypeError('lost response'));vi.mocked(api.getMonitorGroupReceipt).mockRejectedValueOnce({status:404}).mockResolvedValue({group_id:8,monitor_ids:[21]});vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);vi.mocked(api.listMonitors).mockResolvedValue([monitor] as any);
 await mount();await draft();await button('创建监控');await button('重新读取确认');expect(host.querySelector('[role=alert]')).toBeTruthy();expect((host.querySelector('[aria-label="监控组名称"]') as HTMLInputElement).value).toBe('new group');
 await button('重新读取确认');expect(api.createMonitorGroup).toHaveBeenCalledTimes(1);expect(api.getMonitorGroupReceipt).toHaveBeenCalledTimes(2);
});
