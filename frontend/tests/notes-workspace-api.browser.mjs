import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
const evidence=process.env.WORKSPACE_EVIDENCE || join(tmpdir(),'notes-workspace-evidence');

test('single workspace confirmation keeps counts, cancel, owner force, failure receipt and no destructive retry',async t=>{
 const cacheDir=await mkdtemp(join(tmpdir(),'notes-workspace-api-vite-'));
 const server=await createServer({configFile:false,appType:'custom',plugins:[vue()],cacheDir,server:{host:'127.0.0.1',port:0,proxy:{}},optimizeDeps:{entries:[],include:['vue','pinia']},logLevel:'error'});
 t.after(async()=>{await server.close();await rm(cacheDir,{recursive:true,force:true});});
 server.middlewares.use('/__workspace_api_fixture',async(_req,res,next)=>{
  try{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/__workspace_api_fixture',`<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div><script type="module">
  import {createApp,h} from 'vue';import {createPinia,setActivePinia} from 'pinia';import DocList from '/src/modules/notes/DocList.vue';import {useNotesStore} from '/src/stores/notes';import {auth} from '/src/modules/home/auth';import '/src/style.css';
  const pinia=createPinia();setActivePinia(pinia);auth.me={id:'alice'};auth.checked=true;const store=window.store=useNotesStore();Object.assign(store,{userId:'alice',workspaceId:'a',workspaces:[{id:'a',name:'研究笔记',user_id:'alice'},{id:'b',name:'旧资料',user_id:'alice'},{id:'c',name:'保留',user_id:'alice'}]});
  createApp({render:()=>h(DocList,{currentId:null,trashOpen:false,attachOpen:false,graphOpen:false})}).use(pinia).mount('#app');</script></html>`));}catch(e){next(e);}
 });
 await server.listen();await mkdir(evidence,{recursive:true});const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});t.after(()=>browser.close());
 for(const [name,viewport] of [['desktop',{width:1280,height:900}],['narrow',{width:390,height:844}]]){
  const context=await browser.newContext({viewport});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let existing=['a','b','c'];let failB=true;const calls=[];const blocked=[];
  const doc=(id,ws)=>({id,title:id,workspace_id:ws,parent_id:null,created_at:'2026',updated_at:'2026'});
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());if(url.origin!==origin){blocked.push(url.origin);return route.abort();}
   if(url.pathname.startsWith('/workspaces')){
    if(request.method()==='DELETE'){const id=url.pathname.split('/').at(-1);calls.push([id,url.searchParams.get('force')]);if(failB&&id==='b')return route.fulfill({status:409,json:{detail:{code:'attachment_in_use'}}});existing=existing.filter(v=>v!==id);return route.fulfill({status:204});}
    return route.fulfill({json:existing.map(id=>({id,name:({a:'研究笔记',b:'旧资料',c:'保留'})[id],user_id:'alice'}))});
   }
   if(url.pathname.startsWith('/documents')){const ws=url.searchParams.get('workspace_id');const rows=!existing.includes(ws)?[]:url.pathname==='/documents/trash'?(ws==='a'?[doc('trash','a')]:[]):url.pathname==='/documents/'?(ws==='a'?[doc('one','a'),doc('two','a')]:ws==='b'?[doc('other','b')]:[]):[];return route.fulfill({json:rows});}
   if(/^\/(auth|notes-preferences|notes-tools|tags|doc-tags)/.test(url.pathname))return route.fulfill({json:[]});
   await route.continue();
  });
  const open=async()=>{await page.locator('.ws-current').click();assert.equal(await page.getByText('批量删除工作区',{exact:true}).count(),0);await page.getByRole('button',{name:'删除工作区',exact:true}).click();};
  await page.goto(origin+'/__workspace_api_fixture');await open();const dialog=page.getByRole('dialog');await dialog.getByText('正常 2 篇 · 回收站 1 篇',{exact:true}).waitFor();assert.match(await dialog.innerText(),/共 3 篇/);
  assert.deepEqual(calls,[]);await page.screenshot({path:join(evidence,`single-confirm-${name}.png`)});const bounds=await dialog.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=viewport.width,'confirmation fits viewport');
  await page.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(calls,[]);assert.equal(await page.locator('.ws-current').evaluate(el=>el===document.activeElement),true);
  await open();await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await dialog.getByText('研究笔记：已删除',{exact:true}).waitFor();assert.deepEqual(calls,[['a','true']]);assert.equal(await page.evaluate(()=>window.store.workspaceId),'b');assert.deepEqual(existing,['b','c']);await page.getByRole('button',{name:'关闭',exact:true}).click();
  await open();await dialog.getByText('正常 1 篇 · 回收站 0 篇',{exact:true}).waitFor();await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await dialog.getByText('旧资料：删除失败',{exact:true}).waitFor();assert.deepEqual(calls,[['a','true'],['b','true']]);assert.equal(await dialog.getByRole('button',{name:'确认永久删除',exact:true}).count(),0);assert.deepEqual(existing,['b','c']);await page.screenshot({path:join(evidence,`single-failure-${name}.png`)});await page.getByRole('button',{name:'关闭',exact:true}).click();
  failB=false;await open();await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await dialog.getByText('旧资料：已删除',{exact:true}).waitFor();assert.deepEqual(calls,[['a','true'],['b','true'],['b','true']]);assert.deepEqual(existing,['c']);assert.equal(await page.evaluate(()=>window.store.workspaceId),'c');
  assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);await writeFile(join(evidence,`single-api-${name}.json`),JSON.stringify({calls,existing,blocked,errors},null,2));await context.close();
 }
});
