// Actual component + auth store + unmocked API -> loopback FastAPI -> owned PG.
// No resident service or configured proxy. Invoked only by owned-PG pytest.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createServer} from '../../../node_modules/vite/dist/node/index.js';
import vue from '../../../node_modules/@vitejs/plugin-vue/dist/index.mjs';
import {chromium} from '../../../node_modules/playwright/index.mjs';
const root=new URL('../../../',import.meta.url).pathname;
const backend=process.env.STELLA_IDENTITY_HTTP,out=process.env.STELLA_IDENTITY_OUT;
assert(backend&&/^http:\/\/127\.0\.0\.1:\d+$/.test(backend));assert(out&&path.isAbsolute(out));fs.mkdirSync(out,{recursive:true});
const cache=fs.mkdtempSync(path.join(os.tmpdir(),'identity-browser-'));
const server=await createServer({root,configFile:false,envDir:false,appType:'custom',cacheDir:cache,plugins:[vue(),{name:'owned-identity-fixture',configureServer(s){s.middlewares.use(async(req,res,next)=>{if(req.url!=='/')return next();res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await s.transformIndexHtml('/',`<!doctype html><html><head><meta charset="utf-8"></head><body><div id="app"></div><script type="module">
import {createApp,h,ref} from 'vue';
import Component from '/src/modules/servers/MonitorGroupDelete.vue';
import {auth} from '/src/modules/home/auth.ts';
auth.me={id:'owned-fixture',username:'fixture'};window.receipts=[];
const open=ref(true);createApp({render:()=>h(Component,{groupId:1,open:open.value,onClose:()=>{open.value=false},onDeleted:()=>{window.receipts.push('confirmed-original-and-children-absent');open.value=false}})}).mount('#app');
</script></body></html>`));});}}],optimizeDeps:{entries:[],include:['vue']},server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{'/monitors':{target:backend},'/_fixture':{target:backend}}}});
await server.listen();const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'real Chromium -> actual component/API -> real loopback HTTP -> owned PostgreSQL; auth dependencies fixture-only',checks:[],requests:[],errors:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 for(const mode of ['empty-replaced','members-replaced','same-uuid','lost-ack-replaced','lost-ack-partial']){
  const reset=await fetch(backend+'/_fixture/reset?mode='+mode,{method:'POST'});assert.equal(reset.status,200);const before=await reset.json();
  const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(15000);page.on('pageerror',e=>result.errors.push(e.message));
  const calls=[];page.on('request',req=>{if(new URL(req.url()).pathname.startsWith('/monitors/'))calls.push({method:req.method(),url:req.url(),body:req.postData()});});
  let lost=false;
  await page.route('**/monitors/groups/1/delete',async route=>{if(mode.startsWith('lost-ack')){const response=await route.fetch();assert.equal(response.status(),204);lost=true;await fetch(backend+'/_fixture/replace',{method:'POST'});return route.abort('connectionreset');}return route.continue();});
  await page.goto(origin);const dialog=page.getByRole('dialog',{name:'确认删除监控组'});await dialog.getByRole('button',{name:'确认删除整组',exact:true}).waitFor();
  if(mode.endsWith('replaced')&&!mode.startsWith('lost'))await fetch(backend+'/_fixture/replace',{method:'POST'});
  await dialog.getByRole('button',{name:'确认删除整组',exact:true}).click();
  if(mode==='empty-replaced'||mode==='members-replaced'){
   await dialog.getByRole('alert').filter({hasText:'身份或成员范围已变化'}).waitFor();assert.equal(await dialog.getByRole('button',{name:'确认删除整组',exact:true}).count(),0);
   const after=await (await fetch(backend+'/_fixture/state')).json();assert.equal(after.group_uuid,after.replacement_uuid);assert.equal(after.version,before.version);assert.deepEqual(after.ids,before.ids);
  }else if(mode==='same-uuid')await page.waitForFunction(()=>window.receipts.length===1);
  else{
   await dialog.getByRole('alert').filter({hasText:'删除尚未确认'}).waitFor();assert(lost);assert.equal(await page.evaluate(()=>window.receipts.length),0);
   await dialog.getByRole('button',{name:'重新读取确认',exact:true}).click();
   if(mode==='lost-ack-partial'){
    await dialog.getByRole('alert').filter({hasText:'确认成员'}).waitFor();assert.equal(await page.evaluate(()=>window.receipts.length),0);const after=await(await fetch(backend+'/_fixture/state')).json();assert.equal(after.ids.length,1);
   }else await page.waitForFunction(()=>window.receipts.length===1);
   const after=await(await fetch(backend+'/_fixture/state')).json();assert(after.group_uuid&&after.group_uuid!==before.uuid);
   const reads=calls.filter(c=>c.method==='GET'&&new URL(c.url).searchParams.has('expected_stable_uuid'));assert(reads.length>0);for(const read of reads)assert.equal(new URL(read.url).searchParams.get('expected_stable_uuid'),before.uuid);
  }
  const posts=calls.filter(c=>c.method==='POST');assert.equal(posts.length,1);assert.deepEqual(JSON.parse(posts[0].body),{expected_child_ids:before.ids,expected_stable_uuid:before.uuid});
  await page.screenshot({path:path.join(out,mode+'.png')});result.requests.push({mode,calls});result.checks.push(mode);await context.close();
 }
 assert.deepEqual(result.errors,[]);result.passed=true;
}finally{fs.writeFileSync(path.join(out,'real-browser.json'),JSON.stringify(result,null,2));await browser?.close();await server.close();fs.rmSync(cache,{recursive:true,force:true});}
