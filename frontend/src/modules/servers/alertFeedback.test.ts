import {it,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
const mocks=vi.hoisted(()=>({api:vi.fn(),readOne:vi.fn(),refreshList:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
vi.mock('../../stores/notifications',()=>({notifications:{unread:1,items:[{id:9,title:'HK 告警',body:'完整正文',ts:'2026-10-19T00:00:00Z',kind:'alert',link:'/status/12',read:false}]},notificationActions:{readOne:mocks.readOne,refreshList:mocks.refreshList,readAll:vi.fn()}}));
import Alerts from './AlertsView.vue';
import Bell from '../../shell/NotificationBell.vue';
let app:ReturnType<typeof createApp>|undefined;
const flush=async()=>{for(let i=0;i<16;i++){await Promise.resolve();await nextTick();}};
function button(text:string){return [...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text||b.getAttribute('aria-label')===text)!;}
async function mount(component:any){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]});await router.push('/status?view=alerts');
 const el=document.createElement('div');document.body.append(el);app=createApp(component);app.use(router);app.mount(el);await flush();return {el,router};
}
function baseApi(path:string){
 if(path==='/nodes/')return Promise.resolve([{id:12,name:'HK',interfaces:{eth0:{}}}]);
 if(path.includes('map-topology')||path.includes('server-map'))return Promise.resolve({links:[]});
 if(path.startsWith('/alerts/incidents'))return Promise.resolve({items:[],total:0,limit:30,offset:0});
 return Promise.resolve([]);
}
it('uses one add entry and exposes explicit total-volume inputs without the second metric entry',async()=>{
 mocks.api.mockImplementation(baseApi);await mount(Alerts);
 expect(button('添加告警')).toBeTruthy();expect(button('添加指标规则')).toBeUndefined();
 button('添加告警').click();await flush();
 button('累计流量').click();await flush();
 expect(document.body.textContent).toContain('累计流量达到');
 expect(document.body.textContent).toContain('不自动重置');
 expect(document.querySelectorAll('.metrics-panel input[type="datetime-local"]')).toHaveLength(2);
 const metric=document.querySelector<HTMLSelectElement>('.metrics-panel form select:nth-of-type(1)');
 expect(metric).toBeTruthy();
});
it('starts a new legacy rule with email off and describes deadline not report count',async()=>{
 mocks.api.mockImplementation((p:string)=>p==='/alerts/rules'?Promise.resolve([{id:1,kind:'node_offline',target:'12',label:'HK · 上报中断',severity:'warning',email:false,enabled:true,state:'ok',debounce:1,repeat_minutes:0}]):baseApi(p));
 await mount(Alerts);button('添加告警').click();await flush();
 expect(document.querySelector<HTMLInputElement>('.email-check input')!.checked).toBe(false);
 expect(document.querySelector('.rule-meta')!.textContent).toContain('120 秒');
 expect(document.querySelector('.rule-meta')!.textContent).toContain('不重复提醒');
 expect(document.querySelector('.rule-meta')!.textContent).not.toContain('连续 1 次');
});
it('resets new-rule email and keeps never-reported nodes pending',async()=>{
 mocks.api.mockImplementation((p:string)=>p==='/nodes/'?Promise.resolve([{id:12,name:'HK',status:'pending',interfaces:{}}]):p==='/alerts/rules'?Promise.resolve([{id:1,kind:'node_offline',target:'12',label:'HK · 上报中断',severity:'warning',email:false,enabled:true,state:'ok',debounce:1,repeat_minutes:0}]):baseApi(p));
 await mount(Alerts);expect(document.querySelector('.rule-meta')!.textContent).toContain('等待首次上报');
 expect(document.querySelector('.state-dot')!.classList.contains('unknown')).toBe(true);
 button('添加告警').click();await flush();
 const email=document.querySelector<HTMLInputElement>('.email-check input')!;email.checked=true;email.dispatchEvent(new Event('change',{bubbles:true}));await flush();
 button('取消').click();await flush();button('添加告警').click();await flush();
 expect(document.querySelector<HTMLInputElement>('.email-check input')!.checked).toBe(false);
});
it('uses 节点上报中断 consistently in cards rules and history filters',async()=>{
 mocks.api.mockImplementation((p:string)=>p==='/alerts/rules'?Promise.resolve([{id:1,kind:'node_offline',target:'12',label:'HK · 上报中断',severity:'warning',email:false,enabled:true,state:'ok',debounce:1,repeat_minutes:0}]):baseApi(p));
 await mount(Alerts);expect(document.querySelector('.rule .tag')!.textContent).toBe('节点上报中断');
 button('添加告警').click();await flush();expect(button('节点上报中断')).toBeTruthy();
 button('告警记录').click();await flush();
 expect(document.querySelector('option[value="node_offline"]')!.textContent).toBe('节点上报中断');
});
it('separates loading failure from normal and offers current/history pages',async()=>{
 mocks.api.mockImplementation(baseApi);await mount(Alerts);
 expect(button('告警项')).toBeTruthy();expect(button('告警记录')).toBeTruthy();
 expect(document.body.textContent).toContain('当前一切正常喵~');
 app!.unmount();app=undefined;document.body.innerHTML='';
 mocks.api.mockRejectedValue(new Error('offline'));await mount(Alerts);
 expect(document.body.textContent).not.toContain('当前一切正常喵~');expect(document.body.textContent).toContain('加载失败');
});
it('opens a notification detail before navigation and keeps the node link outside buttons',async()=>{
 mocks.api.mockImplementation((p:string)=>p==='/notifications/9'?Promise.resolve({id:9,title:'HK 告警',body:'完整正文',ts:'2026-10-19T00:00:00Z',kind:'alert',context:{incident_id:7},entities:[{type:'node',id:12,label:'HK',available:true}]}):baseApi(p));
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({left:20,right:50,top:10,bottom:40,width:30,height:30,x:20,y:10,toJSON:()=>({})});
 const {router}=await mount(Bell);document.querySelector<HTMLButtonElement>('[aria-label="通知"]')!.click();await flush();
 document.querySelector<HTMLButtonElement>('.item')!.click();await flush();
 expect(router.currentRoute.value.fullPath).toBe('/status?view=alerts');
 const detail=document.querySelector('[data-notification-detail]')!;expect(detail).toBeTruthy();
 expect(detail.textContent).toContain('完整正文');expect(detail.textContent).toContain('发送时间');
 const node=detail.querySelector<HTMLAnchorElement>('a[href="/status/12"]')!;expect(node).toBeTruthy();expect(node.closest('button')).toBeNull();
 expect(mocks.readOne).toHaveBeenCalledWith(9);node.click();await flush();expect(router.currentRoute.value.path).toBe('/status/12');
});
it('does not call incomplete start evidence a healthy empty state',async()=>{
 mocks.api.mockImplementation((p:string)=>p.startsWith('/alerts/incidents')&&p.includes('status=unresolved')?Promise.resolve({items:[],total:0,untracked:[{rule_id:1,label:'旧告警',message:'起始事件记录缺失；未确认恢复'}]}):baseApi(p));
 await mount(Alerts);expect(document.body.textContent).not.toContain('当前一切正常喵~');expect(document.body.textContent).toContain('起始事件记录缺失');
});
it('does not describe an edit watermark as an actual evaluation',async()=>{
 const i={id:1,label:'edited metric',status:'unresolved',kind:'node_metric',severity:'warning',message:'high',started_at:'2026-10-19T00:00:00Z',resolved_at:null,duration_seconds:60,observation:'unknown',evaluated_at:null,watermark:'2026-10-19T01:00:00Z'};
 mocks.api.mockImplementation((p:string)=>p.startsWith('/alerts/incidents')?Promise.resolve({items:[i],total:1}):baseApi(p));await mount(Alerts);
 expect(document.querySelector('[aria-label="当前告警"]')!.textContent).toContain('最后评估 未知');
});
it('mounts the shared current-alert section at the end of the overview',async()=>{
 const {readFile}=await import('node:fs/promises');
 const source=await readFile(process.cwd()+'/src/modules/servers/OverviewView.vue','utf8');
 expect(source).toContain('<AlertIncidentList mode="current"');
 expect(source.indexOf('<AlertIncidentList mode="current"')).toBeGreaterThan(source.indexOf('<!-- 监控项详情浮窗'));
});
it('rule toggle coalesces double clicks, keeps submitted value and exposes failed email updates',async()=>{
 const rule={id:1,kind:'node_offline',target:'12',label:'HK',severity:'warning',email:false,enabled:true,state:'ok',debounce:1,repeat_minutes:0};
 let finish!:(v:any)=>void;
 mocks.api.mockImplementation((p:string,opts?:RequestInit)=>p==='/alerts/rules/1'&&opts?.method==='PATCH'?new Promise(r=>{finish=r;}):p==='/alerts/rules'?Promise.resolve([rule]):baseApi(p));
 await mount(Alerts);const enabled=button('已启用');enabled.click();enabled.click();await flush();
 expect(mocks.api.mock.calls.filter(([p,o])=>p==='/alerts/rules/1'&&o?.method==='PATCH')).toHaveLength(1);expect(enabled.disabled).toBe(true);
 finish({ok:true});await flush();expect(button('已停用')).toBeTruthy();
 mocks.api.mockImplementation((p:string,o?:RequestInit)=>p==='/alerts/rules/1'&&o?.method==='PATCH'?Promise.reject(new Error('fixture email rejected')):baseApi(p));
 button('邮件关').click();await flush();expect(document.body.textContent).toContain('fixture email rejected');expect(button('邮件关').disabled).toBe(false);
});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.restoreAllMocks();vi.resetAllMocks();});
