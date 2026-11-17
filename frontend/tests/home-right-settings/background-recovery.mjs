import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import {chromium} from '@playwright/test';
const root=process.cwd(),port=15583,MAIN=`http://127.0.0.1:${port}`;
const out=process.env.HOME_SETTINGS_EVIDENCE;assert(out,'explicit evidence directory required');fs.mkdirSync(out,{recursive:true});
const harnessFile=path.join(root,'node_modules/.tmp/home-background-recovery-harness.mjs');
fs.mkdirSync(path.dirname(harnessFile),{recursive:true});
fs.writeFileSync(harnessFile,ts.transpileModule(fs.readFileSync(root+'/e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(harnessFile);
const server=await createServer({root,configFile:false,plugins:[vue()],cacheDir:out+'/vite',server:{host:'127.0.0.1',port,strictPort:true,proxy:{},hmr:false}});
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--short'],{encoding:'utf8'}),cases:[],failures:[]};let browser;
try{
 await server.listen();browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
 for(const width of [1440,393]){
 const context=await browser.newContext({viewport:{width,height:width===1440?1000:852},hasTouch:width===393});const page=await context.newPage();page.setDefaultTimeout(6000);
 const h=await setup(page,{background:MAIN+'/old.svg',storage:{stella_home_theme:width===1440?'nightfall':'classic'}});
 const calls=[];let mode='ok';let hold,started;
 let rows=[{id:'one',name:'合成山水',ext:'png',url:MAIN+'/one.svg',isDefault:false},{id:'two',name:'保留背景',ext:'png',url:MAIN+'/two.svg',isDefault:false}].map(e=>({...e,media:{url:e.url,status:'ready',width:1600,height:1000,thumbnail:e.url,variants:{original:e.url}}}));
 await context.route(MAIN+'/{old,one,two,new-owner}.svg',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#223b3d"/><circle cx="1150" cy="250" r="110" fill="#c4a977"/><path d="M0 900L450 260L1000 950L1600 410V1000H0" fill="#487a78"/></svg>'}));
 await context.route(MAIN+'/avatar.png',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="#7b7188"/></svg>'}));
 await context.route(MAIN+'/auth/me',async r=>{
   const method=r.request().method();calls.push(method+' /auth/me');
   if(method==='PATCH'){
     if(mode==='reject')return r.fulfill({status:403,json:{detail:'保存被拒绝（隔离夹具）'}});
     Object.assign(h.user,r.request().postDataJSON());
     if(mode==='hold'){started?.();await hold;}
     if(mode==='lost')return r.abort('connectionfailed');
   }else if(method!=='GET')throw new Error('Unexpected auth method');
   if(method==='GET'&&mode==='readfail')return r.fulfill({status:503,json:{detail:'读回失败（隔离夹具）'}});
   return r.fulfill({json:h.user});
 });
 await context.route(MAIN+'/homebg/**',async r=>{
   const method=r.request().method(),p=new URL(r.request().url()).pathname;calls.push(method+' '+p);
   if(p==='/homebg/'&&method==='GET')return r.fulfill({status:mode==='readfail'?503:200,json:mode==='readfail'?{detail:'图库读回失败（隔离夹具）'}:rows});
   if(p==='/homebg/one'&&['PATCH','DELETE'].includes(method)){
     if(mode==='reject')return r.fulfill({status:403,json:{detail:'操作被拒绝（隔离夹具）'}});
     if(method==='PATCH')Object.assign(rows.find(e=>e.id==='one'),r.request().postDataJSON());else rows=rows.filter(e=>e.id!=='one');
     if(mode==='lost')return r.abort('connectionfailed');
     return r.fulfill({json:method==='PATCH'?rows.find(e=>e.id==='one'):{ok:true}});
   }
   h.unknown.push(method+' '+p);return r.abort('blockedbyclient');
 });
 const gallery=page.locator('.bgm-mask .bgm'),crop=page.locator('.crop-wrap');
 const open=async()=>{await page.getByRole('button',{name:'主页设置',exact:true}).click();await page.getByRole('button',{name:'更换背景',exact:true}).click();await gallery.waitFor();await page.waitForFunction(()=>getComputedStyle(document.querySelector('.bgm-mask')).opacity==='1');};
 const shot=async name=>{await page.waitForFunction(()=>[...document.querySelectorAll('.bgm-mask,.preview-mask')].every(e=>getComputedStyle(e).opacity==='1'));await page.screenshot({path:`${out}/${name}-${width}.png`});};
 try{
  await page.goto(MAIN);await open();await gallery.locator('.cell').first().click();mode='reject';await gallery.getByRole('button',{name:'确定更换',exact:true}).click();
  await gallery.getByRole('alert').filter({hasText:'保存被拒绝'}).waitFor();assert(await gallery.isVisible());assert.equal(await page.evaluate(async()=>{const {auth}=await import('/src/modules/home/auth.ts');return auth.me.home_bg;}),MAIN+'/old.svg');await shot('pick-rejected');
  mode='readfail';await gallery.getByRole('button',{name:'重试保存',exact:true}).click();await gallery.getByRole('button',{name:'重试确认',exact:true}).waitFor();await page.waitForFunction(()=>![...document.querySelectorAll('button')].find(e=>e.textContent==='重试确认')?.disabled);
  assert.equal(h.user.home_bg,MAIN+'/one.svg');const patches=calls.filter(x=>x==='PATCH /auth/me').length;mode='ok';await gallery.getByRole('button',{name:'重试确认',exact:true}).click();await gallery.waitFor({state:'hidden'});assert.equal(calls.filter(x=>x==='PATCH /auth/me').length,patches);
  report.cases.push({name:`pick reject + ack/readfail/GET-only ${width}`,status:'pass'});
  // Returning to the retained drawer does not require clicking its trigger again.
  await page.getByRole('button',{name:'更换背景',exact:true}).click();await gallery.locator('.thumb').first().dblclick();await crop.waitFor();await crop.locator('input[type=range]').first().fill('180');mode='reject';await crop.getByRole('button',{name:'使用这个取景',exact:true}).click();await crop.getByRole('alert').waitFor();await shot('crop-rejected');
  await page.evaluate(()=>{const set=Storage.prototype.setItem;window.__restoreStorage=()=>Storage.prototype.setItem=set;Storage.prototype.setItem=function(k,v){if(k==='stella_home_bgcrop')throw new DOMException('quota','QuotaExceededError');return set.call(this,k,v);};});
  mode='ok';await crop.getByRole('button',{name:'重试保存',exact:true}).click();await crop.getByRole('button',{name:'重试本地保存',exact:true}).waitFor();await shot('crop-local-error');const bounds=await crop.boundingBox();assert(bounds.x>=10&&bounds.x+bounds.width<=width-10,'crop error needs viewport gutters');const cropPatches=calls.filter(x=>x==='PATCH /auth/me').length;
  await page.evaluate(()=>window.__restoreStorage());await crop.getByRole('button',{name:'重试本地保存',exact:true}).click();await crop.waitFor({state:'hidden'});assert.equal(calls.filter(x=>x==='PATCH /auth/me').length,cropPatches);assert(await page.evaluate(()=>JSON.parse(localStorage.getItem('stella_home_bgcrop')).w<1));
  report.cases.push({name:`crop rejected + quota recovery without PATCH ${width}`,status:'pass'});
  await page.getByRole('button',{name:'更换背景',exact:true}).click();await gallery.locator('[title="重命名"]').first().click();await gallery.locator('.rename-input').fill('保留的山水名称');mode='reject';await gallery.getByRole('button',{name:'保存名称',exact:true}).click();await gallery.getByRole('alert').filter({hasText:'操作被拒绝'}).waitFor();assert.equal(await gallery.locator('.rename-input').inputValue(),'保留的山水名称');await shot('rename-rejected');assert((await gallery.locator('.rename-input').boundingBox()).width>=120,'rename draft must be readable');
  mode='readfail';await gallery.getByRole('button',{name:'重试重命名',exact:true}).click();await gallery.getByRole('alert').filter({hasText:'图库读回失败'}).waitFor();const renames=calls.filter(x=>x==='PATCH /homebg/one').length;mode='ok';await gallery.getByRole('button',{name:'重试确认',exact:true}).click();await gallery.getByText('保留的山水名称',{exact:true}).waitFor();assert.equal(calls.filter(x=>x==='PATCH /homebg/one').length,renames);assert.equal(rows[0].name,'保留的山水名称');
  report.cases.push({name:`rename draft + GET-only recovery ${width}`,status:'pass'});
  await gallery.locator('[title="删除"]').first().click();const dialog=page.getByRole('dialog',{name:'删除背景',exact:true});await dialog.waitFor();await shot('delete-confirm');
  await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert(await gallery.isVisible(),'Escape closes only delete dialog');
  await gallery.locator('[title="删除"]').first().click();mode='reject';await dialog.getByRole('button',{name:'确认删除',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'操作被拒绝'}).waitFor();assert.equal(rows.length,2);await shot('delete-rejected');
  mode='lost';await dialog.getByRole('button',{name:'确认删除',exact:true}).click();await dialog.getByRole('button',{name:'重试确认',exact:true}).waitFor();assert.deepEqual(rows.map(e=>e.id),['two']);mode='readfail';await dialog.getByRole('button',{name:'重试确认',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'图库读回失败'}).waitFor();await shot('delete-read-error');const deletes=calls.filter(x=>x==='DELETE /homebg/one').length;
  mode='ok';await dialog.getByRole('button',{name:'重试确认',exact:true}).click();await dialog.waitFor({state:'hidden'});assert.equal(calls.filter(x=>x==='DELETE /homebg/one').length,deletes);assert.equal(await gallery.locator('.cell').count(),1);
  report.cases.push({name:`delete exact target + rejected/lost/GET-only recovery ${width}`,status:'pass'});
  await gallery.locator('.cell').click();let release;hold=new Promise(r=>release=r);const start=new Promise(r=>started=r);mode='hold';await gallery.getByRole('button',{name:'确定更换',exact:true}).click();await start;
  await page.evaluate(async()=>{const {auth}=await import('/src/modules/home/auth.ts');auth.me={...auth.me,id:'new-owner',home_bg:'/new-owner.svg'};});release();await page.waitForTimeout(150);assert.equal(await page.evaluate(async()=>{const {auth}=await import('/src/modules/home/auth.ts');return auth.me.id;}),'new-owner');
  report.cases.push({name:`late background completion fenced ${width}`,status:'pass'});
 }catch(e){report.failures.push({name:`CRUD ${width}`,error:e.stack});await shot('failure');}
 report.cases.push({width,calls,stored:{user:h.user,rows},unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors});
 const unexpectedConsole=h.consoleErrors.filter(x=>!['Failed to load resource: the server responded with a status of 403 (Forbidden)','Failed to load resource: the server responded with a status of 503 (Service Unavailable)','Failed to load resource: net::ERR_CONNECTION_FAILED'].includes(x));
 if(h.unknown.length||h.errors.length||unexpectedConsole.length)report.failures.push({name:`diagnostics ${width}`,unknown:h.unknown,errors:h.errors,unexpectedConsole});await context.close();
 }
}finally{await browser?.close();await server.close();fs.rmSync(harnessFile,{force:true});fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));if(report.failures.length)process.exitCode=1;
