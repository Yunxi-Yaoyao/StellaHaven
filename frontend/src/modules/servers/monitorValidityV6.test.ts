import {auth} from '../home/auth';
import {beforeEach,afterEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Editor from './MonitorGroupEditor.vue';
import Detail from './MonitorDetailModal.vue';
import {monitorTarget,monitorTargetError} from './monitorTarget';
import {monitorStatusLabel,monitorStatusReason} from './monitorStatusLabel';
import * as api from '../../api/servers';
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),createMonitorGroup:vi.fn(),updateMonitor:vi.fn(),listMonitors:vi.fn(),getMonitorSeries:vi.fn(async()=>[])}));
vi.mock('./chartRuntime',()=>({init:vi.fn(()=>({setOption:vi.fn(),resize:vi.fn(),dispose:vi.fn()}))}));
test.each([['tcp','1:1'],['udp','999.1.2.3:53'],['tcp','bad_host:80'],['tcp','::1:443'],['tcp','host:0'],['ping','123'],['ping','host:80'],['ping','https://host'],['ping','host/path'],['ping','ho\nst'],['https','http://host'],['http','http://user:secret@host'],['http','http://1'],['https','https://host:65536'],['http','http://host\\evil'],['tcp','host:4 43'],['tcp','[192.168.1.2]:443'],['ping','fe80::1%eth0'],['ping','host?query'],['ping','host#fragment']])('offline feedback rejects %s %s',(type,target)=>{expect(monitorTargetError(type,target)).not.toBe('');});
test.each([['tcp','nas:443','nas:443'],['tcp','[2001:db8::1]:443','[2001:db8::1]:443'],['ping','2001:db8::1','2001:db8::1'],['ping','例子.测试','xn--fsqu00a.xn--0zwm56d'],['https','https://[2001:db8::1]:8443/path?q=1','https://[2001:db8::1]:8443/path?q=1']])('offline feedback accepts %s %s',(type,target,value)=>{expect(monitorTarget(type,target)).toBe(value);});
test.each([['invalid_target','配置无效'],['scope_pending','尚未取得探测结果（待节点确认目标范围）'],['unsupported','节点不支持此探测'],['stale','过久未取得有效采样']])('short reason %s',(reason,label)=>{const m={status:'down',status_reason:reason} as any;expect(monitorStatusLabel(m)).toBe('异常');expect(monitorStatusReason(m)).toBe(label);});

let app:ReturnType<typeof createApp>,host:HTMLDivElement;
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
function input(el:HTMLInputElement,value:string){el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}
beforeEach(()=>{auth.me={id:'fixture-owner'} as any;auth.suspended=false;auth.sessionClosing=false;for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});});
afterEach(()=>{app?.unmount();host?.remove();vi.clearAllMocks();});
test('new group rejects 1:1 immediately beside retained draft and never POSTs',async()=>{
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Editor,{monitors:[],groups:[],nodes:[{id:7,name:'node'}],nodeName:()=> 'node'})});app.mount(host);await settle();
 [...host.querySelectorAll('button')].find(b=>b.textContent?.trim()==='监控组')!.click();await settle();
 for(const [label,value] of [['监控组名称','group'],['监控项名称','1'],['目标','1:1']])input(host.querySelector(`[aria-label="${label}"]`)!,value);
 await settle();expect(host.querySelector('[role=alert]')?.textContent).toContain('IPv6');
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();expect(api.createMonitorGroup).not.toHaveBeenCalled();expect((host.querySelector('[aria-label="目标"]') as HTMLInputElement).value).toBe('1:1');
});
test('legacy invalid item remains editable; unchanged invalid target does not block rename',async()=>{
 const m={id:1,name:'1',node_id:7,type:'tcp',target:'1:1',interval:60,timeout:5,status:'unknown',status_reason:'invalid_target'};
 vi.mocked(api.updateMonitor).mockResolvedValue({...m,name:'2'} as any);vi.mocked(api.listMonitors).mockResolvedValue([{...m,name:'2'}] as any);
 host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(Detail,{monitor:m as any,nodeName:'node',initialTab:'edit'})});app.mount(host);await settle();
 expect(host.textContent).toContain('配置无效');input(host.querySelector('.edit-body input')!,'2');await settle();
 [...host.querySelectorAll('button')].find(b=>b.textContent?.trim()==='保存')!.click();await settle();
 expect(api.updateMonitor).toHaveBeenCalledWith(1,{name:'2',interval:60});
});
