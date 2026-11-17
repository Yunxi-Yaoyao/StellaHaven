import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, type App } from 'vue';
import WebsiteSettings from './WebsiteSettings.vue';
import { auth } from '../home/auth';
import { api } from '../../api/client';
import { getWebsite } from '../../api/integrations';
import { checkWebsiteDraft, saveWebsiteDraft, getWebsiteSaveReceipt, getWebsiteTemplates, type WebsiteSaveResult, type WebsiteDraft } from '../../api/websiteSettings';
import { loadNavigation, navigation, resetNavigation, type Website, type WebsiteSummary } from '../../stores/navigation';
import { effectiveWebsiteBackground } from '../../stores/websiteBackground';
import { toasts } from '../../composables/useToast';
vi.mock('../../api/client',()=>({api:vi.fn()}));
vi.mock('../../api/integrations',async importOriginal=>({...await importOriginal<typeof import('../../api/integrations')>(),getWebsite:vi.fn()}));
vi.mock('../../api/websiteSettings',()=>({checkWebsiteDraft:vi.fn(),saveWebsiteDraft:vi.fn(),getWebsiteSaveReceipt:vi.fn(),getWebsiteTemplates:vi.fn(),saveWebsiteTemplate:vi.fn(),deleteWebsiteTemplate:vi.fn()}));
vi.mock('../../shell/Icon.vue',()=>({default:{render:()=>null}}));
vi.mock('./IconPicker.vue',()=>({default:{render:()=>null}}));
vi.mock('../../shell/Dropdown.vue',()=>({default:{props:['modelValue','options'],emits:['update:modelValue'],setup(props:any,{emit}:any){return()=>h('select',{value:props.modelValue,onChange:(e:Event)=>emit('update:modelValue',(e.target as HTMLSelectElement).value)},props.options.map((o:any)=>h('option',{value:o.value},o.label)));}}}));
let app:App,host:HTMLDivElement,item:Website;
const id='editable-synthetic-website';
type SavePayload=WebsiteDraft & {idempotency_key:string};
const builtinEntries=[{id:'home',title:'个人主页',icon:'home',visible:true},{id:'nav',title:'导航',icon:'compass',visible:true},{id:'notes',title:'笔记',icon:'note',visible:true},{id:'status',title:'服务器',icon:'server',visible:true},{id:'settings',title:'设置',icon:'settings',visible:true}];
function summary(website:Website,runtime_revision='runtime-before'):WebsiteSummary & {background?:Website['background'];runtime_revision:string}{
 const {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id,background}=website;
 return {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id,background,runtime_revision};
}
const check=(address:string)=>({can_save:true,normalized_url:address,name_suggestion:'网站',help:null,recommended_behavior:'embedded' as const,embedding:{status:'allowed' as const,reason_code:'allowed',reason:'允许嵌入'},access:{status:'reachable' as const,http_status:200},injection:{status:'supported' as const,reason:'支持'},issues:[]});
function receipt(payload:SavePayload,website=item,runtime='runtime-after'):WebsiteSaveResult{
 return {...website,check:check(website.browser_url),idempotency_key:payload.idempotency_key,navigation:{entries:[...builtinEntries.map(e=>({...e})),{id:website.id,title:website.name,icon:website.icon,visible:payload.visible}],modules:[summary(website,runtime)],legacy_routes:{drive:id},revision:2,mutation_id:payload.idempotency_key}};
}
function persist(payload:SavePayload){
 item={...item,name:payload.name||item.name,icon:payload.icon,browser_url:payload.address,entry_policy:payload.entry_policy,access_adapter:payload.access_adapter,template_id:payload.template_id,
  ...(payload.background!==undefined?{background:payload.background}:{}),
  ...(payload.address_mode!==undefined?{address_mode:payload.address_mode,mapping_configured:true,alternate_address:payload.alternate_address}:{}),
  ...(payload.custom?{injection:{active:{...payload.custom,csp_policy:'reject',version:'new-active'},draft:{...payload.custom,csp_policy:'reject'},previous:null}}:{})};
 return receipt(payload);
}
async function flush(){for(let i=0;i<60;i++)await Promise.resolve();await nextTick();}
async function mount(websiteId:string|undefined=id,onBusy?:(value:boolean)=>void){host=document.createElement('div');document.body.append(host);app=createApp(WebsiteSettings,{id:websiteId,onBusy});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(host);await flush();}
const background=()=>Array.from(host.querySelectorAll('select')).find(s=>s.querySelector('option[value=home]'))!;
async function submit(){host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();}
beforeEach(()=>{
 localStorage.clear();resetNavigation();vi.resetAllMocks();toasts.splice(0);Object.assign(auth,{me:{id:'settings-owner'},sessionClosing:false});
 const code={enabled:false,css:'',js:'',timing:'dom_ready' as const,csp_policy:'reject' as const};
 item={id,name:'网站',icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:'https://child.test/',origin:'https://child.test',enabled:true,keep_alive:true,background:'solid',template_id:null,injection:{active:code,draft:code,previous:null}};
 navigation.loaded=true;navigation.modules=[summary(item)];navigation.legacy_routes={drive:id};
 vi.mocked(getWebsite).mockImplementation(async()=>JSON.parse(JSON.stringify(item)));
 vi.mocked(getWebsiteTemplates).mockResolvedValue([]);
 vi.mocked(checkWebsiteDraft).mockResolvedValue(check(item.browser_url) as any);
 vi.mocked(saveWebsiteDraft).mockImplementation(async(_id,payload)=>persist(payload));
 vi.mocked(getWebsiteSaveReceipt).mockRejectedValue(new Error('No receipt configured'));
 vi.mocked(api).mockImplementation(async(path)=>{if(path!=='/navigation')throw new Error(`Unexpected API ${path}`);return receipt({visible:true,idempotency_key:'initial'} as SavePayload).navigation;});
});
afterEach(()=>{app?.unmount();host?.remove();document.body.replaceChildren();resetNavigation();vi.restoreAllMocks();});
it('hides the direct alternate address while preserving its exact suffix and entry choice',async()=>{
 Object.assign(item,{mode:'iframe',connection:{transport:'direct',auth_mode:'oidc',header_name:'Authorization',injection_delivery:'loader',has_token:false},private_address:'https://child.p.test/library?q=a%2Fb#keep',entry_policy:'follow'});
 vi.mocked(saveWebsiteDraft).mockImplementationOnce(async(_id,payload)=>receipt(payload)); // mismatched policy ACK must not confirm
 await mount();expect(host.querySelector('[aria-label="其他访问地址"]')).toBeNull();
 const policy=Array.from(host.querySelectorAll('select')).find(s=>s.querySelector('option[value=follow]'))!;
 expect(policy.value).toBe('follow');policy.value='public';policy.dispatchEvent(new Event('change'));await flush();
 await submit();const payload=vi.mocked(saveWebsiteDraft).mock.calls[0]![1];expect(payload).not.toHaveProperty('private_address');expect(payload).not.toHaveProperty('connection');expect(payload.entry_policy).toBe('public');expect(item.private_address).toBe('https://child.p.test/library?q=a%2Fb#keep');expect(item.connection?.transport).toBe('direct');
 expect(host.textContent).toContain('保存结果尚未确认'); // fixture deliberately does not persist the changed policy
});
it('does not configure generated proxy addresses and preserves the registered mapping by omission',async()=>{
 Object.assign(item,{private_address:'https://app-alt-dev-synthetic.test',entry_policy:'public',connection:{transport:'proxy',auth_mode:'original',header_name:'Authorization',injection_delivery:'proxy',has_token:false}});
 await mount();
 expect(host.querySelector('[aria-label="其他访问地址"]')).toBeNull();
 const policy=Array.from(host.querySelectorAll('select')).find(s=>s.querySelector('option[value=follow]'))!;
 expect(policy.closest('details')).toBeNull();expect(policy.value).toBe('public');
 expect(policy.querySelector('option[value=public]')?.textContent).toBe('始终使用默认入口');
 await submit();expect(vi.mocked(saveWebsiteDraft).mock.calls[0]?.[1]).not.toHaveProperty('private_address');
 expect(item.private_address).toBe('https://app-alt-dev-synthetic.test');expect(host.textContent).not.toContain('保存结果尚未确认');
});
it('notifies once only after the authoritative canonical website and navigation save ACK',async()=>{
 toasts.splice(0);await mount();
 let finish!:(value:WebsiteSaveResult)=>void;vi.mocked(saveWebsiteDraft).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();
 expect(saveWebsiteDraft).toHaveBeenCalledTimes(1);expect(toasts).toHaveLength(0);
 const payload=vi.mocked(saveWebsiteDraft).mock.calls[0]![1];expect(payload.idempotency_key).toEqual(expect.any(String));
 expect(checkWebsiteDraft).not.toHaveBeenCalled();expect(getWebsite).toHaveBeenCalledTimes(1);expect(api).not.toHaveBeenCalled();expect(getWebsiteSaveReceipt).not.toHaveBeenCalled();
 finish(receipt(payload));await flush();expect(toasts.map(t=>t.text)).toEqual(['网站已保存']);expect(host.textContent).not.toContain('网站已保存');
 expect(navigation.entries).toEqual([...builtinEntries,{id,title:item.name,icon:item.icon,visible:true}]);expect(navigation.revision).toBe(2);
 const retry=[...host.querySelectorAll('button')].find(b=>b.textContent==='重试回读');expect(retry).toBeUndefined();
});
it('does not present missing loader as a viewing failure while custom code is disabled',async()=>{
 await mount('');
 vi.mocked(checkWebsiteDraft).mockResolvedValue({can_save:true,normalized_url:'https://direct.test/',embedding:{status:'allowed',reason:'允许嵌入'},access:{status:'reachable'},injection:{status:'loader_required',reason:'需安装此模块加载器'},issues:[]} as any);
 const address=host.querySelector('[aria-label="网站地址"]') as HTMLInputElement;address.value='https://direct.test/';address.dispatchEvent(new Event('input'));
 Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='检测')!.click();await flush();
 expect(host.textContent).not.toContain('需安装此模块加载器');
 const enable=Array.from(host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')).find(i=>i.parentElement?.textContent?.includes('启用自定义代码'))!;enable.checked=true;enable.dispatchEvent(new Event('change'));
 Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='检测')!.click();await flush();
 expect(host.textContent).toContain('需安装此模块加载器');
});

it('shows the effective local preference and does not silently publish it during a metadata save',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');await mount();expect(background().value).toBe('home');expect(host.textContent).toContain('仅此设备');
 const name=host.querySelector('[aria-label=显示名称]') as HTMLInputElement;name.value='新名称';name.dispatchEvent(new Event('input'));await submit();
 expect(vi.mocked(saveWebsiteDraft).mock.calls[0]?.[1].background).toBeUndefined();expect(item.background).toBe('solid');expect(localStorage.getItem('stella_drive_bg_mode')).toBe('image');
});
it('a confirmed explicit choice clears both legacy keys and survives reopening, even if equal to the effective choice',async()=>{
 localStorage.setItem('stella_drive_bg_mode','solid');localStorage.setItem('__stella_drive_bg_mode__','image');await mount();
 background().value='solid';background().dispatchEvent(new Event('change'));await submit();
 expect(vi.mocked(saveWebsiteDraft).mock.calls[0]?.[1].background).toBe('solid');
 expect(localStorage.getItem('stella_drive_bg_mode')).toBeNull();expect(localStorage.getItem('__stella_drive_bg_mode__')).toBeNull();
 localStorage.setItem('stella_drive_bg_mode','image');expect(effectiveWebsiteBackground(item).mode).toBe('solid');
});
it('publishes the authoritative runtime hash after one save while full active code stays in owned detail',async()=>{
 await mount();const css=host.querySelector<HTMLTextAreaElement>('[aria-label="自定义 CSS"]')!;css.value='body{color:purple}';css.dispatchEvent(new Event('input'));
 expect(navigation.modules[0]).toHaveProperty('runtime_revision','runtime-before');
 await submit();expect(navigation.modules[0]).toHaveProperty('runtime_revision','runtime-after');expect(navigation.modules[0]).not.toHaveProperty('injection');
 expect(getWebsite).toHaveBeenCalledTimes(1);const detail=await getWebsite(id);expect(detail.injection?.active?.version).toBe('new-active');expect(detail.injection?.active?.css).toBe(css.value);
 expect(saveWebsiteDraft).toHaveBeenCalledTimes(1);expect(toasts.map(t=>t.text)).toEqual(['网站已保存']);
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/rollback')||path.endsWith('/apply'))).toBe(false);
});
it('keeps the local preference when the explicit save ACK is inconsistent',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');await mount();background().value='solid';background().dispatchEvent(new Event('change'));
 vi.mocked(saveWebsiteDraft).mockImplementationOnce(async(_id,payload)=>receipt(payload,{...item,background:'home'}));await submit();
 expect(localStorage.getItem('stella_drive_bg_mode')).toBe('image');expect(host.textContent).toContain('尚未确认');
 expect(toasts).toHaveLength(0);expect(getWebsite).toHaveBeenCalledTimes(1);
});
it.each(['website-id','idempotency-key','navigation-revision','navigation-label','navigation-icon','navigation-visible'] as const)('does not clear either legacy preference or toast for a mismatched %s ACK',async field=>{
 localStorage.setItem('stella_drive_bg_mode','image');localStorage.setItem('__stella_drive_bg_mode__','solid');await mount();
 background().value='solid';background().dispatchEvent(new Event('change'));
 vi.mocked(saveWebsiteDraft).mockImplementationOnce(async(_id,payload)=>{
  const ack=persist(payload);
  if(field==='website-id')ack.id='wrong-website';
  if(field==='idempotency-key')ack.idempotency_key='wrong-key';
  if(field==='navigation-revision')ack.navigation.revision=-1;
  if(field==='navigation-label')ack.navigation.entries.at(-1)!.title='wrong-name';
  if(field==='navigation-icon')ack.navigation.entries.at(-1)!.icon='wrong-icon';
  if(field==='navigation-visible')ack.navigation.entries.at(-1)!.visible=false;
  return ack;
 });
 await submit();expect(localStorage.getItem('stella_drive_bg_mode')).toBe('image');expect(localStorage.getItem('__stella_drive_bg_mode__')).toBe('solid');
 expect(toasts).toHaveLength(0);expect(host.textContent).toContain('尚未确认');expect(getWebsite).toHaveBeenCalledTimes(1);expect(api).not.toHaveBeenCalled();
});
it('confirms an unknown write through its same-key receipt, not another save or detail/navigation GET',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');await mount();background().value='solid';background().dispatchEvent(new Event('change'));
 let finish!:(value:WebsiteSaveResult)=>void;
 vi.mocked(saveWebsiteDraft).mockRejectedValueOnce(new Error('connection lost after write'));
 vi.mocked(getWebsiteSaveReceipt).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await submit();const payload=vi.mocked(saveWebsiteDraft).mock.calls[0]![1];
 expect(getWebsiteSaveReceipt).toHaveBeenCalledExactlyOnceWith(id,payload.idempotency_key);expect(toasts).toHaveLength(0);expect(localStorage.getItem('stella_drive_bg_mode')).toBe('image');
 finish(persist(payload));await flush();expect(toasts.map(t=>t.text)).toEqual(['网站已保存']);expect(localStorage.getItem('stella_drive_bg_mode')).toBeNull();
 expect(saveWebsiteDraft).toHaveBeenCalledTimes(1);expect(getWebsite).toHaveBeenCalledTimes(1);expect(api).not.toHaveBeenCalled();expect(checkWebsiteDraft).not.toHaveBeenCalled();
});
it('legacy implicit mapping is disclosed instead of claiming the empty other input is shared',async()=>{
 Object.assign(item,{mode:'iframe',browser_url:'https://127.0.0.1:8443/legacy',address_mode:null,mapping_configured:false,alternate_address:null});
 await mount();expect(host.querySelector('.mapping-help')?.textContent).toContain('沿用旧入口映射');
 expect(host.querySelector('.mapping-help')?.textContent).not.toContain('留空时两个 Stella 入口共用');
});
it('primary address edit explicitly establishes the visible mapping and inferred mode for a legacy site',async()=>{
 Object.assign(item,{mode:'iframe',browser_url:'https://127.0.0.1:8443/legacy',address_mode:null,mapping_configured:false,alternate_address:null});
 vi.mocked(checkWebsiteDraft).mockImplementation(async p=>({can_save:true,normalized_url:p.address,embedding:{status:'allowed'},access:{status:'reachable'},injection:{status:'supported'},issues:[]} as any));
 await mount();const address=host.querySelector<HTMLInputElement>('#website-address')!;address.value='https://127.0.0.1:8443/edited';address.dispatchEvent(new Event('input'));await submit();
 expect(checkWebsiteDraft).not.toHaveBeenCalled(); // save delegates its check to the server
 expect(vi.mocked(saveWebsiteDraft).mock.calls[0]![1]).toMatchObject({address_mode:'ip',alternate_address:null});
});
it('editing a legacy inferred-IP address to a domain still sends the displayed IP constraint',async()=>{
 Object.assign(item,{browser_url:'https://127.0.0.1:8443/legacy',address_mode:null,mapping_configured:false});await mount();
 const address=host.querySelector<HTMLInputElement>('#website-address')!;address.value='https://first.fixture.test:8443/domain-under-ip-mode';address.dispatchEvent(new Event('input'));
 [...host.querySelectorAll('button')].find(b=>b.textContent==='检测')!.click();await flush();
 expect(vi.mocked(checkWebsiteDraft).mock.calls[0]![0]).toMatchObject({address_mode:'ip',alternate_address:null});
});
it('fill then clear of an implicit blank other address is an explicit dirty shared-mapping intent',async()=>{
 Object.assign(item,{mapping_configured:false,alternate_address:null});const onDirty=vi.fn();
 host=document.createElement('div');document.body.append(host);app=createApp(WebsiteSettings,{id,onDirty});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(host);await flush();
 const other=host.querySelector<HTMLInputElement>('#website-alternate')!;other.value='https://second.test/';other.dispatchEvent(new Event('input'));await flush();other.value='';other.dispatchEvent(new Event('input'));await flush();
 expect(onDirty).toHaveBeenLastCalledWith(true);await submit();expect(vi.mocked(saveWebsiteDraft).mock.calls[0]![1]).toMatchObject({address_mode:'domain',alternate_address:null});
});
it('unrelated legacy metadata save omits both mapping fields and retains all historical inputs',async()=>{
 Object.assign(item,{mapping_configured:false,address_mode:null,private_address:'https://old.generated.test/'});await mount();
 const name=host.querySelector<HTMLInputElement>('[aria-label="显示名称"]')!;name.value='metadata only';name.dispatchEvent(new Event('input'));await submit();
 const p=vi.mocked(saveWebsiteDraft).mock.calls[0]![1];for(const field of ['address_mode','alternate_address','private_address','connection','custom'])expect(p).not.toHaveProperty(field);
});
it('normalization during a metadata-only check never becomes an explicit legacy mapping edit',async()=>{
 Object.assign(item,{browser_url:'https://CHILD.test/legacy',mapping_configured:false,address_mode:null});
 vi.mocked(checkWebsiteDraft).mockResolvedValue({can_save:true,normalized_url:'https://child.test/legacy',embedding:{status:'allowed'},access:{status:'reachable'},injection:{status:'supported'},issues:[]} as any);
 await mount();[...host.querySelectorAll('button')].find(b=>b.textContent==='检测')!.click();await flush();
 expect(checkWebsiteDraft).toHaveBeenCalledTimes(1);expect(host.querySelector<HTMLInputElement>('#website-address')!.value).toBe('https://child.test/legacy');
 await submit();const p=vi.mocked(saveWebsiteDraft).mock.calls[0]![1];expect(p).not.toHaveProperty('address_mode');expect(p).not.toHaveProperty('alternate_address');
});
it('user address intent stays dirty when normalization returns the original legacy URL',async()=>{
 Object.assign(item,{mapping_configured:false,address_mode:null});const onDirty=vi.fn();host=document.createElement('div');document.body.append(host);app=createApp(WebsiteSettings,{id,onDirty});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(host);await flush();
 const address=host.querySelector<HTMLInputElement>('#website-address')!;address.value='https://CHILD.test/';address.dispatchEvent(new Event('input'));await flush();
 [...host.querySelectorAll('button')].find(b=>b.textContent==='检测')!.click();await flush();expect(address.value).toBe(item.browser_url);expect(onDirty).toHaveBeenLastCalledWith(true);
});
it.each(['primary','alternate'])('reverted %s edits of an explicit shared mapping are clean and do not republish it',async(field)=>{
 Object.assign(item,{address_mode:'domain',mapping_configured:true,alternate_address:null});const onDirty=vi.fn();
 host=document.createElement('div');document.body.append(host);app=createApp(WebsiteSettings,{id,onDirty});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(host);await flush();
 const input=host.querySelector<HTMLInputElement>(field==='primary'?'#website-address':'#website-alternate')!,old=input.value;
 input.value='https://changed.test/';input.dispatchEvent(new Event('input'));await flush();expect(onDirty).toHaveBeenLastCalledWith(true);
 input.value=old;input.dispatchEvent(new Event('input'));await flush();expect(onDirty).toHaveBeenLastCalledWith(false);
 await submit();const p=vi.mocked(saveWebsiteDraft).mock.calls[0]![1];expect(p).not.toHaveProperty('address_mode');expect(p).not.toHaveProperty('alternate_address');
});
it('a pre-write navigation read cannot overwrite the newer save ACK',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');await mount();
 const oldSnapshot={...receipt({visible:true,idempotency_key:'old'} as SavePayload).navigation,revision:1,modules:[summary({...item,name:'stale',background:'home'},'runtime-stale')]};
 let old!:(data:any)=>void;vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{old=resolve;}));const prewrite=loadNavigation({force:true});
 background().value='solid';background().dispatchEvent(new Event('change'));await submit();
 expect(vi.mocked(api).mock.calls.map(([path])=>path)).toEqual(['/navigation']);expect(getWebsite).toHaveBeenCalledTimes(1);expect(checkWebsiteDraft).not.toHaveBeenCalled();
 expect(localStorage.getItem('stella_drive_bg_mode')).toBeNull();old(oldSnapshot);await prewrite;await flush();
 expect(navigation.revision).toBe(2);expect(navigation.modules).toEqual([summary(item,'runtime-after')]);expect(toasts.map(t=>t.text)).toEqual(['网站已保存']);
});
