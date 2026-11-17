import {it,expect} from 'vitest';
import {createApp,nextTick} from 'vue';
import Page from './NavPage.vue';
import {createRouter,createMemoryHistory} from 'vue-router';
it('native page exposes search and group creation',async()=>{
 const host=document.createElement('div');document.body.append(host);
 const app=createApp(Page);app.use(createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]}));app.mount(host);await nextTick();
 expect(host.textContent).toContain('新增分组');
 app.unmount();host.remove();
});
