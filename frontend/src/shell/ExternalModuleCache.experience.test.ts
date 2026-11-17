import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, type App } from 'vue';
import { createRouter, createMemoryHistory, type Router } from 'vue-router';
import ExternalModuleCache from './ExternalModuleCache.vue';
import { auth } from '../modules/home/auth';
import { navigation, resetNavigation, type Website, type WebsiteSummary } from '../stores/navigation';
const state=vi.hoisted(()=>({serial:0}));
// Lifecycle/DOM fixture only: exercises the real cache and VueRouter, not a real remote drive.
vi.mock('./ExternalModulePage.vue',()=>({__esModule:true,default:{props:['id','active'],setup(props:any){const instance=++state.serial;return()=>h('div',{'data-module':props.id,'data-instance':instance,'data-active':props.active},[h('input',{'aria-label':'Unsubmitted draft'}),h('div',{style:'height:2000px'},'Scrollable fixture')]);}}}));
let app:App,host:HTMLDivElement,router:Router;
const item=(id:string):Website=>({id,name:id,icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:`https://${id}.test/`,origin:`https://${id}.test`,enabled:true,keep_alive:true,background:'solid',injection:{active:{enabled:true,css:'a{}',js:'',version:'v1',timing:'dom_ready',csp_policy:'reject'},draft:null,previous:null}});
// Independently model the summary wire contract: runtime changes invalidate,
// draft/history and background alone never reload an established iframe.
function summary(m:Website):WebsiteSummary {const {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id,background}=m;return {id,name,icon,mode,adapter,browser_url,enabled,keep_alive,template_id,background,runtime_revision:JSON.stringify([m.mode,m.adapter,m.browser_url,m.private_address,m.mapping_configured,m.alternate_address,m.entry_policy,m.target_id,m.initial_path,m.origin,m.connection,m.injection?.active])};}
async function flush(){await nextTick();await vi.dynamicImportSettled();await nextTick();}
async function open(id:string){await router.push(id?'/apps/'+id:'/');await flush();}
const node=(id:string)=>host.querySelector(`[data-module="${id}"]`);
beforeEach(async()=>{
 resetNavigation();Object.assign(auth,{me:{id:'owner'},sessionGeneration:0,sessionClosing:false});navigation.modules=['one','two','three','four'].map(id=>summary(item(id)));navigation.loaded=true;
 router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}},{path:'/notes',name:'notes',component:{render:()=>h('main','Notes fixture')}},{path:'/apps/:id',name:'external-module',component:{render:()=>null}}]});await router.push('/apps/one');await router.isReady();
 host=document.createElement('div');document.body.append(host);app=createApp(ExternalModuleCache).use(router);app.mount(host);await flush();
});
afterEach(()=>{app.unmount();host.remove();resetNavigation();});
it('retains at most three pages in LRU order without reordering or rebuilding the current frame',async()=>{
 navigation.modules.forEach((m,index)=>{m.keep_alive=index%2?undefined:false;});await flush();
 const first=node('one');await open('two');await open('three');await open('one');expect(node('one')).toBe(first);
 await open('four');expect(host.querySelectorAll('[data-module]')).toHaveLength(3);expect(node('two')).toBeNull();expect(node('one')).toBe(first);
 auth.me={...auth.me!};await flush();expect(node('one')).toBe(first);
});
it('invalidates retained active injection changes but not background or draft-only edits',async()=>{
 const detail=item('one'),first=node('one');detail.background='home';navigation.modules=[summary(detail),...navigation.modules.slice(1)];await flush();expect(node('one')).toBe(first);
 detail.injection!.draft={...detail.injection!.active!,version:'draft'};navigation.modules[0]=summary(detail);await flush();expect(node('one')).toBe(first);
 await open('two');detail.injection!.active!.version='v2';navigation.modules[0]=summary(detail);await flush();expect(node('one')).toBeNull();
 await open('one');expect(node('one')).not.toBe(first);
 const reloaded=node('one');detail.injection!.active!.enabled=false;navigation.modules[0]=summary(detail);await flush();expect(node('one')).not.toBe(reloaded);
});
it.each([{alternate_address:'https://new-other.test/path?q=1#x'},{mapping_configured:true},{private_address:'https://one.p.test/'},{entry_policy:'public' as const},{browser_url:'https://new.test/'},{target_id:'new-target'},{connection:{transport:'proxy' as const,auth_mode:'original' as const,header_name:'Authorization',injection_delivery:'proxy' as const}}])('invalidates a retained frame when connection/entry options change: %j',async(change)=>{
 const first=node('one');navigation.modules[0]=summary({...item('one'),...change});await flush();expect(node('one')).not.toBe(first);
});
it('invalidates from an opaque runtime revision without any editor code in the first-read DTO',async()=>{
 const first=node('one');navigation.modules[0]={...navigation.modules[0]!,runtime_revision:'changed-active-runtime'} as any;await flush();expect(node('one')).not.toBe(first);
});
it('drops all old-session frames even when a new owner has the same allowed module IDs',async()=>{
 const first=node('one');await open('two');auth.me={...auth.me!,id:'new-owner'};auth.sessionGeneration++;await flush();
 expect(node('one')).toBeNull();await open('one');expect(node('one')).not.toBe(first);
 auth.sessionClosing=true;await flush();expect(host.querySelectorAll('[data-module]')).toHaveLength(0);
});
it.each([false,undefined])('automatically retains legacy keep_alive=%s through notes with the exact instance, scroll and unsaved input',async(legacy)=>{
 navigation.modules[0]!.keep_alive=legacy;await flush();const first=node('one') as HTMLElement;
 const input=first.querySelector('input')!;input.value='not submitted';first.scrollTop=274;
 await router.push('/notes');await flush();expect(node('one')).toBe(first);expect(first.style.display).toBe('none');
 await open('one');expect(node('one')).toBe(first);expect(first.scrollTop).toBe(274);expect(first.querySelector('input')).toBe(input);expect(input.value).toBe('not submitted');
});
it('ignores obsolete keep_alive changes without rebuilding an active or retained document',async()=>{
 const first=node('one');navigation.modules[0]!.keep_alive=false;await flush();expect(node('one')).toBe(first);
 await open('two');delete navigation.modules[0]!.keep_alive;await flush();expect(node('one')).toBe(first);
 await open('one');expect(node('one')).toBe(first);
});
it.each(['hide','disable','delete'])('immediately removes active and hidden pages on %s',async(operation)=>{
 await open('two');
 if(operation==='hide')navigation.entries=[{id:'one',visible:false},{id:'two',visible:false}];
 if(operation==='disable')for(const m of navigation.modules)m.enabled=false;
 if(operation==='delete')navigation.modules=[];
 await flush();expect(node('one')).toBeNull();expect(node('two')).toBeNull();expect(host.querySelector('[role=alert]')).not.toBeNull();
});
it('does not retain external links on leave and invalidates mode changes',async()=>{
 const first=node('one');navigation.modules[0]!.mode='link';await flush();expect(node('one')).not.toBe(first);
 await open('two');expect(node('one')).toBeNull();
 navigation.modules[0]!.mode='iframe';await open('one');expect(node('one')).not.toBe(first);await open('two');expect(node('one')).not.toBeNull();
});
it('fresh cache mount after refresh cannot restore a previous DOM document',async()=>{
 const first=node('one');first!.querySelector('input')!.value='old document';app.unmount();
 app=createApp(ExternalModuleCache).use(router);app.mount(host);await flush();expect(node('one')).not.toBe(first);expect(node('one')!.querySelector('input')!.value).toBe('');
});
it('drops all frames on logout even if the same owner logs back in within the tick',async()=>{
 const first=node('one');await open('two');const owner=auth.me;auth.me=null;auth.me=owner;await flush();expect(node('one')).toBeNull();await open('one');expect(node('one')).not.toBe(first);
});
it('invalidates an old session generation even without an owner ID change',async()=>{
 const first=node('one');await open('two');auth.sessionGeneration++;await flush();expect(node('one')).toBeNull();await open('one');expect(node('one')).not.toBe(first);
});
