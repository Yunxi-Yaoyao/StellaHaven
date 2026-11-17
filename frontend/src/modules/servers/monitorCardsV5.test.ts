import {afterEach,expect,test,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import Overview from './OverviewView.vue';
vi.mock('./chartRuntime',()=>({init:()=>({resize(){},setOption(){},dispose(){}}),getInstanceByDom:()=>undefined}));
vi.mock('./ServerWorldMap.vue',()=>({__esModule:true,default:{render:()=>null}}));
vi.mock('./AlertIncidentList.vue',()=>({__esModule:true,default:{render:()=>null}}));
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),listNodes:vi.fn(async()=>[]),listMonitors:vi.fn(async()=>[{id:1,name:'node A → 默认入口',type:'ping',target:'main.example',status:'down',status_reason:'dns_error',node_id:7,interval:60,timeout:1,last_latency_ms:null,last_check_at:null}]),listMonitorGroups:vi.fn(async()=>[{id:5,name:'very long group name',child_ids:[1],failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,unknown_count:0,up_count:0},{id:6,name:'empty must not render',child_ids:[],status:'down',down_count:0,unknown_count:0}]),getMonitorSeries:vi.fn(async()=>[])}));
let app:ReturnType<typeof createApp>,host:HTMLDivElement;
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();});
test('one add action, nonempty card title counters and one settings action, concrete item status',async()=>{
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});Object.defineProperty(document,'hidden',{value:false,configurable:true});
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]});await router.push('/');host=document.createElement('div');document.body.append(host);app=createApp(Overview);app.use(router);app.mount(host);for(let i=0;i<80;i++){await Promise.resolve();await nextTick();}
 const section=host.querySelector('#service-monitors')!;expect(section.querySelector('.block-head')?.textContent).toContain('添加监控');expect(section.textContent).not.toContain('父子');expect(section.textContent).not.toContain('empty must not render');
 const card=section.querySelector('.mon-card')!;expect(card.querySelectorAll('.mon-heading button')).toHaveLength(1);expect(card.querySelector('.mon-count-down')?.textContent).toBe('异常 1');expect(card.querySelector('.mon-count-up')?.textContent).toBe('正常 0');expect(card.querySelector('.mon-latency')?.getAttribute('title')).toBe('异常 · 域名解析失败');expect(card.querySelector('.mon-status-dot')).toBeTruthy();expect(card.textContent).not.toContain('未知');expect(card.querySelector('.mon-diagnosis')).toBeNull();expect(card.querySelector('.mon-inspect')).toBeNull();
});
