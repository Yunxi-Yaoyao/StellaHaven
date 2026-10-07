import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, type App } from 'vue';
import { createRouter, createMemoryHistory, type Router } from 'vue-router';
import ExternalModuleCache from './ExternalModuleCache.vue';
import { auth } from '../modules/home/auth';
import { navigation, resetNavigation, type Website } from '../stores/navigation';
const state=vi.hoisted(()=>({serial:0}));
vi.mock('./ExternalModulePage.vue',()=>({__esModule:true,default:{props:['id','active'],setup(props:any){const instance=++state.serial;return()=>h('div',{'data-module':props.id,'data-instance':instance,'data-active':props.active});}}}));
let app:App,host:HTMLDivElement,router:Router;
const item=(id:string):Website=>({id,name:id,icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:`https://${id}.test/`,origin:`https://${id}.test`,enabled:true,keep_alive:true,background:'solid',injection:{active:{enabled:true,css:'a{}',js:'',version:'v1',timing:'dom_ready',csp_policy:'reject'},draft:null,previous:null}});
async function flush(){await nextTick();await vi.dynamicImportSettled();await nextTick();}
async function open(id:string){await router.push(id?'/apps/'+id:'/');await flush();}
const node=(id:string)=>host.querySelector(`[data-module="${id}"]`);
beforeEach(async()=>{
 resetNavigation();Object.assign(auth,{me:{id:'owner'},sessionGeneration:0,sessionClosing:false});navigation.modules=['one','two','three','four'].map(item);navigation.loaded=true;
 router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}},{path:'/apps/:id',name:'external-module',component:{render:()=>null}}]});await router.push('/apps/one');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp(ExternalModuleCache).use(router);app.mount(host);await flush();
});
afterEach(()=>{app.unmount();host.remove();resetNavigation();});
it('retains at most three pages in LRU order without reordering or rebuilding the current frame',async()=>{
 const first=node('one');await open('two');await open('three');await open('one');expect(node('one')).toBe(first);
 await open('four');expect(host.querySelectorAll('[data-module]')).toHaveLength(3);expect(node('two')).toBeNull();expect(node('one')).toBe(first);
 auth.me={...auth.me!};await flush();expect(node('one')).toBe(first);
});
it('invalidates retained active injection changes but not background or draft-only edits',async()=>{
 const first=node('one');navigation.modules=[{...item('one'),background:'home'},...navigation.modules.slice(1)];await flush();expect(node('one')).toBe(first);
 navigation.modules[0]!.injection!.draft={...item('one').injection!.active!,version:'draft'};await flush();expect(node('one')).toBe(first);
 await open('two');navigation.modules[0]!.injection!.active!.version='v2';await flush();expect(node('one')).toBeNull();
 await open('one');expect(node('one')).not.toBe(first);
 const reloaded=node('one');navigation.modules[0]!.injection!.active!.enabled=false;await flush();expect(node('one')).not.toBe(reloaded);
});
it('drops all old-session frames even when a new owner has the same allowed module IDs',async()=>{
 const first=node('one');await open('two');auth.me={...auth.me!,id:'new-owner'};auth.sessionGeneration++;await flush();
 expect(node('one')).toBeNull();await open('one');expect(node('one')).not.toBe(first);
 auth.sessionClosing=true;await flush();expect(host.querySelectorAll('[data-module]')).toHaveLength(0);
});
it('unmounts hidden/disabled/removed pages and non-retained pages on leave',async()=>{
 navigation.modules[0]!.keep_alive=false;await flush();await open('two');expect(node('one')).toBeNull();
 navigation.entries=[{id:'two',visible:false}];await flush();expect(node('two')).toBeNull();expect(host.querySelector('[role=alert]')).not.toBeNull();
 await open('three');navigation.modules=navigation.modules.filter(m=>m.id!=='three');await flush();expect(node('three')).toBeNull();
});
