import {createApp, nextTick, type App, type Component} from 'vue';
import {it, expect, vi, afterEach} from 'vitest';
import {api} from '../../api/client';
import {serviceFixture} from '../../../tests/fixtures/serviceSettings';
vi.mock('../../api/client',()=>({api:vi.fn()}));
const panels=import.meta.glob('./ServiceSettings.vue',{eager:true,import:'default'});
const tick=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};
let app:App|undefined;
afterEach(()=>{app?.unmount();vi.resetAllMocks();document.body.innerHTML='';localStorage.clear();});
async function mount(site='drive') {
 expect(panels['./ServiceSettings.vue'],'unified service editor exists').toBeDefined();
 const root=document.createElement('div');document.body.append(root);
 const events={saved:vi.fn(),dirty:vi.fn(),busy:vi.fn()};
 app=createApp(panels['./ServiceSettings.vue'] as Component,{site,onSaved:events.saved,onDirty:events.dirty,onBusy:events.busy});app.mount(root);await tick();
 return {root,events};
}
function input(root:HTMLElement,label:string,value:string){const el=root.querySelector<HTMLInputElement|HTMLTextAreaElement>(`[aria-label="${label}"]`)!;expect(el).not.toBeNull();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));}
async function click(root:HTMLElement,label:string){const button=[...root.querySelectorAll('button')].find(x=>x.textContent?.trim()===label);expect(button,`button ${label}`).toBeDefined();expect(button!.disabled).toBe(false);button!.click();await tick();}
function backend(){let state:any=serviceFixture();const writes:any[]=[];let failRead=false,failWrite=0,uncertain=false;
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path!=='/service-settings/drive')throw Error('Unexpected API '+path);
  if(options?.method==='PUT'){const payload=JSON.parse(String(options.body));writes.push(payload);if(failWrite)throw {status:failWrite,detail:'校验失败'};state={...state,...payload,connection:{...payload.connection,has_token:true},injection:state.injection};if(uncertain)throw Error('timeout');return structuredClone(state);}
  if(failRead)throw Error('read unavailable');return structuredClone(state);
 });
 return {writes,get state(){return state;},set failRead(v:boolean){failRead=v;},set failWrite(v:number){failWrite=v;},set uncertain(v:boolean){uncertain=v;}};
}
it('saves name and connection together in one PUT, preserves blank token, confirms with GET',async()=>{
 const b=backend(),{root,events}=await mount();input(root,'显示名称','私人文件');input(root,'OpenList 服务地址','http://owned.test/new/path');await tick();
 await click(root,'保存');expect(b.writes).toHaveLength(1);expect(b.writes[0]).toEqual({name:'私人文件',icon:'drive',visible:true,connection:{service_url:'http://owned.test/new/path',auth_mode:'token',token:null,clear_token:false},appearance:{theme:'stella',simplified:true}});
 expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toBe('/service-settings/drive');expect(events.saved).toHaveBeenCalledTimes(1);
});
it('validation rejection leaves every input and never emits saved',async()=>{
 const b=backend(),{root,events}=await mount();input(root,'显示名称','Keep name');input(root,'OpenList 服务地址','http://owned.test/draft');b.failWrite=422;await click(root,'保存');
 expect(events.saved).not.toHaveBeenCalled();expect(root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')?.value).toBe('Keep name');expect(root.textContent).toContain('校验失败');expect(b.writes).toHaveLength(1);
});
it('failed readback locks mutation and close, preserves input, retries only GET',async()=>{
 const b=backend(),{root,events}=await mount();input(root,'显示名称','Pending name');b.failRead=true;await click(root,'保存');
 expect(events.saved).not.toHaveBeenCalled();expect(events.busy).toHaveBeenLastCalledWith(true);expect(root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')?.value).toBe('Pending name');
 expect(root.querySelector('fieldset')!.disabled).toBe(true);b.failRead=false;await click(root,'重试回读');expect(events.saved).toHaveBeenCalledTimes(1);expect(b.writes).toHaveLength(1);
});
it('uncertain network result reconciles with GET instead of replaying PUT',async()=>{
 const b=backend(),{root,events}=await mount();b.uncertain=true;input(root,'显示名称','Confirmed after timeout');await click(root,'保存');
 expect(events.saved).toHaveBeenCalledTimes(1);expect(b.writes).toHaveLength(1);expect(vi.mocked(api).mock.calls.at(-1)?.[1]?.method).not.toBe('PUT');
});
it('appearance preview changes theme and simplified graphics without saving the service',async()=>{
 backend();const {root}=await mount();
 const theme=root.querySelector<HTMLInputElement>('[aria-label="Stella 主题"]');expect(theme).not.toBeNull();theme!.checked=false;theme!.dispatchEvent(new Event('change',{bubbles:true}));await tick();
 expect(root.querySelector('[data-preview-theme="original"]')).not.toBeNull();
 const simple=root.querySelector<HTMLInputElement>('[aria-label="简洁显示"]');expect(simple).not.toBeNull();simple!.checked=false;simple!.dispatchEvent(new Event('change',{bubbles:true}));await tick();
 expect(root.querySelector('[data-preview-brand]')).not.toBeNull();expect(vi.mocked(api).mock.calls).toHaveLength(1);
});
it('background draft uses legacy preference and persists only on an explicit device save, no API',async()=>{
 localStorage.setItem('__stella_drive_bg_mode__','image');backend();const {root}=await mount();
 const bg=root.querySelector<HTMLInputElement>('[aria-label="主页背景"]');expect(bg?.checked).toBe(true);bg!.checked=false;bg!.dispatchEvent(new Event('change',{bubbles:true}));await tick();
 expect(localStorage.getItem('__stella_drive_bg_mode__')).toBe('image');await click(root,'保存本机背景');
 expect(localStorage.getItem('stella_drive_bg_mode')).toBe('solid');expect(localStorage.getItem('__stella_drive_bg_mode__')).toBe('solid');expect(vi.mocked(api).mock.calls).toHaveLength(1);
});
it('Immich logo preview switches actual graphics and clearly names the domain scope',async()=>{
 vi.mocked(api).mockResolvedValue(serviceFixture('gallery'));const {root}=await mount('gallery');
 expect(root.querySelector('[data-preview-logo="stella"] img')).not.toBeNull();
 const logo=root.querySelector<HTMLInputElement>('[aria-label="Stella Logo"]');expect(logo).not.toBeNull();logo!.checked=false;logo!.dispatchEvent(new Event('change',{bubbles:true}));await tick();
 expect(root.querySelector('[data-preview-logo="original"] svg')).not.toBeNull();expect(root.textContent).toContain('整个原站域名');expect(root.querySelector('[aria-label="主页背景"]')).toBeNull();
});
it('saves only a custom draft through legacy validate, reads aggregate, and retains unrelated dirty input',async()=>{
 const state:any=serviceFixture();const calls:any[]=[];
 vi.mocked(api).mockImplementation(async(path,options)=>{calls.push({path,method:options?.method});if(path==='/builtin-injections/drive/validate'){state.injection.draft=JSON.parse(String(options?.body));return {valid:true,errors:[],draft:state.injection.draft};}if(path==='/service-settings/drive')return structuredClone(state);throw Error('Unexpected '+path);});
 const {root,events}=await mount();input(root,'显示名称','not yet saved');input(root,'自定义 CSS','body { color: salmon; }');await click(root,'仅保存草稿');
 expect(state.injection.active.css).toBe('');expect(state.injection.draft.css).toBe('body { color: salmon; }');expect(events.saved).not.toHaveBeenCalled();expect(events.dirty).toHaveBeenLastCalledWith(true);expect(calls.at(-1).path).toBe('/service-settings/drive');expect(root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')?.value).toBe('not yet saved');
});
it('rollback reads active separately from a retained different draft and never replays an uncertain POST',async()=>{
 const state:any=serviceFixture();state.injection.active={...state.injection.active,css:'/* current */',version:'v2'};state.injection.previous={...state.injection.active,css:'/* previous */',version:'v1',status:'revoked'};state.injection.draft={...state.injection.active,css:'/* saved draft */'};let count=0;
 vi.mocked(api).mockImplementation(async(path)=>{if(path==='/builtin-injections/drive/rollback'){count++;[state.injection.active,state.injection.previous]=[{...state.injection.previous,status:'active'},{...state.injection.active,status:'revoked'}];throw Error('timeout');}if(path==='/service-settings/drive')return structuredClone(state);throw Error('Unexpected '+path);});
 const {root}=await mount();await click(root,'回退上一版本');expect(count).toBe(1);expect(root.querySelector<HTMLTextAreaElement>('[aria-label="活动版本 CSS"]')?.value).toBe('/* previous */');expect(root.querySelector<HTMLTextAreaElement>('[aria-label="自定义 CSS"]')?.value).toBe('/* saved draft */');expect(root.textContent).toContain('回退已回读');
});
it('main save includes edited custom with explicit reject policy and waits for active code readback',async()=>{
 const state:any=serviceFixture();let body:any;
 vi.mocked(api).mockImplementation(async(path,options)=>{if(path!=='/service-settings/drive')throw Error('Unexpected '+path);if(options?.method==='PUT'){body=JSON.parse(String(options.body));state.injection.active={...body.custom,version:'v2',status:'active'};}return structuredClone(state);});
 const {root,events}=await mount();input(root,'自定义 JavaScript','window.example = 7;');await click(root,'保存');expect(body.custom).toEqual({enabled:false,css:'',js:'window.example = 7;',timing:'dom_ready',csp_policy:'reject'});expect(events.saved).toHaveBeenCalledTimes(1);
});
it('detects current unsaved connection, discards late check results after editing',async()=>{
 const state=serviceFixture();let release!:(v:unknown)=>void;vi.mocked(api).mockImplementation(async(path)=>{if(path==='/service-settings/drive/check')return new Promise(r=>release=r);if(path==='/service-settings/drive')return state;throw Error('Unexpected '+path);});
 const {root}=await mount();input(root,'OpenList 服务地址','http://owned.test/unsaved');await click(root,'检测连接');
 expect(vi.mocked(api).mock.calls.at(-1)?.[1]?.body).toBe(JSON.stringify({connection:{service_url:'http://owned.test/unsaved',auth_mode:'token',token:null,clear_token:false}}));
 input(root,'OpenList 服务地址','http://owned.test/newer');release({ok:true,message:'stale success'});await tick();expect(root.textContent).not.toContain('stale success');expect(root.textContent).toContain('需重新检测');
});
it('readback mismatch preserves input and permits deliberate editing only after a successful GET',async()=>{
 const state=serviceFixture();let puts=0;vi.mocked(api).mockImplementation(async(path,options)=>{if(path!=='/service-settings/drive')throw Error('unexpected');if(options?.method==='PUT'){puts++;throw Error('timeout before write');}return structuredClone(state);});
 const {root,events}=await mount();input(root,'显示名称','Unwritten draft');await click(root,'保存');expect(events.saved).not.toHaveBeenCalled();await click(root,'继续编辑，不重发');expect(puts).toBe(1);expect(root.querySelector('fieldset')!.disabled).toBe(false);expect(root.querySelector<HTMLInputElement>('[aria-label="显示名称"]')?.value).toBe('Unwritten draft');
});
it('ordinary owner reads only the nonsecret aggregate; one form and folded advanced settings',async()=>{
 vi.mocked(api).mockResolvedValue(serviceFixture());
 const {root}=await mount();
 expect(vi.mocked(api).mock.calls.map(([p])=>p)).toEqual(['/service-settings/drive']);
 expect(root.querySelectorAll('form')).toHaveLength(1);
 expect(root.querySelectorAll('select')).toHaveLength(0);
 expect(root.querySelector<HTMLInputElement>('[aria-label="OpenList 服务地址"]')?.value).toBe('http://owned.test:5244/drive/openlist');
 expect(root.querySelector<HTMLInputElement>('[aria-label="Token"]')?.value).toBe('');
 expect(root.querySelector<HTMLDetailsElement>('.advanced')?.open).toBe(false);
 expect(root.querySelector('.icon-picker svg')).not.toBeNull();
});

for(const site of ['drive','gallery'] as const)it(`confirms accepted ${site} trailing URL separators after exact readback`,async()=>{
 const state:any=serviceFixture(site);let puts=0;
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path!=='/service-settings/'+site)throw Error('unexpected');
  if(options?.method==='PUT'){
   puts++;const v=JSON.parse(String(options.body));
   const {token,clear_token,...connection}=v.connection;
   for(const key of ['service_url','browser_url','upstream_url','alternate_browser_url'])if(typeof connection[key]==='string')connection[key]=connection[key].replace(/\/+$/,'');
   Object.assign(state,{...v,connection:{...connection,...(site==='drive'?{has_token:true}:{})}});
  }
  return structuredClone(state);
 });
 const {root,events}=await mount(site);
 if(site==='drive')input(root,'OpenList 服务地址','http://owned.test:5244/drive/openlist/');
 else {input(root,'Immich 浏览器地址','https://gallery.test/');input(root,'备用浏览器地址','https://alternate.test/');input(root,'健康检查地址','https://health.test/ping/');}
 await click(root,'保存');expect(puts).toBe(1);expect(events.saved).toHaveBeenCalledTimes(1);
});
