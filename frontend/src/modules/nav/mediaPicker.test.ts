import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import {defaults} from './controller';
import {auth} from '../home/auth';
import {bgManagerOpen,homeSettings} from '../home/settings';
import {backgroundEntries} from '../home/backgroundMedia';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('../../api/client',()=>({api:mocks.api}));
vi.mock('../../stores/navigation',()=>({navigation:{modules:[]}}));
vi.mock('../../composables/useToast',()=>({toast:vi.fn()}));
vi.mock('./realtime',()=>({watchNavRevision:()=>()=>{}}));
import Page from './NavPage.vue';
let app:ReturnType<typeof createApp>,host:HTMLDivElement,server:any,calls:string[];
const url='/assets/homebg/picker.png';
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();await nextTick();};
function button(name:string,scope:ParentNode=document){return [...scope.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.trim()===name||b.getAttribute('aria-label')===name)!;}
beforeEach(()=>{localStorage.clear();backgroundEntries.value=[];Object.assign(auth,{me:{id:'nav-picker-owner',username:'owner',display_name:'Owner',home_bg:'/home.png'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});bgManagerOpen.value=false;server={revision:0,data:defaults()};calls=[];mocks.api.mockImplementation(async(path:string,o?:RequestInit)=>{calls.push((o?.method||'GET')+' '+path);if(path==='/nav-assets')return [];if(path==='/nav-data'){if(o?.method==='PUT'){const payload=JSON.parse(String(o.body));server={revision:1,data:payload.data};}return structuredClone(server);}throw Error('DENY '+path);});vi.stubGlobal('fetch',vi.fn(async(input,init)=>{calls.push((init?.method||'GET')+' '+input);if(String(input)==='/homebg/')return Response.json([{id:'pick',name:'Synthetic',url,ext:'png',isDefault:false,owner:auth.me!.id,media:{url,status:'ready',variants:{original:url}}}]);throw Error('DENY '+input);}));HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open')};});
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();});
async function mount(){host=document.createElement('div');document.body.append(host);app=createApp(Page);app.use(createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]}));app.mount(host);await flush();button('导航设置').click();await flush();button('背景').click();await flush();button('管理壁纸与视频').click();await flush();}
it('real BgManager is inside the native dialog top layer; select only edits nav draft and cancel discards it',async()=>{const home=JSON.stringify(auth.me),crop=JSON.stringify(homeSettings.bgCrop);await mount();expect(host.querySelector('dialog .bgm-mask')).not.toBeNull();expect(document.activeElement).toBe(host.querySelector('.bgm .x'));expect(host.querySelector('dialog > form')?.hasAttribute('inert')).toBe(true);document.querySelector<HTMLElement>('.cell')!.click();await flush();button('选择此背景').click();await flush();expect(host.querySelector('.bgm-mask')).toBeNull();expect(server.data.preferences.backgroundUrl).toBe('');button('取消',host).click();await flush();expect(JSON.stringify(auth.me)).toBe(home);expect(JSON.stringify(homeSettings.bgCrop)).toBe(crop);expect(calls.every(c=>c.startsWith('GET '))).toBe(true);expect(bgManagerOpen.value).toBe(false);});
it('saving a picked background sends only nav-data, never auth/home prefs/crop writes',async()=>{await mount();document.querySelector<HTMLElement>('.cell')!.click();await flush();button('选择此背景').click();await flush();button('保存',host).click();await flush();expect(server.data.preferences.background).toBe('custom');expect(server.data.preferences.backgroundUrl).toBe(url);expect(calls.filter(c=>!c.startsWith('GET '))).toEqual(['PUT /nav-data']);});
