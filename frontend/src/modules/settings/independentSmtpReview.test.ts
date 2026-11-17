import {createApp,nextTick,h,KeepAlive,ref,type App} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import {it,expect,vi,afterEach,beforeEach} from 'vitest';
vi.mock('./AvatarCropper.vue',()=>({default:{template:'<div />'}}));
vi.mock('./NavigationSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../../shell/SettingsPanel.vue',()=>({default:{template:'<div />'}}));
vi.mock('./PerformanceSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('./SecuritySettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('./AuthProviderSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../notes/NotesSettings.vue',()=>({default:{template:'<div />'}}));
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'owner',display_name:'Owned'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1}),isAdmin:ref(true),currentAvatar:ref(''),logout:vi.fn(),refreshAccess:vi.fn(async()=>false)};});
vi.mock('../../api/servers',()=>({getPublicHost:vi.fn().mockResolvedValue({value:''}),setPublicHost:vi.fn()}));
import {auth,isAdmin} from '../home/auth';
import SettingsPage from './SettingsPage.vue';
import {toasts} from '../../composables/useToast';
let app:App|undefined,visible=ref(true),failPut=false,getGate:Promise<Response>|null=null,putCount=0,getCount=0;
const secret='synthetic-review-only';
const config=()=>({host:'smtp.owned.invalid',port:465,username:'owned',password:'••••••',from_name:'Owned',enabled:true});
const response=(v:any,status=200)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json'}});
const flush=async()=>{for(let i=0;i<25;i++)await Promise.resolve();await nextTick();await new Promise(r=>setTimeout(r,0));await nextTick();};
beforeEach(()=>{Object.assign(auth,{me:{id:'owner'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1});(isAdmin as any).value=true;visible=ref(true);failPut=false;getGate=null;putCount=0;getCount=0;
 vi.stubGlobal('fetch',vi.fn(async(path:string,options?:RequestInit)=>{if(path==='/config/access-entries')return response({settings:{revision:1,enabled:false,public_origin:'https://synthetic.example.test',private_origin:null},issuer:null,deployed:{public:'https://synthetic.example.test',private:null},websites:[]});if(path==='/admin/email/config'){if(options?.method==='PUT'){putCount++;return response({},failPut?502:200);}getCount++;return getGate??response(config());}return response([]);}));
});
afterEach(()=>{toasts.splice(0);app?.unmount();app=undefined;document.body.innerHTML='';vi.unstubAllGlobals();});
async function mount(){const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage},{path:'/status',component:{template:'<div />'}}]});await router.push('/settings?section=services');await router.isReady();const root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(KeepAlive,null,{default:()=>visible.value?h(SettingsPage):null})});app.use(router);app.mount(root);await flush();return router;}
it('labels SMTP controls and exposes the real switch state without submitting on edit',async()=>{await mount();const toggle=document.querySelector<HTMLButtonElement>('[role="switch"]')!;expect(toggle.getAttribute('aria-label')).toBe('启用 SMTP 服务');expect(toggle.getAttribute('aria-checked')).toBe('true');toggle.click();await flush();expect(toggle.getAttribute('aria-checked')).toBe('false');for(const label of ['SMTP 端口','SMTP 账号','SMTP 签名','测试收件邮箱'])expect(document.querySelector(`[aria-label="${label}"]`)).not.toBeNull();expect(document.querySelector('[aria-label="节点连接主机名"]')).toBeNull();expect(document.querySelector<HTMLInputElement>('[aria-label="SMTP 服务地址"]')!.value).toBe('smtp.owned.invalid');expect(getCount).toBe(1);expect(putCount).toBe(0);});
it.each(['owner','suspend','closing','epoch','unmount'] as const)('scrubs the existing DOM synchronously at %s',async boundary=>{
 await mount();await type();const el=input()!;
 if(boundary==='owner'){auth.me={id:'other'} as any;auth.sessionGeneration++;}
 if(boundary==='suspend')auth.suspended=true;
 if(boundary==='closing')auth.sessionClosing=true;
 if(boundary==='epoch')auth.requestEpoch++;
 if(boundary==='unmount'){app!.unmount();app=undefined;}
 expect(el.value==='','synchronous scrub before Vue rendering').toBe(true);
});
it('readback failure retries GET only and retains newer nonsecret and secret edits',async()=>{
 await mount();await type();getGate=Promise.resolve(response({},503));await save();
 expect(putCount).toBe(1);expect(input()?.value===secret).toBe(true);
 await type('synthetic-newer-draft');
 const host=document.querySelector<HTMLInputElement>('[aria-label="SMTP 服务地址"]')!;host.value='newer.invalid';host.dispatchEvent(new Event('input',{bubbles:true}));await flush();
 getGate=null;const retry=[...document.querySelectorAll('button')].find(b=>b.textContent==='重试读取 SMTP 配置')!;
 expect(retry?.disabled).toBe(false);retry.click();await flush();
 expect(putCount).toBe(1);expect(getCount).toBe(3);expect(input()?.value==='synthetic-newer-draft').toBe(true);expect(host.value).toBe('newer.invalid');
});
it('native hide clears only secrets and re-entry preserves nonsecret drafts',async()=>{
 const router=await mount();await type();const host=document.querySelector<HTMLInputElement>('[aria-label="SMTP 服务地址"]')!;host.value='draft.invalid';host.dispatchEvent(new Event('input',{bubbles:true}));await flush();
 await router.push('/settings?section=authentication');await flush();await router.push('/settings?section=services');await flush();
 expect(input()?.value).toBe('');expect(document.querySelector<HTMLInputElement>('[aria-label="SMTP 服务地址"]')?.value).toBe('draft.invalid');expect(getCount).toBe(2);
});
it.each([200,503])('suspend/resume replaces held GET and ignores stale %s publication',async status=>{
 let finish!:(r:Response)=>void;getGate=new Promise(r=>finish=r);await mount();auth.suspended=true;await flush();getGate=null;auth.suspended=false;await flush();
 expect(getCount).toBe(2);await type();finish(response({...config(),host:'stale.invalid'},status));await flush();
 expect(input()?.value===secret).toBe(true);expect(document.querySelector<HTMLInputElement>('[aria-label="SMTP 服务地址"]')?.value).toBe('smtp.owned.invalid');expect(document.body.textContent).not.toContain('邮箱配置读取失败');
});
it('suspended late error cannot publish a read failure',async()=>{
 let finish!:(r:Response)=>void;getGate=new Promise(r=>finish=r);await mount();auth.suspended=true;finish(response({},503));await flush();expect(document.body.textContent).not.toContain('邮箱配置读取失败');
});
function input(){return document.querySelector<HTMLInputElement>('[aria-label="SMTP 密钥"]');}
async function type(value=secret){const el=input()!;expect(el).toBeTruthy();el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));await flush();}
async function save(){[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='应用 SMTP 配置')!.click();await flush();}
it('failed write retains synthetic retry draft',async()=>{await mount();await type();failPut=true;await save();expect(input()?.value===secret).toBe(true);expect(putCount).toBe(1);expect(getCount).toBe(1);});
it.each(['session','suspend','closing','owner'] as const)('failed retry secret is cleared at %s boundary',async(boundary)=>{await mount();await type();failPut=true;await save();if(boundary==='session'){auth.sessionGeneration++;}if(boundary==='suspend'){auth.suspended=true;auth.requestEpoch++;(isAdmin as any).value=false;}if(boundary==='closing'){auth.sessionClosing=true;auth.requestEpoch++;(isAdmin as any).value=false;}if(boundary==='owner'){auth.me={id:'other'} as any;auth.sessionGeneration++;(isAdmin as any).value=false;}await flush();expect(input()?.value===secret,'old secret must not remain in rendered input').toBe(false);});
it('failed retry secret is cleared by KeepAlive hide and not restored on activation',async()=>{await mount();await type();failPut=true;await save();visible.value=false;await flush();visible.value=true;await flush();expect(input()?.value===secret).toBe(false);});
it('native services hide then logout cannot reveal retry secret on return',async()=>{const router=await mount();await type();failPut=true;await save();await router.push('/settings?section=authentication');await flush();expect(input()).toBeNull();auth.sessionClosing=true;await router.push('/settings?section=services');await flush();expect(input()?.value===secret,'returning to locked services exposes the retained secret').toBe(false);expect(getCount).toBe(1);});
it('confirmed save readback clears the submitted secret',async()=>{await mount();await type();await save();expect(input()?.value).toBe('');expect(toasts.map(t=>t.text).join(' ')).toContain('配置已保存');expect(getCount).toBe(2);});
it('late successful readback does not erase a newer typed secret',async()=>{await mount();await type();let finish!:(r:Response)=>void;getGate=new Promise(r=>finish=r);await save();await type('synthetic-newer-draft');finish(response(config()));await flush();expect(input()?.value==='synthetic-newer-draft','new edit generation should survive older readback').toBe(true);});
it('pending privileged read cannot publish old config after suspension',async()=>{let finish!:(r:Response)=>void;getGate=new Promise(r=>finish=r);await mount();expect(input()).toBeNull();auth.suspended=true;await flush();finish(response(config()));await flush();expect(document.querySelector('[aria-label="SMTP 服务地址"]'),'locked old GET must not mount privileged form').toBeNull();});
it('reads and saves SMTP with only the authenticated owner, without a management grant',async()=>{(isAdmin as any).value=false;await mount();expect(input()).not.toBeNull();expect(getCount).toBe(1);await type();await save();expect(putCount).toBe(1);expect(input()?.value).toBe('');});
it('real API client fences a late successful read after logout epoch change',async()=>{let finish!:(r:Response)=>void;getGate=new Promise(r=>finish=r);await mount();auth.sessionClosing=true;auth.requestEpoch++;(isAdmin as any).value=false;finish(response(config()));await flush();expect(input()).toBeNull();});
