import {createApp,h,nextTick,type App} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import {isAdmin} from '../home/auth';
import {it,expect,vi,afterEach} from 'vitest';
import {api} from '../../api/client';
vi.mock('../../api/client',()=>({api:vi.fn()}));
vi.mock('../home/auth',async()=>{const {ref}=await import('vue');return {isAdmin:ref(true)};});
let app:App|undefined;
afterEach(()=>{app?.unmount();document.body.replaceChildren();vi.restoreAllMocks();});
const flush=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};
it('shows both entry addresses without an enable gate, then checks, applies and reads back explicitly',async()=>{
 const modules=import.meta.glob('./AccessEntrySettings.vue');expect(modules['./AccessEntrySettings.vue']).toBeDefined();
 const Component=(await modules['./AccessEntrySettings.vue']!() as {default:object}).default;
 let settings={revision:0,enabled:false,public_origin:'https://stella.test',private_origin:'https://stella.p.test'};
 const summary=()=>({settings:{...settings},issuer:'https://issuer.test',deployed:{public:settings.public_origin,private:settings.private_origin},websites:[]});
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path==='/config/access-entries/check')return {can_apply:true,digest:'a'.repeat(64),checks:[{name:'公网主站',status:'configured',reason:'已部署'}],network:{dns:'unknown',tls:'unknown',browser:'unknown'},behavior:'跟随当前入口'} as never;
  if(options?.method==='PUT'){const incoming=JSON.parse(String(options.body));settings={revision:incoming.revision+1,enabled:incoming.enabled,public_origin:incoming.public_origin,private_origin:incoming.private_origin};}
  return summary() as never;
 });
 const root=document.createElement('div');document.body.append(root);
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:Component}]});await router.push('/settings?section=access');
 app=createApp({render:()=>h(RouterView)});app.use(router);app.mount(root);await flush();
 const button=(text:string)=>[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!;
 expect(root.querySelector('[role=switch]')).toBeNull();
 expect(root.textContent).not.toContain('原站 / 客户端两侧配置示例');
 expect(root.textContent).not.toContain('入口与网站详情');expect(root.querySelector('.deployment-details')).toBeNull();
 expect(root.querySelector<HTMLInputElement>('[aria-label="其他入口地址"]')?.value).toBe(settings.private_origin);
 expect(button('应用设置')).toBeUndefined();
 const publicAddress=root.querySelector<HTMLInputElement>('[aria-label="默认入口地址"]')!;publicAddress.value='https://new-stella.test';publicAddress.dispatchEvent(new Event('input'));await flush();
 button('检查设置').click();await flush();expect(button('应用设置').disabled).toBe(false);expect(root.textContent).not.toContain('公网主站');
 expect(vi.mocked(api).mock.calls.some(([,o])=>o?.method==='PUT')).toBe(false);
 button('应用设置').click();await flush();expect(root.textContent).toContain('已应用');
 expect(settings.private_origin).toBe('https://stella.p.test');
});
const base={revision:0,enabled:false,public_origin:'https://stella.test',private_origin:'https://stella.p.test'};
const value=(settings={...base})=>({settings,issuer:'https://issuer.test',deployed:{public:base.public_origin,private:base.private_origin},websites:[]});
async function realMount(){
 (isAdmin as {value:boolean}).value=true;
 const Component=(await import('./AccessEntrySettings.vue')).default;
 const root=document.createElement('div');document.body.append(root);
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:Component},{path:'/outside',component:{render:()=>null}}]});
 await router.push('/settings?section=access');app=createApp({render:()=>h(RouterView)});app.use(router);app.mount(root);await flush();
 return {root,router,button:(text:string)=>[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!};
}
it('rebases a retained conflict draft to the explicitly read current revision before another check',async()=>{
 vi.mocked(api).mockResolvedValue(value() as never);
 const {root,button}=await realMount();
 const address=root.querySelector<HTMLInputElement>('[aria-label="其他入口地址"]')!;address.value='https://new-private.test';address.dispatchEvent(new Event('input'));await flush();
 vi.mocked(api).mockRejectedValueOnce({status:409});button('检查设置').click();await flush();
 vi.mocked(api).mockResolvedValueOnce(value({...base,revision:4}) as never);button('回读设置').click();await flush();
 button('检查设置').click();await flush();
 const last=vi.mocked(api).mock.calls.filter(([path])=>path.endsWith('/check')).at(-1)!;
 expect(JSON.parse(String(last[1]?.body))).toMatchObject({revision:4,private_origin:'https://new-private.test'});
});
it('ignores a management read that completes after lock-back',async()=>{
 let resolve!:(v:unknown)=>void;vi.mocked(api).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}) as never);
 const {root}=await realMount();(isAdmin as {value:boolean}).value=false;await flush();resolve(value());await flush();
 expect(root.querySelector('form')).toBeNull();expect(root.textContent).not.toContain('https://issuer.test');
});
it('guards same-route section changes while dirty, preserving or explicitly discarding only the draft',async()=>{
 vi.mocked(api).mockResolvedValue(value() as never);
 const {root,router}=await realMount();const address=root.querySelector<HTMLInputElement>('[aria-label="其他入口地址"]')!;address.value='https://new-private.test';address.dispatchEvent(new Event('input'));await flush();
 let settled=false;const navigation=router.push('/settings?section=navigation').then(()=>{settled=true;});await flush();
 expect(settled).toBe(false);expect(document.querySelector('[aria-label="保留入口地址草稿"]')).not.toBeNull();
 [...document.querySelectorAll('button')].find(b=>b.textContent==='继续编辑')!.click();await navigation;
 expect(router.currentRoute.value.query.section).toBe('access');
});
