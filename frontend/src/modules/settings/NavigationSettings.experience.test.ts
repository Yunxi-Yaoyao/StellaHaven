import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import NavigationSettings from './NavigationSettings.vue';
import {api} from '../../api/client';
import {navigation,resetNavigation,type Website,type WebsiteSummary} from '../../stores/navigation';
import {toasts} from '../../composables/useToast';
import receipt from '../../../tests/fixtures/websiteLowconfigReceipt.json';
vi.mock('../../api/client',()=>({api:vi.fn()}));
vi.mock('./IconPicker.vue',()=>({default:{render:()=>null}}));
let app:App,host:HTMLDivElement,entries:any[],hold:boolean,release:()=>void;
function summary(item:Website):WebsiteSummary {const {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id}=item;return {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id};}
const snapshot=(modules:WebsiteSummary[]=[],revision=1,mutation_id:string|null=null)=>({entries,modules,legacy_routes:{},revision,mutation_id});
async function flush(){for(let i=0;i<80;i++)await Promise.resolve();await nextTick();}
async function mount(){const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:NavigationSettings}]});await router.push('/settings?section=navigation');host=document.createElement('div');document.body.append(host);app=createApp(NavigationSettings).use(router);app.mount(host);await flush();}
function button(name:string){return [...host.querySelectorAll('button')].find(b=>b.textContent===name||b.getAttribute('aria-label')===name)!;}
beforeEach(()=>{Element.prototype.scrollIntoView=vi.fn();resetNavigation();toasts.splice(0);vi.clearAllMocks();entries=[{id:'home',title:'个人主页',icon:'home',visible:true},{id:'nav',title:'导航',icon:'compass',visible:true},{id:'notes',title:'笔记',icon:'note',visible:true},{id:'status',title:'服务器',icon:'server',visible:true},{id:'settings',title:'设置',icon:'settings',visible:true}];hold=false;navigation.entries=entries;navigation.loaded=true;
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path==='/navigation'&&options?.method==='PUT'){const body=JSON.parse(options.body as string);entries=body.entries;if(hold)await new Promise<void>(r=>{release=r;});return snapshot([],body.expected_revision+1,body.mutation_id);}
  if(path==='/navigation')return snapshot();
  throw new Error('Unexpected API '+path);
 });
});
afterEach(()=>{app?.unmount();host?.remove();document.body.replaceChildren();resetNavigation();});
it('acknowledges navigation only once after the canonical save ACK and closes a confirmed builtin edit without inline success',async()=>{
 await mount();button('编辑 笔记').click();await flush();const name=host.querySelector<HTMLInputElement>('[aria-label="显示名称"]')!;name.value='我的笔记';name.dispatchEvent(new Event('input'));hold=true;button('保存').click();await flush();expect(toasts).toHaveLength(0);expect(host.querySelector('.builtin-editor')).not.toBeNull();release();await flush();
 expect(toasts.map(t=>t.text)).toEqual(['导航已同步']);expect(host.textContent).not.toContain('导航已同步');expect(host.querySelector('.builtin-editor')).toBeNull();expect(navigation.entries.find(e=>e.id==='notes')?.title).toBe('我的笔记');
 expect(vi.mocked(api).mock.calls.map(([path,options])=>[path,options?.method])).toEqual([['/navigation','PUT']]);
});
it('retains the child through authoritative delete readback so it acknowledges once before its row disappears',async()=>{
 const item=structuredClone(receipt.before);navigation.modules=[summary(item as Website)];let deleted=false;let finishNavigation!:()=>void;
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path==='/external-modules/'+item.id&&options?.method==='DELETE'){deleted=true;return;}
  if(path==='/external-modules/'+item.id){if(deleted)throw {status:404};return structuredClone(item);}
  if(path==='/navigation'){await new Promise<void>(resolve=>{finishNavigation=resolve;});return snapshot(deleted?[]:[summary(item as Website)]);}
  throw Error('Unexpected API '+path);
 });
 await mount();button('编辑 '+item.name).click();await flush();button('删除网站入口').click();await flush();
 [...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='确认删除入口')!.click();await flush();
 expect(toasts).toHaveLength(0);expect(host.querySelector('.inline-editor')).not.toBeNull();expect(host.querySelector(`[data-row-id="${item.id}"]`)).not.toBeNull();
 finishNavigation();await flush();
 expect(toasts.map(t=>t.text)).toEqual(['网站入口已删除']);expect(host.querySelector('.inline-editor')).toBeNull();expect(host.textContent).not.toContain('网站入口已删除');
 expect(host.querySelector(`[data-row-id="${item.id}"]`)).toBeNull();expect(vi.mocked(api).mock.calls.map(([path])=>path)).toEqual(['/external-modules/'+item.id,'/external-modules/'+item.id,'/external-modules/'+item.id,'/navigation']);
});
it('keeps delete recovery inline when the authoritative navigation still contains the deleted website',async()=>{
 const item=structuredClone(receipt.before);navigation.modules=[summary(item as Website)];let deleted=false;
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path==='/external-modules/'+item.id&&options?.method==='DELETE'){deleted=true;return;}
  if(path==='/external-modules/'+item.id){if(deleted)throw {status:404};return structuredClone(item);}
  if(path==='/navigation')return snapshot([summary(item as Website)]);
  throw Error('Unexpected API '+path);
 });
 await mount();button('编辑 '+item.name).click();await flush();button('删除网站入口').click();await flush();
 [...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='确认删除入口')!.click();await flush();
 expect(toasts).toHaveLength(0);expect(host.textContent).toContain('删除结果尚未确认');expect(host.querySelector('.inline-editor')).not.toBeNull();
});
it('keeps a mismatched canonical navigation ACK inline rather than acknowledging unconfirmed changes',async()=>{
 await mount();vi.mocked(api).mockImplementation(async(path,options)=>{if(path==='/navigation'&&options?.method==='PUT'){const body=JSON.parse(options.body as string);return snapshot([],body.expected_revision+1,body.mutation_id);}throw Error('Unexpected API '+path);});
 button('下移 个人主页').click();await flush();expect(toasts).toHaveLength(0);expect(host.textContent).toContain('导航未保存，保留修改，请重试');
});
it('keeps navigation failure inline and does not claim success',async()=>{
 await mount();vi.mocked(api).mockRejectedValueOnce(new Error('offline'));button('下移 个人主页').click();await flush();expect(toasts).toHaveLength(0);expect(host.textContent).toContain('导航未保存，保留修改，请重试');
});
