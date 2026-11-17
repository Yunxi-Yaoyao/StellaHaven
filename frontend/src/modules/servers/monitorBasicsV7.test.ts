import {auth} from '../home/auth';
import {beforeEach,afterEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import Editor from './MonitorGroupEditor.vue';
import * as api from '../../api/servers';
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),createMonitor:vi.fn(),createMonitorBatch:vi.fn(),getMonitorBatchReceipt:vi.fn(),createMonitorGroup:vi.fn(),listMonitors:vi.fn(),listMonitorGroups:vi.fn()}));
const item={id:21,name:'独立项',node_id:7,type:'tcp',target:'solo.example:443',interval:60,timeout:5,status:'down',status_reason:'pending'};
let app:ReturnType<typeof createApp>,host:HTMLDivElement;
const saved=vi.fn(),close=vi.fn();
async function settle(){for(let i=0;i<40;i++)await Promise.resolve();await nextTick();}
async function mount(routed=false){
 host=document.createElement('div');document.body.append(host);
 const component={render:()=>h(Editor,{monitors:[],groups:[],nodes:[{id:7,name:'探测节点'}],nodeName:()=> '探测节点',onSaved:saved,onClose:close})};
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component},{path:'/other',component:{render:()=>null}}]});await router.push('/');
 app=createApp(routed?{render:()=>h(RouterView)}:component);app.use(router);app.mount(host);await settle();return router;
}
function input(label:string,value:string){const el=host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;expect(el,label).toBeTruthy();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}
async function button(text:string){const b=[...host.querySelectorAll('button')].find(b=>b.textContent?.trim()===text);expect(b,text).toBeTruthy();b!.click();await settle();}
async function draft(){input('监控项名称','独立项');input('目标','solo.example');input('端口','443');await settle();}
function submit(){host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));return settle();}
beforeEach(()=>{auth.me={id:'fixture-owner'} as any;auth.suspended=false;auth.sessionClosing=false;for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.resetAllMocks();});
test('default standalone creates one item, no group name or implicit group, and waits for GET',async()=>{
 vi.mocked(api.createMonitorBatch).mockResolvedValue({group_id:null,monitor_ids:[21]});vi.mocked(api.listMonitors).mockResolvedValue([item] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);
 await mount();expect(host.querySelector('[aria-label="监控组名称"]')).toBeNull();expect(host.textContent).toContain('独立监控项');await draft();await submit();
 expect(api.createMonitorBatch).toHaveBeenCalledExactlyOnceWith({items:[{name:item.name,type:item.type,target:item.target,node_id:7,interval:60,timeout:5}],group_id:null,expected_group_uuid:null,request_key:expect.any(String)},expect.any(Function));expect(api.createMonitorGroup).not.toHaveBeenCalled();expect(saved).toHaveBeenCalledOnce();
});
test('mode switching preserves separate solo and multi-item group drafts',async()=>{
 await mount();await draft();await button('监控组');input('监控组名称','两项组');input('监控项名称','组内项');host.querySelector<HTMLInputElement>('input[value=udp]')!.click();await settle();await button('独立监控项');expect((host.querySelector('[aria-label="监控项名称"]') as HTMLInputElement).value).toBe('独立项');await button('监控组');expect((host.querySelector('[aria-label="监控组名称"]') as HTMLInputElement).value).toBe('两项组');expect((host.querySelector('[aria-label="监控项名称"]') as HTMLInputElement).value).toBe('组内项');expect(host.querySelector<HTMLInputElement>('input[value=udp]')!.checked).toBe(true);
});
test('ACK followed by GET 403 remains pending and only GET is retried',async()=>{
 vi.mocked(api.createMonitorBatch).mockResolvedValue({group_id:null,monitor_ids:[21]});vi.mocked(api.listMonitors).mockRejectedValueOnce({status:403}).mockResolvedValue([item] as any);
 const router=await mount(true);await draft();await submit();expect(saved).not.toHaveBeenCalled();expect(host.textContent).toContain('创建尚未确认');await router.push('/other');expect(router.currentRoute.value.path).toBe('/');await button('重新读取确认');expect(api.createMonitorBatch).toHaveBeenCalledOnce();expect(api.listMonitors).toHaveBeenCalledTimes(2);expect(saved).toHaveBeenCalledOnce();
});
test('lost POST cannot be identified by name; reread never unlocks or repeats POST',async()=>{
 vi.mocked(api.createMonitorBatch).mockRejectedValue(new TypeError('lost ACK'));vi.mocked(api.listMonitors).mockResolvedValue([item] as any);vi.mocked(api.listMonitorGroups).mockResolvedValue([]);
 const router=await mount(true);await draft();await submit();expect(host.textContent).toContain('创建尚未确认');await button('重新读取确认');await button('重新读取确认');expect(api.createMonitorBatch).toHaveBeenCalledOnce();expect(saved).not.toHaveBeenCalled();expect(host.querySelector('[aria-label="监控项名称"]')!.matches(':disabled')).toBe(true);await router.push('/other');expect(router.currentRoute.value.path).toBe('/');await button('取消');expect(close).not.toHaveBeenCalled();
});
test.each(['solo','group'])('invalid %s draft never POSTs and retains target',async mode=>{
 await mount();if(mode==='group'){await button('监控组');input('监控组名称','组');}await draft();input('目标','1:1');await submit();expect(api.createMonitorBatch).not.toHaveBeenCalled();expect(api.createMonitorGroup).not.toHaveBeenCalled();expect(host.querySelector('[role=alert]')?.textContent).toContain('IPv6');expect((host.querySelector('[aria-label="目标"]') as HTMLInputElement).value).toBe('1:1');
});
test.each(['solo','group'])('definite POST rejection in %s keeps editable draft and permits corrected submission',async mode=>{
 vi.mocked(api.createMonitorBatch).mockRejectedValue({status:422,detail:'节点不存在'});vi.mocked(api.createMonitorGroup).mockRejectedValue({status:422,detail:'节点不存在'});
 await mount();if(mode==='group'){await button('监控组');input('监控组名称','组');}await draft();await submit();expect(host.textContent).toContain('节点不存在');expect((host.querySelector('[aria-label="监控项名称"]') as HTMLInputElement).disabled).toBe(false);expect(saved).not.toHaveBeenCalled();
});
test.each(['solo','group'])('shared numeric sampling validation blocks bypassed native form in %s',async mode=>{
 await mount();if(mode==='group'){await button('监控组');input('监控组名称','组');}await draft();const el=host.querySelector<HTMLInputElement>('input[type=number]')!;el.value='9';el.dispatchEvent(new Event('input',{bubbles:true}));await submit();expect(api.createMonitorBatch).not.toHaveBeenCalled();expect(api.createMonitorGroup).not.toHaveBeenCalled();
});
