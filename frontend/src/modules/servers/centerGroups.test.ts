import { beforeEach, afterEach, expect, test, vi } from 'vitest';
import { createApp, h, nextTick } from 'vue';
import Editor from './MonitorGroupEditor.vue';
import Detail from './MonitorDetailModal.vue';
import Navigation from '../settings/SettingsNavigation.vue';
import Channel from './NodeCenterChannel.vue';
import AdminElevation from '../../shell/AdminElevationModal.vue';
import { auth, clearSecurity } from '../home/auth';
import * as api from '../../api/servers';
vi.mock('./chartRuntime',()=>({init:()=>({setOption(){},resize(){},dispose(){}})}));
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),
 listMonitorGroups:vi.fn(),listMonitors:vi.fn(),createMonitorGroupChild:vi.fn(),updateMonitor:vi.fn(),removeMonitor:vi.fn(),
 getMonitorSeries:vi.fn(async()=>[]),listMonitorMtr:vi.fn(async()=>[]),saveMonitorGroup:vi.fn(),
}));
const group={id:4,name:'节点 → 中心',child_ids:[],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:0,automatic:true,source_node_id:7};
const monitor={id:10,name:'入口 ICMP',node_id:7,type:'ping',target:'192.168.160.3',interval:60,timeout:1,status:'unknown',management:'entry_icmp'};
let app:ReturnType<typeof createApp>, host:HTMLDivElement;
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
async function mount(component:any,props:any){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(component,props)});app.component('RouterLink',{render(){return h('a');}});app.mount(host);await settle();}
async function button(text:string){const el=[...host.querySelectorAll('button')].find(e=>e.textContent?.trim()===text);expect(el,text).toBeTruthy();el!.click();await settle();}
beforeEach(()=>{auth.me={id:'synthetic-owner'} as any;auth.suspended=false;auth.sessionClosing=false;for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.clearAllMocks();vi.unstubAllGlobals();clearSecurity();auth.me=null;auth.suspended=false;auth.sessionClosing=false;});
async function draft(){
 await button('新建监控项');
 for(const [label,value] of [['监控项名称','receipt draft'],['监控项目标','owned:443']]){const el=host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;el.value=value!;el.dispatchEvent(new Event('input',{bubbles:true}));}await settle();
}
test('legacy empty group opens by id but cannot save an empty group',async()=>{
 await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}]});
 expect((host.querySelector('input[maxlength]') as HTMLInputElement).value).toBe(group.name);
 expect((([...host.querySelectorAll('button')].find(e=>e.textContent==='保存设置')) as HTMLButtonElement).disabled).toBe(true);
});
test('group editor creates a real child with explicit source then reads probe and membership back',async()=>{
 vi.mocked(api.createMonitorGroupChild).mockResolvedValue({...monitor,management:undefined} as any);
 vi.mocked(api.listMonitors).mockResolvedValue([monitor] as any);
 vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[10]}] as any);
 await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}]});
 await button('新建监控项');
 const name=host.querySelector('[aria-label="监控项名称"]') as HTMLInputElement;expect(name).toBeTruthy();name.value='manual';name.dispatchEvent(new Event('input',{bubbles:true}));
 const target=host.querySelector('[aria-label="监控项目标"]') as HTMLInputElement;target.value='192.168.160.3:443';target.dispatchEvent(new Event('input',{bubbles:true}));await settle();
 await button('创建并加入');
 expect(api.createMonitorGroupChild).toHaveBeenCalledWith(4,expect.objectContaining({name:'manual',node_id:7,target:'192.168.160.3:443'}));
 expect(api.listMonitors).toHaveBeenCalled();expect(api.listMonitorGroups).toHaveBeenCalled();
});
test('group settings save metadata without rewriting an obsolete membership snapshot',async()=>{
 const current={...group,child_ids:[10,11]};vi.mocked(api.saveMonitorGroup).mockResolvedValue(current as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([current] as any);
 await mount(Editor,{monitors:[monitor],groups:[{...group,child_ids:[10]}],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}]});
 const form=host.querySelector('form')!;form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();expect(api.saveMonitorGroup).toHaveBeenCalledTimes(1);expect(vi.mocked(api.saveMonitorGroup).mock.calls[0][1]).not.toHaveProperty('child_ids');
});
test('automatic child exposes name edit but sampling inputs are read-only, and errors persist',async()=>{
 vi.mocked(api.updateMonitor).mockRejectedValue({detail:'自动入口目标不能修改'});
 await mount(Detail,{monitor,nodeName:'node',initialTab:'edit'});
 expect(host.querySelector('.mdl-tabs .active')?.textContent).toBe('编辑');
 expect(host.textContent).toContain('固定每 60 秒');
 expect((host.querySelector('.edit-body input[type=number]') as HTMLInputElement).disabled).toBe(true);
 await button('保存');expect(api.updateMonitor).toHaveBeenCalledWith(10,{name:'入口 ICMP'});
 expect(host.querySelector('[role=alert]')?.textContent).toContain('自动入口目标不能修改');
});
test('settings navigation has no desktop or mobile servers option',async()=>{
 await mount(Navigation,{section:'profile'});expect(host.innerHTML).not.toContain('section=servers');expect(host.textContent).not.toContain('服务器');
});
test('node details retain report transaction as a different measurement and explain missing ICMP',async()=>{
 await mount(Channel,{node:{status:'online',components:{monitoring:{ready:true,types:['ping']}},control_channel:{report:{duration_ms:25,status:'ok',http_status:200,origin:'https://main.example',sampled_at:new Date().toISOString()},icmp:[{entry_id:'public',status:'outside_scope',sampled_at:new Date().toISOString(),results:[]}]}},now:Date.now()});
 expect(host.textContent).toContain('汇报事务');expect(host.textContent).toContain('25.00 ms');expect(host.textContent).toContain('目标范围');expect(host.textContent).not.toContain('RTT');
});
test('unconfirmed child creation retries readback without creating a duplicate',async()=>{
 vi.mocked(api.createMonitorGroupChild).mockResolvedValue(monitor as any);
 vi.mocked(api.listMonitors).mockRejectedValueOnce(new Error('read offline')).mockResolvedValue([monitor] as any);
 vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[10]}] as any);
 await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}]});
 await button('新建监控项');
 for(const [label,value] of [['监控项名称','new child'],['监控项目标','owned:443']]){const el=host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;el.value=value!;el.dispatchEvent(new Event('input',{bubbles:true}));}await settle();
 await button('创建并加入');expect(host.querySelector('[role=alert]')).toBeTruthy();
 await button('重新确认创建结果');expect(api.createMonitorGroupChild).toHaveBeenCalledTimes(1);expect(api.listMonitors).toHaveBeenCalledTimes(2);
});
test.each([401,403,404,500])('committed child receipt survives GET %s and retries only GET',async status=>{
 vi.mocked(api.listMonitorGroups).mockReset();
 vi.mocked(api.createMonitorGroupChild).mockResolvedValue(monitor as any);
 vi.mocked(api.listMonitors).mockResolvedValue([monitor] as any);
 vi.mocked(api.listMonitorGroups).mockRejectedValueOnce({status,detail:'read denied'}).mockRejectedValueOnce({status}).mockResolvedValue([{...group,child_ids:[10]}] as any);
 const changed=vi.fn(),saved=vi.fn(),close=vi.fn();
 await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}],onChanged:changed,onSaved:saved,onClose:close});
 await button('新建监控项');
 for(const [label,value] of [['监控项名称','receipt draft'],['监控项目标','owned:443']]){const el=host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;el.value=value!;el.dispatchEvent(new Event('input',{bubbles:true}));}await settle();
 await button('创建并加入');
 expect(host.textContent).toContain('重新确认创建结果');
 expect((host.querySelector('[aria-label="监控项名称"]') as HTMLInputElement).value).toBe('receipt draft');
 expect(changed).not.toHaveBeenCalled();expect(saved).not.toHaveBeenCalled();
 await button('重新确认创建结果');expect(api.createMonitorGroupChild).toHaveBeenCalledTimes(1);
 await button('取消新建');expect(host.querySelector('.child-form')).toBeTruthy();
 await button('取消');host.querySelector<HTMLButtonElement>('[aria-label="关闭监控组设置"]')!.click();
 host.querySelector('.group-dialog')!.dispatchEvent(new MouseEvent('click',{bubbles:true}));
 host.querySelector('.group-dialog')!.dispatchEvent(new Event('cancel',{bubbles:true,cancelable:true}));await settle();
 expect(close).not.toHaveBeenCalled();
 await button('重新确认创建结果');expect(api.createMonitorGroupChild).toHaveBeenCalledTimes(1);
 expect(changed).toHaveBeenCalledTimes(1);expect(saved).not.toHaveBeenCalled();expect(host.querySelector('.child-form')).toBeNull();
});
test('Escape closes the nested child editor without closing the parent manager',async()=>{
 await mount(Editor,{monitors:[monitor],groups:[{...group,child_ids:[10]}],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}]});
 await button('编辑');expect(host.querySelector('.item-window')).toBeTruthy();
 host.querySelector('.item-window')!.dispatchEvent(new Event('cancel',{bubbles:true,cancelable:true}));await settle();
 expect(host.querySelector('.item-window')).toBeNull();expect(host.querySelector('.group-dialog')).toBeTruthy();
});
test('unknown POST followed by denied GET never releases receipt even after auth recovery',async()=>{
 vi.mocked(api.createMonitorGroupChild).mockReset().mockRejectedValue(new TypeError('network lost after commit'));
 vi.mocked(api.listMonitorGroups).mockReset().mockRejectedValueOnce({status:401}).mockResolvedValue([{...group,child_ids:[10]}] as any);
 vi.mocked(api.listMonitors).mockReset().mockResolvedValue([monitor] as any);
 const close=vi.fn(),changed=vi.fn(),saved=vi.fn();
 await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}],onClose:close,onChanged:changed,onSaved:saved});await draft();
 await button('创建并加入');expect(api.listMonitorGroups).not.toHaveBeenCalled();
 await button('重新确认创建结果');expect(api.listMonitorGroups).toHaveBeenCalledTimes(1);
 auth.suspended=true;await settle();auth.suspended=false;auth.requestEpoch++;await settle();
 await button('重新确认创建结果');await button('重新确认创建结果');
 expect(api.createMonitorGroupChild).toHaveBeenCalledTimes(1);expect(changed).not.toHaveBeenCalled();expect(saved).not.toHaveBeenCalled();
 expect(host.textContent).toContain('关闭或重新登录不代表可以安全重建');
 const unload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(unload);expect(unload.defaultPrevented).toBe(true);
 await button('取消新建');host.querySelector('.group-dialog')!.dispatchEvent(new Event('cancel',{bubbles:true,cancelable:true}));await settle();expect(close).not.toHaveBeenCalled();expect(host.querySelector('.child-form')).toBeTruthy();
});
test('held readback does not clear drafts, emit saved/changed, or admit concurrent POST; exact membership required',async()=>{
 let release!:(value:any)=>void;
 vi.mocked(api.createMonitorGroupChild).mockReset().mockResolvedValue(monitor as any);
 vi.mocked(api.listMonitors).mockReset().mockResolvedValue([monitor] as any);
 vi.mocked(api.listMonitorGroups).mockReset().mockImplementationOnce(()=>new Promise(r=>release=r)).mockResolvedValue([{...group,child_ids:[10]}] as any);
 const changed=vi.fn(),saved=vi.fn(),close=vi.fn();
 await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}],onChanged:changed,onSaved:saved,onClose:close});await draft();
 await button('创建并加入');await button('重新确认创建结果');await button('取消新建');await button('取消');
 expect(api.createMonitorGroupChild).toHaveBeenCalledTimes(1);expect(changed).not.toHaveBeenCalled();expect(saved).not.toHaveBeenCalled();expect(close).not.toHaveBeenCalled();
 expect((host.querySelector('[aria-label="监控项名称"]') as HTMLInputElement).value).toBe('receipt draft');
 release([{...group,child_ids:[]}]);await settle();expect(changed).not.toHaveBeenCalled();expect(host.querySelector('.child-form')).toBeTruthy();
 await button('重新确认创建结果');expect(changed).toHaveBeenCalledTimes(1);expect(saved).not.toHaveBeenCalled();expect(api.createMonitorGroupChild).toHaveBeenCalledTimes(1);
 await button('取消');expect(close).toHaveBeenCalledTimes(1);
});
test('cancelling a never-submitted child and closing parent remain available',async()=>{
 const close=vi.fn();await mount(Editor,{monitors:[],groups:[group],nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}],onClose:close});await draft();await button('取消新建');expect(host.querySelector('.child-form')).toBeNull();
 host.querySelector('.group-dialog')!.dispatchEvent(new Event('cancel',{bubbles:true,cancelable:true}));await settle();expect(close).toHaveBeenCalledTimes(1);expect(api.createMonitorGroupChild).not.toHaveBeenCalled();
});
test.each([400,403])('definite POST %s rejection permits only an explicit retry, never admin elevation',async status=>{
 const actual=await vi.importActual<typeof import('../../api/servers')>('../../api/servers');
 vi.mocked(api.createMonitorGroupChild).mockReset().mockImplementation(actual.createMonitorGroupChild);
 vi.mocked(api.listMonitorGroups).mockReset().mockResolvedValue([{...group,child_ids:[10]}] as any);
 vi.mocked(api.listMonitors).mockReset().mockResolvedValue([monitor] as any);
 auth.me={id:'synthetic-owner'} as any;auth.suspended=false;auth.sessionClosing=false;
 let posts=0,unlocks=0;
 vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{
  if(path==='/auth/admin/unlock'){expect(JSON.parse(String(options?.body))).toEqual({password:''});unlocks++;return Response.json({ok:true});}
  if(path==='/auth/security')return Response.json({enabled:true,configured:true,elevated:true,expires_at:null,single_user:true,setup_required:false});
  expect(path).toBe('/monitors/groups/4/children');expect(options?.method).toBe('POST');posts++;
  if(posts===1)return Response.json({detail:status===400?'definitely rejected':{code:'admin_elevation_required'}},{status});
  if(posts===2)return Response.json({detail:{code:'admin_elevation_required'}},{status:403});
  return Response.json(monitor,{status:201});
 }));
 const changed=vi.fn();await mount({render:()=>h('div',[h(Editor,{monitors:[],groups:[group] as any,nodeName:()=> 'node',initialGroupId:4,nodes:[{id:7,name:'node'}],onChanged:changed}),h(AdminElevation)])},{});await draft();await button('创建并加入');
 expect(document.querySelector('.admin-dialog')).toBeNull();
 expect(host.textContent).toContain('创建并加入');expect(changed).not.toHaveBeenCalled();expect(posts).toBe(1);
 await button('创建并加入');expect(document.querySelector('.admin-dialog')).toBeNull();expect(posts).toBe(2);
 expect(changed).not.toHaveBeenCalled();expect(unlocks).toBe(0);
 await button('创建并加入');
 expect(posts).toBe(3);expect(changed).toHaveBeenCalledTimes(1);expect(host.querySelector('.child-form')).toBeNull();
});
