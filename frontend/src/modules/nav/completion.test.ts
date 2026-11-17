import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import {defaults} from './controller';
import {auth} from '../home/auth';
import {forgetNavDraft} from './drafts';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
vi.mock('../home/auth',async()=>{const {reactive,computed,ref}=await import('vue');const auth=reactive({me:{id:'completion-owner'},sessionGeneration:1,requestEpoch:1});return {auth,loggedIn:computed(()=>!!auth.me),displayBg:ref('')};});
vi.mock('../../stores/navigation',()=>({navigation:{modules:[{id:'docs',name:'Docs'}]}}));
vi.mock('../home/backgroundMedia',async()=>{const {ref}=await import('vue');return {useBackgroundMedia:()=>({source:ref(''),poster:ref('')})};});
vi.mock('../../composables/useToast',()=>({toast:vi.fn()}));
vi.mock('./realtime',()=>({watchNavRevision:()=>()=>{}}));
import Page from './NavPage.vue';
let app:ReturnType<typeof createApp>,host:HTMLDivElement;
const flush=async()=>{for(let i=0;i<20;i++)await nextTick();};
function button(name:string,scope:ParentNode=document){return [...scope.querySelectorAll('button')].find(b=>b.textContent?.trim()===name||b.getAttribute('aria-label')===name) as HTMLButtonElement;}
beforeEach(()=>{mocks.api.mockReset();HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open')};});
afterEach(()=>{app?.unmount();host?.remove();forgetNavDraft('completion-owner');});
it('import preview offers explicit per-card module binding, invalidates consent on change, and sends the chosen mapping',async()=>{
 const data=defaults();data.groups=[{id:crypto.randomUUID(),title:'Migrated',icon:'',description:'',style:null,items:[{id:crypto.randomUUID(),title:'Card',url:'https://example.test',lanUrl:'',description:'',icon:null,openMethod:2,module_id:null}]}];
 let server={revision:0,data:defaults()},sent:any;
 mocks.api.mockImplementation(async(path:string,options?:RequestInit)=>{
  if(path==='/nav-assets')return [];
  if(path==='/nav-package-preview')return {data,revision:0,digest:'d',counts:{groups:1,items:1,assets:0,bytes:0},warnings:[]};
  if(path==='/nav-package-import'){sent=JSON.parse(options!.body as string);server={revision:1,data:JSON.parse(JSON.stringify(data))};server.data.groups[0]!.items[0]!.module_id=sent.module_bindings[data.groups[0]!.items[0]!.id];return server;}
  if(path==='/nav-data')return server;
  throw new Error('unexpected '+path);
 });
 host=document.createElement('div');document.body.append(host);app=createApp(Page);app.use(createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]}));app.mount(host);await flush();
 button('导航设置',host).click();await flush();button('数据工具',host).click();await flush();
 const source=host.querySelector('textarea')!;source.value='{}';source.dispatchEvent(new Event('input',{bubbles:true}));await flush();button('完整包预览（不写入）',host).click();await flush();
 const label='迁移网站 Card 的模块绑定';expect(button(label,host)).toBeTruthy();
 const confirm=host.querySelector('.nav-import-preview input[type=checkbox]') as HTMLInputElement;confirm.click();await flush();
 button(label,host).click();await flush();(document.querySelector('[role=option][data-value="docs"]') as HTMLButtonElement||[...document.querySelectorAll('[role=option]')].find(e=>e.textContent==='Docs') as HTMLButtonElement).click();await flush();
 expect(confirm.checked).toBe(false);confirm.click();await flush();button('确认原子导入',host).click();await flush();
 expect(sent.module_bindings).toEqual({[data.groups[0]!.items[0]!.id]:'docs'});
});
it('SPA leave and same-owner relogin retain a private draft; other owner and cancellation cannot expose it',async()=>{
 const server={revision:0,data:defaults()};mocks.api.mockImplementation(async(path:string)=>path==='/nav-assets'?[]:JSON.parse(JSON.stringify(server)));
 const mount=async()=>{host=document.createElement('div');document.body.append(host);app=createApp(Page);app.use(createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]}));app.mount(host);await flush();};
 await mount();button('导航设置',host).click();await flush();const input=[...host.querySelectorAll('label')].find(e=>e.textContent==='导航标题')!.querySelector('input')!;input.value='PRIVATE unsaved';input.dispatchEvent(new Event('input',{bubbles:true}));await flush();
 app.unmount();host.remove();await mount();expect(button('恢复未保存导航草稿',host)).toBeTruthy();
 (auth as any).me={id:'other-owner'};await flush();expect(button('恢复未保存导航草稿',host)).toBeUndefined();expect(host.textContent).not.toContain('PRIVATE unsaved');
 (auth as any).me={id:'completion-owner'};auth.sessionGeneration++;await flush();button('恢复未保存导航草稿',host).click();await flush();expect(host.querySelector('dialog[open] input')?.getAttribute('type')).not.toBe('hidden');expect(( [...host.querySelectorAll('dialog[open] label')].find(e=>e.textContent==='导航标题')!.querySelector('input') as HTMLInputElement).value).toBe('PRIVATE unsaved');
 (auth as any).me=null;auth.sessionGeneration++;await flush();expect(host.textContent).not.toContain('PRIVATE unsaved');
 (auth as any).me={id:'completion-owner'};auth.sessionGeneration++;await flush();button('恢复未保存导航草稿',host).click();await flush();expect(( [...host.querySelectorAll('dialog[open] label')].find(e=>e.textContent==='导航标题')!.querySelector('input') as HTMLInputElement).value).toBe('PRIVATE unsaved');button('取消',host).click();await flush();
 app.unmount();host.remove();await mount();expect(button('恢复未保存导航草稿',host)).toBeUndefined();expect(mocks.api.mock.calls.every(([,o])=>!o?.method||o.method==='GET')).toBe(true);
});
