import {afterEach, expect, test, vi} from 'vitest';
import {createApp, nextTick} from 'vue';
import {createRouter, createMemoryHistory} from 'vue-router';
import Overview from './OverviewView.vue';
const fixture = vi.hoisted(() => ({status:'down', reason:'pending', grouped:true}));
vi.mock('./chartRuntime',()=>({init:()=>({resize(){},setOption(){},dispose(){}}),getInstanceByDom:()=>undefined}));
vi.mock('./ServerWorldMap.vue',()=>({__esModule:true,default:{render:()=>null}}));
vi.mock('./AlertIncidentList.vue',()=>({__esModule:true,default:{render:()=>null}}));
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),
 listNodes:vi.fn(async()=>[]), getMonitorSeries:vi.fn(async()=>[]),
 listMonitors:vi.fn(async()=>[{id:1,name:'retained probe',node_id:7,type:'ping',target:'192.168.160.4',interval:60,timeout:2,status:fixture.status,status_reason:fixture.reason,last_check_at:null,last_latency_ms:fixture.status==='up'?3:null}]),
 listMonitorGroups:vi.fn(async()=>fixture.grouped?[{id:5,name:'retained group',child_ids:[1],failure_policy:'any',rotation_seconds:0,status:fixture.status,down_count:Number(fixture.status==='down'),up_count:Number(fixture.status==='up'),unknown_count:0}]:[]),
}));
let app:ReturnType<typeof createApp>, host:HTMLDivElement;
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();});
async function mount(){
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}});
 Object.defineProperty(document,'hidden',{value:false,configurable:true});
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]});
 await router.push('/');host=document.createElement('div');document.body.append(host);app=createApp(Overview);app.use(router);app.mount(host);
 for(let i=0;i<80;i++){await Promise.resolve();await nextTick();}
 return host.querySelector('.mon-card')!;
}
test.each([
 ['pending','尚未取得探测结果'],['stale','过久未取得有效采样'],['source_pending','探测节点尚未接入'],
 ['source_offline','探测节点离线'],['invalid_target','配置无效'],['outside_scope','目标范围受限'],
 ['unsupported','节点不支持此探测'],['restricted','探测受限'],['dns_error','域名解析失败'],
 ['scope_pending','尚未取得探测结果（待节点确认目标范围）'],['failure','目标探测失败'],
])('abnormal business result keeps concrete separate cause %s',async(reason,label)=>{
 fixture.status='down';fixture.reason=reason;fixture.grouped=true;
 const card=await mount();const current=card.querySelector('.mon-plot-metrics')!;
 expect(card.querySelector('.mon-count-down')?.textContent).toBe('异常 1');
 expect(card.querySelector('.mon-count-up')?.textContent).toBe('正常 0');
 expect(current.querySelector('.mon-latency')?.getAttribute('aria-label')).toBe(`异常，${label}`);expect(current.querySelector('.mon-status-dot')).not.toBeNull();expect(card.querySelector('.mon-diagnosis,.mon-inspect')).toBeNull();
 expect(current.textContent).not.toMatch(/未知|结果已过期|待首次检测/);
 if(reason!=='failure')expect(current.textContent).not.toContain('目标探测失败');
 expect(current.querySelector('.mon-reason-action')).toBeNull();
});
test.each([true,false])('fresh success stays normal with no abnormal cause, grouped=%s',async grouped=>{
 fixture.status='up';fixture.reason='healthy';fixture.grouped=grouped;
 const card=await mount();expect(card.querySelector('.mon-count-up')?.textContent).toBe('正常 1');
 expect(card.querySelector('.mon-count-down')?.textContent).toBe('异常 0');
 const current=card.querySelector('.mon-plot-metrics')!;expect(current.querySelector('.mon-latency')?.getAttribute('aria-label')).toBe('正常，');
 expect(current.querySelector('.mon-reason')).toBeNull();expect(current.textContent).toContain('3.0 ms');
});
