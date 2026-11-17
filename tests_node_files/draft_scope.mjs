// Real Vue, FastAPI, independent FileWorker and owned disk bytes. Only the
// metadata-denial receipt is synthetic; actual successful edits are never mocked.
import {createServer} from '../frontend/node_modules/vite/dist/node/index.js';
import vue from '../frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const repo=dirname(dirname(fileURLToPath(import.meta.url))), cfg=JSON.parse(await readFile(process.argv[2],'utf8'));
const receipt={commit:execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim(),sourceSha256:createHash('sha256').update(await readFile(join(repo,'frontend/src/modules/servers/NodeFilesView.vue'))).digest('hex'),checks:[],requests:[],dialogs:[]};
const names=['draft-a.txt','draft-b.txt'],initial=['A · 原文\n','B · 新文件正文\n'],oldDraft='A 的未保存草稿，不能落到 B\n';
for(let i=0;i<2;i++)await writeFile(join(cfg.root,names[i]),initial[i]);
async function bytes(){return Object.fromEntries(await Promise.all(names.map(async name=>{const body=await readFile(join(cfg.root,name));return [name,{text:body.toString('utf8'),sha256:createHash('sha256').update(body).digest('hex')}]})))}
receipt.before=await bytes();
const server=await createServer({root:join(repo,'frontend'),configFile:false,appType:'custom',plugins:[vue()],cacheDir:join(dirname(cfg.root),'draft-vite-cache'),optimizeDeps:{entries:[],include:['vue']},server:{host:'127.0.0.1',port:0,proxy:{'/node-files':{target:cfg.backend,changeOrigin:false}}},logLevel:'error'});
server.middlewares.use('/__draft',async(_req,res,next)=>{try{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/__draft',`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><div id="app"></div><script type="module">import {createApp} from 'vue';import '@fontsource-variable/inter';import '/src/style.css';import View from '/src/modules/servers/NodeFilesView.vue';createApp(View,{scopeKey:'draft-owned-session'}).mount('#app');</script>`));}catch(e){next(e)}});
await server.listen();let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.STELLA_CHROMIUM||'/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome',args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 await context.addCookies([{name:'stella_at',value:cfg.cookie,url:origin,httpOnly:true,sameSite:'Lax'}]);
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 // Persist bounded crash evidence before each unchanged full-page capture.
 // A passing replay is not proof that a prior renderer/browser crash is fixed.
 receipt.browserVersion=browser.version();receipt.screenshots=[];
 async function resourceSnapshot(){
   return Object.fromEntries(await Promise.all(['memory.events','memory.current','memory.peak','memory.max','pids.current','pids.events','pids.max'].map(async key=>[key,await readFile('/sys/fs/cgroup/'+key,'utf8').catch(error=>'unavailable: '+error.code)])));
 }
 page.on('crash',()=>{receipt.browserCrashed=true});
 async function screenshot(name){
   const entry={name,before:await resourceSnapshot(),geometry:await page.evaluate(()=>({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,viewport:{width:innerWidth,height:innerHeight},devicePixelRatio}))};
   receipt.screenshots.push(entry);
   await writeFile(join(cfg.evidence,'draft-scope-screenshot-diagnostics.json'),JSON.stringify({browserVersion:receipt.browserVersion,screenshots:receipt.screenshots},null,2));
   try{await page.screenshot({path:join(cfg.evidence,name),fullPage:true});entry.completed=true}
   finally{entry.after=await resourceSnapshot();await writeFile(join(cfg.evidence,'draft-scope-screenshot-diagnostics.json'),JSON.stringify({browserVersion:receipt.browserVersion,browserCrashed:receipt.browserCrashed||false,screenshots:receipt.screenshots},null,2))}
 }
 let accept=false;
 page.on('dialog',async d=>{receipt.dialogs.push({type:d.type(),message:d.message(),accept});await (accept?d.accept():d.dismiss())});
 page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/node-files/requests')receipt.requests.push(r.postDataJSON())});
 const button=name=>page.getByRole('button',{name,exact:true}),editor=page.getByLabel('文件内容',{exact:true}),preview=page.getByRole('region',{name:'文本预览'});
 const idle=()=>page.waitForFunction(()=>!document.querySelector('.node-files>header button').disabled);
 const title=()=>preview.locator('h3').textContent();
 const picker=name=>page.locator('.dd').and(page.getByLabel(name,{exact:true}));
 async function pick(name,label){const dd=picker(name);await dd.locator('.dd-btn').click();await dd.getByRole('option',{name:label,exact:true}).click();await idle()}
 await page.goto(origin+'/__draft');await button(names[0]).waitFor();await idle();
 await button(names[0]).click();await button('编辑文本').click();await editor.fill(oldDraft);
 let refused=false;
 await page.route('**/node-files/requests',async route=>{if(!refused&&route.request().postDataJSON()?.op==='edit'){refused=true;await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'metadata_preservation_denied'})})}else await route.continue()});
 await button('保存文件').click();await page.getByRole('alert').filter({hasText:'无法保持原文件权限'}).waitFor();
 assert.equal(await editor.inputValue(),oldDraft);assert.deepEqual(await bytes(),receipt.before);
 receipt.checks.push('synthetic existing metadata-denial retains draft; real disk unchanged');
 await screenshot('denied-draft.png');
 const beforeCancel=receipt.requests.length;
 await button('关闭').click();
 if(!receipt.dialogs.length){
   // Baseline defect exploration: do NOT assume a stale visible draft implies
   // a write. Actually save it to the second owned file and read both bytes.
   assert.equal(await preview.count(),0);await button(names[1]).click();await idle();
   receipt.baseline={title:await title(),editing:await editor.count(),draft:await editor.inputValue()};
   await screenshot('baseline-stale-b.png');
   await button('保存文件').click();await page.getByText('文件已保存。',{exact:true}).waitFor();
   receipt.baseline.after=await bytes();
   receipt.baseline.wrongTargetWrite=receipt.baseline.after[names[0]].text===initial[0]&&receipt.baseline.after[names[1]].text===oldDraft;
   assert.equal(receipt.baseline.wrongTargetWrite,true);
   throw Error('RED: closing denied dirty preview had no discard confirmation; stale A draft was actually saved to B using B CAS etag');
 }
 assert.equal(await title(),names[0]);assert.equal(await editor.inputValue(),oldDraft);
 assert.equal(receipt.requests.length,beforeCancel);assert.deepEqual(await bytes(),receipt.before);
 receipt.checks.push('cancel close preserves selected A/draft, zero requests and zero disk writes');
 // Direct file, directory, breadcrumb, node and root cancellation all preserve
 // both the selected file and picker value, without even sending reads.
 for(const action of [()=>button(names[1]).click(),()=>button('folder').click(),()=>page.getByRole('navigation',{name:'路径'}).getByRole('button').click(),()=>pick('允许根','只读目录'),()=>pick('节点','离线文件节点 · 离线')]){
   const count=receipt.requests.length,dialogs=receipt.dialogs.length;await action();
   assert.equal(receipt.dialogs.length,dialogs+1);assert.equal(await title(),names[0]);assert.equal(await editor.inputValue(),oldDraft);assert.equal(receipt.requests.length,count);
   assert.match(await picker('允许根').locator('.dd-btn').textContent(),/验收目录/);assert.match(await picker('节点').locator('.dd-btn').textContent(),/隔离文件节点/);assert.deepEqual(await bytes(),receipt.before);
 }
 receipt.checks.push('cancel direct file/directory/breadcrumb/root/node preserves draft+selection; zero requests/writes');
 accept=true;await button('关闭').click();assert.equal(await preview.count(),0);
 await button(names[1]).click();await button('编辑文本').waitFor();assert.equal(await editor.count(),0);assert.equal(await preview.locator('pre').textContent(),initial[1]);
 await button('编辑文本').click();assert.equal(await editor.inputValue(),initial[1]);
 await screenshot('confirmed-b-fresh-editor.png');
 const bDraft='B · 正确的新草稿\n';await editor.fill(bDraft);await button('保存文件').click();await page.getByText('文件已保存。',{exact:true}).waitFor();
 const expected=await bytes();assert.equal(expected[names[0]].text,initial[0]);assert.equal(expected[names[1]].text,bDraft);receipt.correctTargetAfterSave=expected;
 let dialogs=receipt.dialogs.length;await button('关闭').click();assert.equal(receipt.dialogs.length,dialogs);
 receipt.checks.push('confirmed close clears editing/draft; B initializes from B; real save modifies only B; saved close no prompt');
 // A real filesystem CAS conflict, not a synthesized failed edit response.
 await button(names[0]).click();await button('编辑文本').click();await editor.fill(oldDraft);
 await writeFile(join(cfg.root,names[0]),'A · external CAS version\n');
 await button('保存文件').click();await page.getByRole('alert').filter({hasText:'草稿已保留'}).waitFor();assert.equal(await editor.inputValue(),oldDraft);
 const casBytes=await bytes(),count=receipt.requests.length;accept=false;await button(names[1]).click();assert.equal(await title(),names[0]);assert.equal(await editor.inputValue(),oldDraft);assert.equal(receipt.requests.length,count);assert.deepEqual(await bytes(),casBytes);
 accept=true;await button(names[1]).click();await button('编辑文本').waitFor();assert.equal(await preview.locator('pre').textContent(),bDraft);await button('编辑文本').click();assert.equal(await editor.inputValue(),bDraft);
 receipt.checks.push('real CAS conflict retains A; cancel switch zero writes; confirmed direct switch initializes B');
 // Clean editing is not dirty. Read-only preview also has no extra prompt.
 dialogs=receipt.dialogs.length;await button('关闭').click();assert.equal(receipt.dialogs.length,dialogs);
 await pick('允许根','只读目录');await button('read-only.txt').click();await preview.waitFor();await button('关闭').click();assert.equal(receipt.dialogs.length,dialogs);
 await pick('允许根','验收目录');await button(names[0]).click();await preview.waitFor();await button('关闭').click();assert.equal(receipt.dialogs.length,dialogs);
 receipt.checks.push('unchanged editor and read-only/plain preview close without confirmation');
 // Hold a real list admission receipt, unchanged, while a dirty editor remains
 // mounted. Busy close/node/root/directory cannot bypass draft admission.
 await button(names[1]).click();await button('编辑文本').click();await editor.fill(oldDraft);
 let release,ready;const gate=new Promise(r=>release=r),readyGate=new Promise(r=>ready=r);
 await page.route('**/node-files/requests',async route=>{if(route.request().postDataJSON()?.op==='list'){const actual=await route.fetch();ready();await gate;await route.fulfill({response:actual})}else await route.fallback()});
 await button('刷新').click();await readyGate;
 assert.equal(await button('关闭').isDisabled(),true);assert.equal(await button('folder').isDisabled(),true);assert.equal(await button(names[0]).isDisabled(),true);
 for(const name of ['节点','允许根','排序'])assert.equal(await picker(name).locator('.dd-btn').isDisabled(),true);
 const busyCount=receipt.requests.length,busyBytes=await bytes();accept=false;await button('取消').click();assert.equal(await editor.inputValue(),oldDraft);assert.equal(await title(),names[1]);assert.equal(receipt.requests.length,busyCount);assert.deepEqual(await bytes(),busyBytes);
 release();await idle();assert.equal(await editor.inputValue(),oldDraft);await page.unroute('**/node-files/requests');
 receipt.checks.push('real held list receipt: busy close/node/root/directory disabled; cancel abort dismissal preserves draft and bytes');
 // Accepted dirty transitions clear state too; return through actual reads.
 accept=true;await button('folder').click();await idle();assert.equal(receipt.requests.at(-1).path,'folder');assert.equal(await preview.count(),0);
 await page.getByRole('navigation',{name:'路径'}).getByRole('button',{name:'验收目录',exact:true}).click();await button(names[1]).click();await button('编辑文本').click();assert.equal(await editor.inputValue(),bDraft);await editor.fill(oldDraft);
 await pick('允许根','只读目录');assert.equal(await preview.count(),0);await pick('允许根','验收目录');await button(names[1]).click();await button('编辑文本').click();assert.equal(await editor.inputValue(),bDraft);await editor.fill(oldDraft);
 await pick('节点','离线文件节点 · 离线');assert.equal(await preview.count(),0);await pick('节点','隔离文件节点');await button(names[1]).click();await button('编辑文本').click();assert.equal(await editor.inputValue(),bDraft);assert.deepEqual(await bytes(),busyBytes);
 receipt.checks.push('confirmed dirty directory/root/node transitions clear editor; reopening B initializes only B; zero additional disk writes');
 assert.deepEqual(errors,[]);receipt.after=await bytes();receipt.pass=true;
 await screenshot('green-final.png');
 console.log('draft scope real-browser PASS',receipt.checks);
}finally{
 receipt.requests=receipt.requests.map(({request_key,...data})=>data);
 await writeFile(join(cfg.evidence,'draft-scope.json'),JSON.stringify(receipt,null,2));
 await browser?.close();await server.close();
}
