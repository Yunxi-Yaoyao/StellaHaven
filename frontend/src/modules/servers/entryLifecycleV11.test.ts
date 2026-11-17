import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import Editor from './MonitorGroupEditor.vue';
import Item from './MonitorItemEditor.vue';
import Management from './MonitorManagement.vue';
import * as api from '../../api/servers';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'owner'},suspended:false,sessionClosing:false})}));
vi.mock('../../api/servers',()=>({listMonitors:vi.fn(),listMonitorGroups:vi.fn(),saveMonitorGroup:vi.fn(),updateMonitor:vi.fn(),listMonitorChecks:vi.fn(),removeMonitor:vi.fn(),dissolveMonitorGroup:vi.fn()}));
const member={id:7,name:'source',node_id:1,type:'ping',target:'main.example',interval:60,timeout:1,status:'down',management:'entry_icmp'};
const group={id:2,name:'默认入口探测',child_ids:[7],eligible_child_ids:[7],status:'down',failure_policy:'any',rotation_seconds:0,automatic:true,entry_id:'public',target_origin:'https://main.example'};
let app:ReturnType<typeof createApp>,host:HTMLElement;
async function settle(){for(let i=0;i<30;i++)await nextTick();}
async function mount(component:any,props:any){host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(component,props)});app.mount(host);await settle();}
beforeEach(()=>{vi.resetAllMocks();for(const [name,open] of [['showModal',true],['close',false]] as const)Object.defineProperty(HTMLDialogElement.prototype,name,{configurable:true,value:function(this:HTMLDialogElement){this.open=open;}});vi.mocked(api.listMonitorGroups).mockResolvedValue([group] as any);vi.mocked(api.listMonitors).mockResolvedValue([member] as any);});
afterEach(()=>{app?.unmount();host?.remove();});
test('system editor has readonly single target and no add/move/dissolve action',async()=>{
 await mount(Editor,{monitors:[member],groups:[group],nodeName:()=> 'node',initialGroupId:2});
 expect(host.textContent).toContain('https://main.example');
 expect(host.textContent).not.toContain('新建监控项');
 for(const b of host.querySelectorAll<HTMLButtonElement>('[aria-haspopup=menu]')){b.click();await settle();expect(document.body.textContent).not.toMatch(/移出监控组|解散监控组/);b.click();await settle();}
});
test('empty system editor can save metadata and explains empty state',async()=>{
 const empty={...group,child_ids:[],eligible_child_ids:[],status:null,availability_reason:'no_connected_nodes'};
 vi.mocked(api.listMonitorGroups).mockResolvedValue([empty] as any);
 await mount(Editor,{monitors:[],groups:[empty],nodeName:()=> 'node',initialGroupId:2});
 expect(host.textContent).toContain('暂无接入节点');
 const save=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='保存设置')!;
 expect(save.disabled).toBe(false);save.click();await settle();expect(api.saveMonitorGroup).toHaveBeenCalledOnce();
});
test('automatic item does not expose delete action',async()=>{
 await mount(Item,{monitor:member,nodeName:'node'});
 expect(host.querySelector('[aria-label="监控项操作"]')).toBeNull();
});
test('overview renders visible empty system cards without health or fabricated child',async()=>{
 const source=(await import('./OverviewView.vue?raw')).default;
 expect(source).toContain('v-for="g in monitorGroups.filter');
 expect(source).toContain("g.availability_reason==='entry_not_configured'?'未配置其他入口':'暂无接入节点'");
});

test('management names system action accurately and shows explicit empty reason',async()=>{
 vi.mocked(api.listMonitorGroups).mockResolvedValue([{...group,child_ids:[],eligible_child_ids:[],status:null,availability_reason:'entry_not_configured'}] as any);
 await mount(Management,{open:true});
 expect(host.textContent).toContain('未配置其他入口');
 host.querySelector<HTMLButtonElement>('[aria-label="更多组操作 默认入口探测"]')!.click();await settle();
 expect(document.body.textContent).not.toContain('组设置 / 解散');
});
