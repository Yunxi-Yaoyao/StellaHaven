import {afterEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
vi.mock('../../api/client',()=>({api:vi.fn()}));
vi.mock('../../composables/useToast',()=>({toast:vi.fn()}));
import {api} from '../../api/client';
import WebsiteSettings from './WebsiteSettings.vue';
import {resetNavigation,mergeNavigationSnapshot,navigationEpoch,navigation} from '../../stores/navigation';
const request=vi.mocked(api);
let app:App;
const website:import('../../stores/navigation').Website={id:'demo',name:'Original',icon:'globe',mode:'iframe',adapter:'generic',browser_url:'https://site.test/',enabled:true,private_address:null,entry_policy:'follow',access_adapter:'auto',template_id:null,background:'solid',injection:{draft:null,active:null,previous:null}};
const snapshot=(name='Original',revision=1)=>({revision,mutation_id:null,legacy_routes:{},modules:[{...website,name}],entries:[{id:'demo',title:name,icon:'globe',visible:true}]});
async function settle(){await new Promise(r=>setTimeout(r,0));await nextTick();}
afterEach(()=>{app?.unmount();document.body.innerHTML='';resetNavigation();request.mockReset();});
it.each(['https://site.test/','site.test/'])('saves metadata for %s with one PATCH and canonical ACK',async(address)=>{
 resetNavigation();mergeNavigationSnapshot(snapshot(),navigationEpoch());
 request.mockImplementation(async(url,options)=>{
  if(url==='/external-modules/demo')return website;
  if(url==='/website-settings/demo') {const payload=JSON.parse(options!.body as string);return {...website,name:payload.name,...(payload.address_mode?{address_mode:payload.address_mode,alternate_address:payload.alternate_address,mapping_configured:true}:{}),idempotency_key:payload.idempotency_key,navigation:snapshot(payload.name,2)};}
  if(url==='/website-settings/check')return {normalized_url:website.browser_url,name_suggestion:'Original',can_save:true,software:{type:'unknown'},injection:{status:'supported',reason:'fixture'},embedding:{status:'allowed',reason:'fixture'},access:{status:'reachable'},issues:[]};
  if(url==='/navigation')return snapshot('Updated',2);
  if(url==='/external-modules')return [{...website,name:'Updated'}];
  throw new Error('Unexpected '+url);
 });
 const saved=vi.fn(),root=document.createElement('div');document.body.append(root);app=createApp(WebsiteSettings,{id:'demo',onSaved:saved});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(root);await settle();
 const addressInput=root.querySelector<HTMLInputElement>('[aria-label="网站地址"]')!;addressInput.value=address;addressInput.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
 request.mockClear();const name=root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')!;name.value='Updated';name.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();await settle();
 expect(request.mock.calls.map(([url])=>url)).toEqual(['/website-settings/demo']);
 expect(navigation.modules[0]?.name).toBe('Updated');
 expect(saved).toHaveBeenCalledTimes(1);
});
it('does not clear newer user edits when an older submitted ACK arrives',async()=>{
 resetNavigation();mergeNavigationSnapshot(snapshot(),navigationEpoch());
 let finish!:(value:unknown)=>void, payload:any;
 request.mockImplementation(async(url,options)=>{
  if(url==='/external-modules/demo')return website;
  if(url==='/website-settings/demo'){payload=JSON.parse(options!.body as string);return await new Promise(resolve=>{finish=resolve;});}
  throw new Error('Unexpected '+url);
 });
 const saved=vi.fn(),root=document.createElement('div');document.body.append(root);app=createApp(WebsiteSettings,{id:'demo',onSaved:saved});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(root);await settle();
 const name=root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')!;
 name.value='Submitted';name.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();
 name.value='Newer draft';name.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
 finish({...website,name:'Submitted',navigation:snapshot('Submitted',2),idempotency_key:payload.idempotency_key});await settle();await settle();
 expect(name.value).toBe('Newer draft');expect(saved).not.toHaveBeenCalled();
 expect(root.textContent).toContain('后续修改尚未保存');
});
it('sends the detail read-time revision and keeps a rejected stale edit as a draft',async()=>{
 resetNavigation();mergeNavigationSnapshot(snapshot('Original',99),navigationEpoch());
 let sent:any;
 request.mockImplementation(async(url,options)=>{
  if(url==='/external-modules/demo')return {...website,read_revision:7};
  if(url==='/website-settings/demo'){sent=JSON.parse(options!.body as string);throw {status:409,detail:'其他窗口已修改'};}
  throw new Error('Unexpected '+url);
 });
 const saved=vi.fn(),root=document.createElement('div');document.body.append(root);app=createApp(WebsiteSettings,{id:'demo',onSaved:saved});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(root);await settle();
 const name=root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')!;name.value='Stale draft';name.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();
 expect(sent.expected_revision).toBe(7);expect(name.value).toBe('Stale draft');expect(saved).not.toHaveBeenCalled();expect(root.textContent).toContain('其他窗口已修改');
});
it('clears private navigation on a definitive save authorization denial',async()=>{
 resetNavigation();mergeNavigationSnapshot(snapshot(),navigationEpoch());
 request.mockImplementation(async(url)=>{if(url==='/external-modules/demo')return website;throw {status:403,detail:'revoked'};});
 const root=document.createElement('div');document.body.append(root);app=createApp(WebsiteSettings,{id:'demo'});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(root);await settle();
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await settle();
 expect(navigation.loaded).toBe(false);expect(navigation.modules).toEqual([]);
});
