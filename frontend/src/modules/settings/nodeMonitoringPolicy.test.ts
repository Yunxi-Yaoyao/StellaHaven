import {test,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick,h,defineComponent} from 'vue';
import Panel from './NodeMonitoringPolicySettings.vue';
import * as policy from '../../api/nodeMonitoringPolicy';
import {auth,security,securityChecked,clearSecurity} from '../home/auth';
vi.mock('../../api/nodeMonitoringPolicy',()=>({getEntryMonitoring:vi.fn(),getNodeMonitoringPolicy:vi.fn(),putNodeMonitoringPolicy:vi.fn(),pauseNodeMonitoring:vi.fn()}));
vi.mock('../../api/servers',()=>({listNodes:vi.fn(async()=>[{id:2,name:'测试节点 A',status:'online',components:null,control_channel:null}])}));
let app:ReturnType<typeof createApp>|undefined,host:HTMLElement;
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
afterEach(()=>{app?.unmount();host?.remove();clearSecurity();vi.resetAllMocks();});
test('read failure is explicit and retry loads truthful old-Agent unknown without a fake enable action',async()=>{
 auth.me={id:'owner'} as never;auth.suspended=false;auth.sessionClosing=false;securityChecked.value=true;Object.assign(security,{enabled:true,elevated:true,expires_at:null});
 vi.mocked(policy.getEntryMonitoring).mockRejectedValueOnce(new Error('offline')).mockResolvedValue([{entry_id:'public',origin:'https://main.example',hostname:'main.example',version:'a'.repeat(24)}]);
 host=document.createElement('div');document.body.append(host);app=createApp(Panel);app.component('RouterLink',defineComponent({setup(_,{slots}){return ()=>h('a',slots.default?.());}}));app.mount(host);await settle();
 expect(host.textContent).toContain('读取失败');expect(host.querySelector('form,input,select')).toBeNull();
 [...host.querySelectorAll('button')].find(b=>b.textContent==='重新读取结果')!.click();await settle();
 expect(host.textContent).toContain('等待 Agent 提供监控能力');expect(host.textContent).toContain('尚未提供真实汇报耗时');expect(host.textContent).not.toContain('自动启用');
 expect(policy.getNodeMonitoringPolicy).not.toHaveBeenCalled();expect(policy.putNodeMonitoringPolicy).not.toHaveBeenCalled();
});
