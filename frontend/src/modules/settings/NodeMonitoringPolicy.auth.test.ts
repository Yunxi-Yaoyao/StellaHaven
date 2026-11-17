import {defineComponent,createApp,h,KeepAlive,nextTick,ref,type App} from 'vue';
import {it,expect,vi,beforeEach,afterEach} from 'vitest';
import Panel from './NodeMonitoringPolicySettings.vue';
import {auth,security,securityChecked,clearSecurity} from '../home/auth';
import * as policy from '../../api/nodeMonitoringPolicy';
import * as servers from '../../api/servers';
vi.mock('../../api/nodeMonitoringPolicy',()=>({getEntryMonitoring:vi.fn(),getNodeMonitoringPolicy:vi.fn(),putNodeMonitoringPolicy:vi.fn(),pauseNodeMonitoring:vi.fn()}));
vi.mock('../../api/servers',()=>({listNodes:vi.fn()}));
const entries=[{entry_id:'public',origin:'https://main.example',hostname:'main.example',version:'a'.repeat(24)}];
const node={id:2,name:'真实来源',status:'online',components:{monitoring:{ready:true,types:['ping']}},control_channel:null};
let app:App|undefined,host:HTMLElement;
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
function unlock(){securityChecked.value=true;Object.assign(security,{enabled:true,configured:true,elevated:true,expires_at:null});}
beforeEach(()=>{auth.me={id:'owner'} as never;auth.suspended=false;auth.sessionClosing=false;clearSecurity();securityChecked.value=true;security.setup_required=false;vi.mocked(policy.getEntryMonitoring).mockResolvedValue(entries as never);vi.mocked(servers.listNodes).mockResolvedValue([node] as never);});
afterEach(()=>{app?.unmount();host?.remove();clearSecurity();vi.clearAllMocks();vi.unstubAllGlobals();});
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp(Panel);app.component('RouterLink',defineComponent({setup(_, {slots}){return ()=>h('a',slots.default?.());}}));app.mount(host);await settle();}
it('authenticated owner shows mechanism status with no second unlock, strategy form or save',async()=>{
 await mount();expect(host.textContent).not.toContain('解锁管理');
 expect(policy.getEntryMonitoring).toHaveBeenCalledTimes(1);expect(host.querySelector('form,input,select')).toBeNull();
 expect(host.textContent).toContain('默认入口');expect(host.textContent).toContain('等待首个样本');
 expect(policy.putNodeMonitoringPolicy).not.toHaveBeenCalled();expect(policy.getNodeMonitoringPolicy).not.toHaveBeenCalled();
});
it('rejects stale reads across request epoch and reloads the same unlocked session',async()=>{
 let resolve!:(v:unknown)=>void;
 vi.mocked(servers.listNodes).mockImplementationOnce(()=>new Promise(r=>{resolve=r as never;}));
 unlock();await mount();auth.requestEpoch++;await settle();resolve([{...node,name:'过期来源'}]);await settle();
 expect(policy.getEntryMonitoring).toHaveBeenCalledTimes(2);expect(host.textContent).toContain('真实来源');expect(host.textContent).not.toContain('过期来源');
});
it('session suspension hides data and same-owner login reloads without management elevation',async()=>{
 await mount();auth.suspended=true;auth.requestEpoch++;await settle();expect(host.textContent).toContain('请登录');expect(host.textContent).not.toContain('真实来源');
 auth.suspended=false;await settle();expect(policy.getEntryMonitoring).toHaveBeenCalledTimes(2);
});
it('refreshes after KeepAlive reactivation',async()=>{
 unlock();const shown=ref(true);host=document.createElement('div');document.body.append(host);app=createApp({render:()=>h(KeepAlive,()=>shown.value?h(Panel):null)});app.component('RouterLink',defineComponent({setup(_, {slots}){return ()=>h('a',slots.default?.());}}));app.mount(host);await settle();
 shown.value=false;await settle();shown.value=true;await settle();expect(policy.getEntryMonitoring).toHaveBeenCalledTimes(2);
});
it('legacy security readback is not a prerequisite for an authenticated owner',async()=>{
 clearSecurity();vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({enabled:true,configured:true,elevated:true,expires_at:null,single_user:true,setup_required:false})}));
 await mount();expect(host.textContent).toContain('真实来源');
 expect(policy.getEntryMonitoring).toHaveBeenCalledTimes(1);expect(fetch).not.toHaveBeenCalled();
});
it('keeps ICMP and actual report transactions distinct and marks stale data',async()=>{
 const sampled_at=new Date(Date.now()-600000).toISOString();
 vi.mocked(servers.listNodes).mockResolvedValue([{...node,control_channel:{report:{entry_id:'public',origin:'https://main.example',duration_ms:37.5,status:'error',error:'timeout',http_status:null,sampled_at},icmp:[{...entries[0],status:'complete',sampled_at,results:[{ip:'192.168.1.2',family:4,status:'up',latency_ms:1.5,loss_pct:0}]}]}}] as never);
 unlock();await mount();expect(host.textContent).toContain('37.50 ms');expect(host.textContent).toContain('192.168.1.2');expect(host.textContent).toContain('1.50 ms');expect(host.textContent).toContain('已过期');expect(host.textContent).toContain('上一笔');
});
