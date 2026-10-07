import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, type App } from 'vue';
import WebsiteSettings from './WebsiteSettings.vue';
import { auth } from '../home/auth';
import { api } from '../../api/client';
import { getWebsite } from '../../api/integrations';
import { checkWebsiteDraft, saveWebsiteDraft, getWebsiteTemplates } from '../../api/websiteSettings';
import { loadNavigation, navigation, resetNavigation, type Website } from '../../stores/navigation';
import { effectiveWebsiteBackground } from '../../stores/websiteBackground';
vi.mock('../../api/client',()=>({api:vi.fn()}));
vi.mock('../../api/integrations',async importOriginal=>({...await importOriginal<typeof import('../../api/integrations')>(),getWebsite:vi.fn()}));
vi.mock('../../api/websiteSettings',()=>({checkWebsiteDraft:vi.fn(),saveWebsiteDraft:vi.fn(),getWebsiteTemplates:vi.fn()}));
vi.mock('../../shell/Icon.vue',()=>({default:{render:()=>null}}));
vi.mock('./IconPicker.vue',()=>({default:{render:()=>null}}));
vi.mock('../../shell/Dropdown.vue',()=>({default:{props:['modelValue','options'],emits:['update:modelValue'],setup(props:any,{emit}:any){return()=>h('select',{value:props.modelValue,onChange:(e:Event)=>emit('update:modelValue',(e.target as HTMLSelectElement).value)},props.options.map((o:any)=>h('option',{value:o.value},o.label)));}}}));
let app:App,host:HTMLDivElement,item:Website;
const id='editable-synthetic-website';
async function flush(){for(let i=0;i<60;i++)await Promise.resolve();await nextTick();}
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp(WebsiteSettings,{id});app.mount(host);await flush();}
const background=()=>Array.from(host.querySelectorAll('select')).find(s=>s.querySelector('option[value=home]'))!;
async function submit(){host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flush();}
beforeEach(()=>{
 localStorage.clear();resetNavigation();vi.clearAllMocks();Object.assign(auth,{me:{id:'settings-owner'},sessionClosing:false});
 const code={enabled:false,css:'',js:'',timing:'dom_ready' as const,csp_policy:'reject' as const};
 item={id,name:'网站',icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:'https://child.test/',origin:'https://child.test',enabled:true,keep_alive:true,background:'solid',template_id:null,injection:{active:code,draft:code,previous:null}};
 navigation.loaded=true;navigation.modules=[item];navigation.legacy_routes={drive:id};
 vi.mocked(getWebsite).mockImplementation(async()=>JSON.parse(JSON.stringify(item)));
 vi.mocked(getWebsiteTemplates).mockResolvedValue([]);
 vi.mocked(checkWebsiteDraft).mockResolvedValue({can_save:true,normalized_url:item.browser_url,embedding:{status:'allowed'},access:{status:'reachable'},injection:{status:'supported'},issues:[]} as any);
 vi.mocked(saveWebsiteDraft).mockImplementation(async(_id,payload)=>{item={...item,...(payload.background?{background:payload.background}:{}),name:payload.name||item.name};return {...item,check:await checkWebsiteDraft({address:item.browser_url,open_behavior:'embedded',custom_enabled:false})};});
 vi.mocked(api).mockImplementation(async(path)=>path==='/navigation'?{entries:[],legacy_routes:{drive:id}}:[item]);
});
afterEach(()=>{app?.unmount();host?.remove();resetNavigation();vi.restoreAllMocks();});
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
it('reloads authoritative active code into retained module configuration after rollback',async()=>{
 item.injection!.active!.version='current';item.injection!.previous={...item.injection!.active!,version:'previous'};await mount();
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path.endsWith('/rollback')){item={...item,injection:{...item.injection!,active:{...item.injection!.previous!}}};return item.injection;}
  return path==='/navigation'?{entries:[],legacy_routes:{drive:id}}:[item];
 });
 const rollback=Array.from(host.querySelectorAll('button')).find(b=>b.textContent==='回退上一版本')!;rollback.click();await flush();
 expect(navigation.modules[0]?.injection?.active?.version).toBe('previous');expect(host.textContent).not.toContain('手动重载');
});
it('keeps the local preference when explicit save readback is inconsistent',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');await mount();background().value='solid';background().dispatchEvent(new Event('change'));
 vi.mocked(getWebsite).mockImplementation(async()=>({...item,background:'home'}));await submit();
 expect(localStorage.getItem('stella_drive_bg_mode')).toBe('image');expect(host.textContent).toContain('尚未确认');
});
it('never joins a pre-write navigation readback',async()=>{
 localStorage.setItem('stella_drive_bg_mode','image');await mount();
 let old!:(data:any)=>void;vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{old=resolve;})).mockResolvedValueOnce([item]);const prewrite=loadNavigation();
 background().value='solid';background().dispatchEvent(new Event('change'));await submit();
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/navigation')).toHaveLength(2);
 expect(localStorage.getItem('stella_drive_bg_mode')).toBeNull();old({entries:[],legacy_routes:{drive:id}});await prewrite;
});
