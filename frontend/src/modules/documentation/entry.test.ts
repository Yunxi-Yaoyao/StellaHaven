import {afterEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createMemoryHistory,createRouter} from 'vue-router';
import {readFileSync} from 'node:fs';
vi.mock('../home/auth',()=>({auth:{checked:true,me:null,sessionClosing:false,error:''},loggedIn:{value:false},currentAvatar:{value:''},fetchMe:vi.fn()}));
import SideBar from '../../shell/SideBar.vue';
let app:App;afterEach(()=>{app?.unmount();document.body.innerHTML='';});
it('exposes a system documentation link without adding a persisted navigation item',async()=>{
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}},{path:'/help',component:{render:()=>null}},{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});await router.push('/');await router.isReady();
 const host=document.createElement('div');document.body.append(host);app=createApp(SideBar,{collapsed:false,mobileOpen:false}).use(router);app.mount(host);await nextTick();
 const help=[...host.querySelectorAll('a')].find(a=>a.textContent?.includes('文档中心'));expect(help?.getAttribute('href')).toBe('/help');
 const nav=readFileSync('src/stores/navigation.ts','utf8');expect(nav).not.toContain("to:'/help'");
 const route=readFileSync('src/router/index.ts','utf8');expect(route).toContain('DocumentationPage.vue');expect(route).toContain('path: "/help"');
});
