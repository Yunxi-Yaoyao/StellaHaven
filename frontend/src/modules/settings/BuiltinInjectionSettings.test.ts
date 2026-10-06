import {createApp,nextTick,type Component} from 'vue';
import {it,expect,vi,afterEach} from 'vitest';
import {api} from '../../api/client';
vi.mock('../../api/client',()=>({api:vi.fn()}));
const panels=import.meta.glob('./BuiltinInjectionSettings.vue',{eager:true,import:'default'});
const tick=async()=>{await new Promise(r=>setTimeout(r,0));await nextTick();};
afterEach(()=>{vi.resetAllMocks();document.body.innerHTML='';});
it('uses shared custom dropdowns instead of native select controls', async () => {
  const state={site:'drive',source:'preset',active:{enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject',version:'preset-v1',status:'active'},draft:null,previous:null,preset:{css:'',js:''}};
  vi.mocked(api).mockResolvedValue(state);
  const root=document.createElement('div');document.body.append(root);const app=createApp(panels['./BuiltinInjectionSettings.vue'] as Component);app.mount(root);await tick();
  expect(root.querySelectorAll('select')).toHaveLength(0);
  expect(root.querySelectorAll('.dd-btn').length).toBeGreaterThanOrEqual(2);
  app.unmount();
});
it('edits a builtin draft then applies and reads back its version; rollback reads authoritative state',async()=>{
 expect(panels['./BuiltinInjectionSettings.vue'],'builtin settings component missing').toBeDefined();
 let state:any={site:'drive',source:'postgres',active:{enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject',version:'preset-v1',status:'active'},draft:null,previous:null,preset:{css:'body{color:white}',js:'/* cache fix */'}};
 vi.mocked(api).mockImplementation(async(path,options)=>{
  if(path.endsWith('/validate')){state.draft=JSON.parse(String(options?.body));return {valid:true,errors:[],draft:state.draft};}
  if(path.endsWith('/apply')){state.previous={...state.active,status:'revoked'};state.active={...state.draft,version:'published-1',status:'active'};return structuredClone(state);}
  if(path.endsWith('/rollback')){[state.active,state.previous]=[{...state.previous,status:'active'},{...state.active,status:'revoked'}];return structuredClone(state);}
  return structuredClone(state);
 });
 const root=document.createElement('div');document.body.append(root);const app=createApp(panels['./BuiltinInjectionSettings.vue'] as Component);app.mount(root);await tick();
 const js=root.querySelector('textarea[aria-label="自定义 JavaScript"]') as HTMLTextAreaElement;js.value='window.targetOnly=7;';js.dispatchEvent(new Event('input',{bubbles:true}));
 const enabled=root.querySelector('input[type=checkbox]') as HTMLInputElement;enabled.checked=true;enabled.dispatchEvent(new Event('change',{bubbles:true}));await tick();
 const click=async(text:string)=>{const b=Array.from(root.querySelectorAll('button')).find(b=>b.textContent?.trim()===text)!;expect(b).toBeDefined();expect(b.disabled).toBe(false);b.click();await tick();};
 await click('校验并保存草稿');expect(state.draft.js).toBe('window.targetOnly=7;');await click('应用版本');
 expect(root.textContent).toContain('published-1');expect(root.textContent).toContain('活动配置已回读');
 expect(api).toHaveBeenLastCalledWith('/builtin-injections/drive',expect.anything());
 await click('回退上一版本');expect(state.active.version).toBe('preset-v1');expect(root.textContent).toContain('preset-v1');app.unmount();
});
it('never reports applied when readback fails and prevents a second POST until reconciled',async()=>{
 expect(panels['./BuiltinInjectionSettings.vue']).toBeDefined();
 let reads=0;
 const state={site:'drive',source:'postgres',active:{enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject',version:'preset-v1',status:'active'},draft:null,previous:null,preset:{css:'',js:''}};
 vi.mocked(api).mockImplementation(async(path)=>{if(path.endsWith('/validate'))return {valid:true,errors:[]};if(path.endsWith('/apply'))return {active:{version:'new-v1'}};if(++reads>1)throw new Error('secret-details');return structuredClone(state);});
 const root=document.createElement('div');document.body.append(root);const app=createApp(panels['./BuiltinInjectionSettings.vue'] as Component);app.mount(root);await tick();
 Array.from(root.querySelectorAll('button')).find(x=>x.textContent?.trim()==='校验并保存草稿')!.click();await tick();
 Array.from(root.querySelectorAll('button')).find(x=>x.textContent?.trim()==='应用版本')!.click();await tick();
 expect(root.textContent).toContain('应用结果尚未确认');expect(root.textContent).not.toContain('活动配置已回读');expect(root.textContent).not.toContain('secret-details');
 expect(Array.from(root.querySelectorAll('button')).find(x=>x.textContent?.trim()==='应用版本')!.disabled).toBe(true);app.unmount();
});
it('unknown POST outcome is reconciled by reading without replaying the mutation',async()=>{
 const state={site:'drive',source:'postgres',active:{enabled:false,css:'',js:'',timing:'dom_ready',csp_policy:'reject',version:'actual-v2',status:'active'},draft:null,previous:null,preset:{css:'',js:''}};
 vi.mocked(api).mockImplementation(async(path)=>{if(path.endsWith('/validate'))return {valid:true,errors:[]};if(path.endsWith('/apply'))throw new Error('network timeout');return structuredClone(state);});
 const root=document.createElement('div');document.body.append(root);const app=createApp(panels['./BuiltinInjectionSettings.vue'] as Component);app.mount(root);await tick();
 const click=async(text:string)=>{Array.from(root.querySelectorAll('button')).find(x=>x.textContent?.trim()===text)!.click();await tick();};
 await click('校验并保存草稿');await click('应用版本');await click('刷新回读');
 expect(root.textContent).toContain('活动配置已回读');
 expect(root.textContent).toContain('actual-v2');
 expect(vi.mocked(api).mock.calls.filter(([path])=>path.endsWith('/apply'))).toHaveLength(1);app.unmount();
});
