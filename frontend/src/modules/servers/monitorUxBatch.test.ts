import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Editor from './MonitorGroupEditor.vue';
import Item from './MonitorItemEditor.vue';
import Management from './MonitorManagement.vue';
import * as api from '../../api/servers';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},suspended:false,sessionClosing:false,requestEpoch:0,sessionGeneration:0})}));
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),removeMonitor:vi.fn(),updateMonitor:vi.fn(),saveMonitorGroup:vi.fn(),dissolveMonitorGroup:vi.fn(),listMonitorChecks:vi.fn(),getMonitorGroupDeletionState:vi.fn()}));
const member={id:7,name:'服务',node_id:1,type:'https',target:'https://example.com:8443/a%2Fb?q=1#x',interval:60,timeout:5,status:'up'};
const group={id:2,name:'业务组',child_ids:[7],failure_policy:'any',rotation_seconds:0,status:'up',down_count:0,unknown_count:0};
let app:ReturnType<typeof createApp>,host:HTMLElement;
async function settle(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
async function mount(kind:string,extra:any={}){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>kind==='group'?h(Editor,{monitors:[member] as any,groups:[group] as any,initialGroupId:2,nodeName:()=> '节点',nodes:[{id:1,name:'节点'}],...extra}):kind==='item'?h(Item,{monitor:member as any,nodeName:'节点',...extra}):h(Management,{open:true,...extra})});app.mount(host);await settle();}
async function click(text:string,root:ParentNode=host){const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();await settle();}
beforeEach(()=>{vi.resetAllMocks();vi.mocked(api.listMonitors).mockResolvedValue([member] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);for(const [method,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,method,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();});
test('group operation row has only one menu trigger, which exposes edit/delete; system group has no deletion',async()=>{
 await mount('management');const row=host.querySelector('.group-row')!;expect(row.querySelectorAll('.row-actions>button')).toHaveLength(0);expect(row.querySelector('button.edit')).toBeNull();
 row.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click();await settle();expect(host.textContent).toContain('删除监控组');expect(host.textContent).toContain('编辑监控组');
});
test('existing group opens standalone native create window, no stacked child form, and has whole-group delete',async()=>{
 await mount('group');await click('新建监控项');expect(host.querySelector<HTMLDialogElement>('[aria-label="新建监控项"]')?.open).toBe(true);expect(host.querySelector('.child-form')).toBeNull();expect(host.querySelector<HTMLDialogElement>('.group-dialog')?.open).toBe(false);
 await click('取消',host.querySelector('[aria-label="新建监控项"]')!);expect(host.querySelector<HTMLDialogElement>('.group-dialog')?.open).toBe(true);host.querySelector<HTMLButtonElement>('[aria-label="监控组操作"]')!.click();await settle();expect(host.textContent).toContain('删除监控组');
});
test('clearing an existing port cannot silently send a default, even bypassing native form validation',async()=>{
 await mount('item');const port=host.querySelector<HTMLInputElement>('[aria-label="端口"]')!;port.value='';port.dispatchEvent(new Event('input',{bubbles:true}));await settle();host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();expect(api.updateMonitor).not.toHaveBeenCalled();expect(host.textContent).toContain('端口');
});
test('existing item splits host/port and retains legacy URL suffix on host edit',async()=>{
 await mount('item');const target=host.querySelector<HTMLInputElement>('[aria-label="目标"]')!;expect(target.value).toBe('example.com');expect(host.querySelector<HTMLInputElement>('[aria-label="端口"]')?.value).toBe('8443');expect(host.querySelector<HTMLInputElement>('[aria-label="URL 路径、查询与片段"]')?.value).toBe('/a%2Fb?q=1#x');target.value='new.example';target.dispatchEvent(new Event('input',{bubbles:true}));await settle();vi.mocked(api.updateMonitor).mockRejectedValue({status:422});await click('保存');expect(api.updateMonitor).toHaveBeenCalledWith(7,expect.objectContaining({target:'https://new.example:8443/a%2Fb?q=1#x'}));
});
