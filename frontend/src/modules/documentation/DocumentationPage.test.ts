import {afterEach,beforeAll,expect,it,vi} from 'vitest';
beforeAll(()=>{HTMLDialogElement.prototype.close=vi.fn();HTMLDialogElement.prototype.showModal=vi.fn();});
import {createApp,nextTick} from 'vue';
import {createMemoryHistory,createRouter} from 'vue-router';
import DocumentationPage from './DocumentationPage.vue';
let cleanup=()=>{};
afterEach(()=>{cleanup();localStorage.clear();document.body.innerHTML='';});
it('ignores syntactically valid but malformed documentation-only cache',async()=>{
 localStorage.setItem('stella_doc_center_reading_v1','null');
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/help',component:DocumentationPage}]});await router.push('/help');await router.isReady();
 const host=document.createElement('div');document.body.append(host);const app=createApp(DocumentationPage).use(router);cleanup=()=>app.unmount();
 expect(()=>app.mount(host)).not.toThrow();await nextTick();expect(host.querySelector('article')?.textContent).toContain('开始使用');
});
it('reads both guide and API from one searchable directory without executing examples',async()=>{
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/help',component:DocumentationPage}]});
 await router.push('/help');await router.isReady();
 const root=document.createElement('div');document.body.append(root);
 const app=createApp(DocumentationPage).use(router);app.mount(root);cleanup=()=>app.unmount();await nextTick();
 expect(root.textContent).toContain('使用指南');expect(root.textContent).toContain('API 参考');
 expect(root.querySelector('article')?.textContent).toContain('开始使用');
 const api=[...root.querySelectorAll('button')].find(b=>b.textContent==='API 参考')!;api.click();await nextTick();await nextTick();
 expect(root.querySelector('article')?.textContent).toContain('认证与会话');
 const search=root.querySelector<HTMLInputElement>('input[type="search"]')!;search.value='不可能命中的文档词xyz';search.dispatchEvent(new Event('input'));await nextTick();
 expect(root.textContent).toContain('没有找到相关文档');
 expect(root.querySelector('iframe,script')).toBeNull();
});
