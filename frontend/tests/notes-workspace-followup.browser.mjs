import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';

const evidence=process.env.WORKSPACE_EVIDENCE || join(tmpdir(),'notes-workspace-evidence');
const phase=process.env.WORKSPACE_PHASE || 'green';
const title='这是一篇很长的中文笔记标题，需要在目录中完整换行阅读而不是被按钮挤成省略号';
const unbroken='LongUnbrokenWorkspaceDocumentTitle'.repeat(4);

test('real DocList geometry: desktop/narrow wrapping, overlay controls, tree and touch',async t=>{
 const cacheDir=await mkdtemp(join(tmpdir(),'notes-workspace-vite-'));
 const server=await createServer({configFile:false,appType:'custom',plugins:[vue()],cacheDir,server:{host:'127.0.0.1',port:0,proxy:{}},optimizeDeps:{entries:[],include:['vue','pinia']},logLevel:'error'});
 t.after(async()=>{await server.close();await rm(cacheDir,{recursive:true,force:true});});
 server.middlewares.use('/__workspace_fixture',async(_req,res,next)=>{
  try {res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/__workspace_fixture',`<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><body><div id="app"></div><script type="module">
  import {createApp,h,nextTick} from 'vue';import {createPinia,setActivePinia} from 'pinia';
  import DocList from '/src/modules/notes/DocList.vue';import {useNotesStore} from '/src/stores/notes';import {auth} from '/src/modules/home/auth';import '/src/style.css';
  const pinia=createPinia();setActivePinia(pinia);auth.me={id:'alice'};auth.checked=true;window.store=useNotesStore();window.tick=nextTick;window.events=[];
  const doc=(id,title,parent_id=null)=>({id,title,parent_id,workspace_id:'a',created_at:'2026',updated_at:'2026',is_favorite:id==='long',has_draft:id==='long'});
  const docs=[doc('long',${JSON.stringify(title)}),doc('child',${JSON.stringify(unbroken)},'long'),doc('short','简短标题')];
  Object.assign(window.store,{userId:'alice',workspaceId:'a',workspaces:[{id:'a',name:'研究笔记',user_id:'alice'},{id:'b',name:'旧资料',user_id:'alice'},{id:'c',name:'保留',user_id:'alice'}],docs,allDocs:docs,recent:[docs[0]]});
  localStorage.setItem('stella_tree_expanded',JSON.stringify(['long']));
  createApp({render:()=>h(DocList,{currentId:'long',trashOpen:false,attachOpen:false,graphOpen:false,onDel:n=>window.events.push(n.id)})}).use(pinia).mount('#app');
  </script></body></html>`));}catch(e){next(e);}
 });
 await server.listen();await mkdir(evidence,{recursive:true});
 const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});t.after(()=>browser.close());
 const metrics=[];
 for(const [name,viewport,touch] of [['desktop',{width:1280,height:900},false],['narrow',{width:390,height:844},true]]){
  const context=await browser.newContext({viewport,hasTouch:touch,isMobile:touch});const page=await context.newPage();
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.origin!==origin)return route.abort();
   if(/^\/(documents|workspaces|auth|notes-preferences|notes-tools|tags|doc-tags|document-views)/.test(url.pathname))throw new Error(`Unexpected API in geometry fixture: ${url.pathname}`);
   await route.continue();
  });
  await page.goto(origin+'/__workspace_fixture');await page.locator('.row[data-import-parent=long] .text').waitFor();await page.mouse.move(1000,850);
  const geometry=await page.evaluate(()=>{
   const row=document.querySelector('.row[data-import-parent=long]'),text=row.querySelector('.text'),actions=row.querySelector('.actions'),child=document.querySelector('.row[data-import-parent=child]');
   const rect=e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,right:e.getBoundingClientRect().right});
   return {row:rect(row),text:rect(text),child:rect(child),actionsPosition:getComputedStyle(actions).position,whiteSpace:getComputedStyle(text).whiteSpace,scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,recentHeight:document.querySelector('.flat-item').getBoundingClientRect().height};
  });metrics.push({name,...geometry});
  await page.screenshot({path:join(evidence,`titles-${name}-${phase}.png`),fullPage:true});
  await writeFile(join(evidence,`geometry-${phase}.json`),JSON.stringify(metrics,null,2));
  assert.equal(geometry.actionsPosition,'absolute','hidden controls must not consume title width');
  assert.equal(geometry.whiteSpace,'normal','tree titles wrap naturally');assert.ok(geometry.text.height>32,'long title displays multiple readable lines');
  assert.ok(geometry.text.width>geometry.row.width-95,'title uses full row width minus original icons/indent/indicators');
  assert.ok(geometry.recentHeight>40,'recent titles also wrap');assert.ok(geometry.scrollWidth<=geometry.viewport,'no horizontal page overflow');
  const first=page.locator('.row[data-import-parent=long]');const before=await first.boundingBox();
  if(!touch)await first.hover();
  const del=first.getByRole('button',{name:'删除',exact:true});await del.focus();assert.equal(await del.evaluate(el=>getComputedStyle(el.parentElement).opacity),'1');
  await page.screenshot({path:join(evidence,`titles-${name}-controls-${phase}.png`),fullPage:true});
  assert.deepEqual(await first.boundingBox(),before,'hover/focus controls do not reflow row');await del.click();assert.deepEqual(await page.evaluate(()=>window.events),['long']);
  const childText=page.locator('.row[data-import-parent=child] .text');assert.ok(await childText.evaluate(el=>el.scrollWidth<=el.clientWidth),'unbroken child title stays within available width');
  assert.ok(await page.locator('.row[data-import-parent=child] .caret').count(),'child indent and icons retained');
  await context.close();
 }
});
