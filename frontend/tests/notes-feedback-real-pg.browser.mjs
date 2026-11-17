import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';

// Invoked only by the PG fixture: no resident URL/default is accepted.
const backend=process.env.NOTES_FEEDBACK_BACKEND;
assert.match(backend??'',/^http:\/\/127\.0\.0\.1:\d+$/);
const seed=JSON.parse(process.env.NOTES_FEEDBACK_SEED??'null');
assert.ok(seed?.owner&&seed?.workspace&&seed?.root&&process.env.NOTES_FEEDBACK_TOKEN);
const evidence=process.env.NOTES_FEEDBACK_EVIDENCE;
assert.ok(evidence);

test('real Notes directory batch and protected-template workspace removal over HTTP + PG',async t=>{
 const cacheDir=await mkdtemp(join(tmpdir(),'notes-feedback-vite-'));
 const proxy=Object.fromEntries(['/documents','/workspaces','/notes-preferences','/notes-tools','/tags','/doc-tags'].map(path=>[path,{target:backend,changeOrigin:true}]));
 const server=await createServer({configFile:false,appType:'custom',plugins:[vue()],cacheDir,server:{host:'127.0.0.1',port:0,proxy},optimizeDeps:{entries:[],include:['vue','pinia']},logLevel:'error'});
 t.after(async()=>{await server.close();await rm(cacheDir,{recursive:true,force:true});});
 server.middlewares.use('/__notes_feedback',async(_req,res,next)=>{
  try{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/__notes_feedback',`<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div><script type="module">
  import {createApp,h} from 'vue';import {createPinia,setActivePinia} from 'pinia';import DocList from '/src/modules/notes/DocList.vue';import DeleteNoteDialog from '/src/modules/notes/DeleteNoteDialog.vue';import {useNotesStore} from '/src/stores/notes';import {auth} from '/src/modules/home/auth';import '/src/style.css';
  const pinia=createPinia();setActivePinia(pinia);auth.me={id:${JSON.stringify(seed.owner)}};auth.checked=true;const store=window.store=useNotesStore();store.userId=${JSON.stringify(seed.owner)};store.workspaceId=${JSON.stringify(seed.workspace)};store.templateRootId=${JSON.stringify(seed.root)};await Promise.all([store.refreshList(),store.refreshWorkspaces()]);
  window.barriers=[];createApp({render:()=>h('div',[h(DocList,{currentId:null,trashOpen:false,attachOpen:false,graphOpen:false,beforeWorkspaceDelete:async()=>{window.barriers.push('workspace');return true;}}),store.pendingDelete?h(DeleteNoteDialog,{beforeTrash:async ids=>{window.barriers.push([...ids]);return true;}}):null])}).use(pinia).mount('#app');window.ready=true;</script></html>`));}catch(e){next(e);}
 });
 await server.listen();await mkdir(evidence,{recursive:true});const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});t.after(()=>browser.close());
 const context=await browser.newContext({viewport:{width:1280,height:900}});t.after(()=>context.close());
 await context.addCookies([{name:'stella_at',value:process.env.NOTES_FEEDBACK_TOKEN,url:origin}]);
 const page=await context.newPage(),errors=[],blocked=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='DELETE')writes.push(new URL(r.url()).pathname+new URL(r.url()).search);});
 await page.route('**/*',async route=>new URL(route.request().url()).origin===origin?route.continue():(blocked.push(route.request().url()),route.abort()));
 const read=async path=>{const r=await page.request.get(origin+path);assert.equal(r.status(),200,await r.text());return r.json();};
 const create=async(title,parent_id=null)=>{const r=await page.request.post(origin+'/documents/',{data:{workspace_id:seed.workspace,title,file_path:'/feedback/'+crypto.randomUUID(),content:'synthetic feedback fixture',parent_id}});assert.equal(r.status(),201,await r.text());return r.json();};
 const prefs=async(fields)=>{const p=await read('/notes-preferences');const r=await page.request.patch(origin+'/notes-preferences',{data:{expected_revision:p.revision,...fields}});assert.equal(r.status(),200,await r.text());};
 const choose=async titles=>{await page.getByRole('button',{name:'批量删除笔记',exact:true}).click();for(const title of titles)await page.getByRole('checkbox',{name:`选择笔记：${title}`,exact:true}).check();await page.getByRole('button',{name:`删除所选（${titles.length}）`,exact:true}).click();};
 await page.goto(origin+'/__notes_feedback');await page.waitForFunction(()=>window.ready);
 await page.locator('.ws-current').click();assert.equal(await page.getByText('批量删除工作区',{exact:true}).count(),0);await page.locator('.ws-current').click();
 const a=await create('反馈甲'),b=await create('反馈乙');await page.evaluate(()=>window.store.refreshList());
 await choose(['反馈甲','反馈乙']);const dialog=page.getByRole('dialog');await dialog.getByText('批量删除 2 篇笔记',{exact:true}).waitFor();
 assert.equal(writes.length,0);await page.screenshot({path:join(evidence,'notes-batch-confirm-desktop.png')});
 await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.equal(writes.length,0);
 await choose(['反馈甲','反馈乙']);await dialog.getByRole('button',{name:'确认移入回收站',exact:true}).click();await dialog.waitFor({state:'detached'});
 assert.equal(writes.length,2);assert.ok(writes.every(p=>!p.includes('/permanent')&&p.includes('scope_token=')&&p.includes('cascade=false')));
 const trash=await read('/documents/trash?workspace_id='+seed.workspace);assert.ok([a.id,b.id].every(id=>trash.some(d=>d.id===id)));
 const active=await read('/documents/?workspace_id='+seed.workspace);assert.ok(active.some(d=>d.id===seed.root));
 // A remembered trash preference auto-runs only ordinary leaves, never permanent.
 await prefs({delete_action:'trash',ask_before_delete:false});const auto=await create('记住回收站');await page.evaluate(()=>window.store.refreshList());await choose(['记住回收站']);await page.waitForFunction(()=>!window.store.pendingDelete);assert.equal(writes.length,3);assert.ok(!writes.at(-1).includes('/permanent'));
 // Explicit permanent choice uses the same server lifecycle, only after a click.
 await prefs({ask_before_delete:true});const permanent=await create('明确永久');await page.evaluate(()=>window.store.refreshList());await choose(['明确永久']);await dialog.getByRole('radio',{name:'永久删除 不可恢复',exact:true}).check();await dialog.getByRole('button',{name:'确认永久删除',exact:true}).click();await dialog.waitFor({state:'detached'});assert.equal((await page.request.get(origin+'/documents/'+permanent.id)).status(),404);assert.ok(writes.at(-1).includes('/permanent'));
 // A lost ACK is injected only after the real backend committed the second
 // DELETE. Recovery must be read-only and must not replay either document.
 const lostA=await create('丢回执甲'),lostB=await create('丢回执乙');await page.evaluate(()=>window.store.refreshList());
 const lostPath=`**/documents/${lostB.id}?*`;let dropped=false;
 await page.route(lostPath,async route=>{if(route.request().method()!=='DELETE'||dropped)return route.continue();dropped=true;const response=await route.fetch();assert.equal(response.status(),204);await route.abort('failed');});
 const lostStart=writes.length;await choose(['丢回执甲','丢回执乙']);await dialog.getByRole('button',{name:'确认移入回收站',exact:true}).click();await dialog.getByText(/批量删除已停止/).waitFor();await page.screenshot({path:join(evidence,'batch-lost-ack-real-pg.png')});assert.equal(writes.length,lostStart+2);
 await dialog.getByRole('button',{name:'刷新列表核对',exact:true}).click();await dialog.waitFor({state:'detached'});assert.equal(writes.length,lostStart+2);await page.unroute(lostPath);
 const afterLost=await read('/documents/trash?workspace_id='+seed.workspace);assert.ok([lostA.id,lostB.id].every(id=>afterLost.some(d=>d.id===id)));
 // Keep-children applies to selected notes only, not their unselected child.
 const keepParent=await create('保留子页父'),keepChild=await create('保留子页',keepParent.id),keepOther=await create('保留子页同批');await page.evaluate(()=>window.store.refreshList());await choose(['保留子页父','保留子页同批']);await dialog.getByRole('radio',{name:/仅删所选笔记/}).check();await dialog.getByRole('button',{name:'确认移入回收站',exact:true}).click();await dialog.waitFor({state:'detached'});const retained=await read('/documents/'+keepChild.id);assert.equal(retained.parent_id,null);assert.ok(!(await read('/documents/?workspace_id='+seed.workspace)).some(d=>d.id===keepParent.id||d.id===keepOther.id));
 // Narrow screen, parent+child overlap must require explicit child scope and
 // deduplicate cascade roots rather than replaying a child DELETE.
 await page.setViewportSize({width:390,height:844});const parent=await create('父笔记'),child=await create('子笔记',parent.id);await page.evaluate(()=>{localStorage.setItem('stella_tree_expanded',JSON.stringify([]));window.store.refreshList();});
 await page.reload();await page.waitForFunction(()=>window.ready);await page.locator(`[data-import-parent="${parent.id}"] .caret`).click();await choose(['父笔记','子笔记']);await dialog.getByText(/包含子页面/).waitFor();assert.equal(await dialog.getByRole('button',{name:'确认移入回收站',exact:true}).isDisabled(),true);await dialog.getByRole('radio',{name:/一起删除/}).check();await page.waitForFunction(()=>{const b=[...document.querySelectorAll('[role=dialog] button')].find(b=>b.textContent==='确认移入回收站');return b&&!b.disabled;});await dialog.getByText('本次范围：2 篇笔记',{exact:true}).waitFor();await page.screenshot({path:join(evidence,'notes-batch-confirm-narrow.png')});const previous=writes.length;await dialog.getByRole('button',{name:'确认移入回收站',exact:true}).click();await dialog.waitFor({state:'detached'});assert.equal(writes.length,previous+1);assert.ok(writes.at(-1).includes(parent.id));
 // Existing single workspace delete: active/trash counts, cancel, explicit force.
 await page.locator('.ws-current').click();await page.getByRole('button',{name:'删除工作区',exact:true}).click();await dialog.getByText(/共 .*篇笔记/).waitFor();await page.screenshot({path:join(evidence,'workspace-single-confirm-narrow.png')});const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=390);await dialog.getByRole('button',{name:'取消',exact:true}).click();assert.equal(writes.length,previous+1);
 await page.locator('.ws-current').click();await page.getByRole('button',{name:'删除工作区',exact:true}).click();await dialog.getByRole('button',{name:'确认永久删除',exact:true}).click();await dialog.getByText('反馈工作区：已删除',{exact:true}).waitFor();assert.equal((await page.request.get(origin+'/workspaces/'+seed.workspace)).status(),404);assert.ok(writes.at(-1).includes('force=true'));
 assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);await writeFile(join(evidence,'browser-real-pg.json'),JSON.stringify({writes,errors,blocked,barriers:await page.evaluate(()=>window.barriers),trashed:[a.id,b.id,auto.id,parent.id,child.id]},null,2));
});
