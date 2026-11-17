import {it,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
import Alerts from './AlertsView.vue';
let app:ReturnType<typeof createApp>|undefined;
const flush=async()=>{for(let i=0;i<16;i++){await Promise.resolve();await nextTick();}};
function button(text:string){return [...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text||b.getAttribute('aria-label')===text)!;}
function baseApi(path:string){
 if(path==='/nodes/')return Promise.resolve([{id:12,name:'fixture HK',status:'online'}]);
 if(path.includes('map-topology'))return Promise.resolve({links:[]});
 if(path.startsWith('/alerts/incidents'))return Promise.resolve({items:[],total:0,limit:30,offset:0});
 return Promise.resolve([]);
}
async function mount(){
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]});await router.push('/status?view=alerts');
 const el=document.createElement('div');document.body.append(el);app=createApp(Alerts);app.use(router);app.mount(el);await flush();
}
it('keeps discovered and manual WG choices distinct and sends explicit user-selected direction',async()=>{
 mocks.api.mockImplementation((path:string,options:any)=>options?.method==='POST'?Promise.resolve({id:1}):baseApi(path));
 await mount();button('添加告警').click();await flush();button('WG 链路中断').click();await flush();
 const mode=document.querySelector<HTMLSelectElement>('[aria-label="WG 目标来源"]');expect(mode).toBeTruthy();
 mode!.value='manual';mode!.dispatchEvent(new Event('change'));await flush();
 const select=document.querySelector<HTMLSelectElement>('[aria-label="WG 源节点"]')!;select.value='12';select.dispatchEvent(new Event('change'));
 for(const [label,value] of [['本地 WG 接口','wg-real'],['目标 WG IPv4','10.42.0.2']]){
   const input=document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;input.value=value;input.dispatchEvent(new Event('input'));
 }
 await flush();button('添加').click();await flush();
 const call=mocks.api.mock.calls.find(([path,opts]:any)=>path==='/alerts/rules'&&opts?.method==='POST')!;
 expect(JSON.parse(call[1].body)).toMatchObject({kind:'wg_link',target:'',wg_manual:{node_id:12,interface:'wg-real',target:'10.42.0.2'}});
 expect(document.body.textContent).not.toContain('手动端点尚未接入');
});
it('renders manual direction freshness and does not label missing data recovered',async()=>{
 mocks.api.mockImplementation((path:string)=>path==='/alerts/rules'?Promise.resolve([{id:1,kind:'wg_link',target:'manual:synthetic',label:'fixture',severity:'warning',state:'firing',enabled:true,email:false,debounce:1,repeat_minutes:30,wg_manual:{node_id:12,interface:'wg0',target:'10.42.0.2'},wg_observation:{health:'unknown',reason:'missing_or_expired_probe',checked_at:null}}]):baseApi(path));
 await mount();expect(document.body.textContent).toContain('手动单向');expect(document.body.textContent).toContain('10.42.0.2');expect(document.body.textContent).toContain('未知');expect(document.body.textContent).toContain('不代表恢复');
 expect(document.querySelector('.state-dot')?.getAttribute('title')).toContain('未知');
});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.resetAllMocks();});
