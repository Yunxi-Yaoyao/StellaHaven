import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import {chromium} from '@playwright/test';
const root=process.cwd(),port=15593,MAIN=`http://127.0.0.1:${port}`;
const out=process.env.HOME_SETTINGS_EVIDENCE;assert(out,'explicit evidence directory required');fs.mkdirSync(out,{recursive:true});
const sourceFiles=['src/modules/home/BgManager.vue','src/modules/home/backgroundMedia.ts','src/shell/SettingsPanel.vue','src/App.vue','src/modules/home/settings.ts','tests/home-right-settings/background-review.mjs','e2e/experience-independent-harness.ts'];
const hashes=()=>Object.fromEntries(sourceFiles.map(f=>[f,createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex')]));
const sourceBefore=hashes();
const harnessFile=path.join(root,'node_modules/.tmp/background-review-harness.mjs');
fs.mkdirSync(path.dirname(harnessFile),{recursive:true});
fs.writeFileSync(harnessFile,ts.transpileModule(fs.readFileSync(root+'/e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(harnessFile);
const server=await createServer({root,configFile:false,envDir:'/root/.hermes/cache/scratch/background-review-fix/empty-env',plugins:[vue()],cacheDir:out+'/vite',server:{host:'127.0.0.1',port,strictPort:true,proxy:{},hmr:false}});
const report={commit:execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),dirty:execFileSync('git',['-C',root,'status','--short'],{encoding:'utf8'}),sourceBefore,cases:[],failures:[]};let browser;
try{
 await server.listen();browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
 for(const width of [1440,393]){
 const context=await browser.newContext({viewport:{width,height:width===1440?1000:852},hasTouch:width===393});const page=await context.newPage();page.setDefaultTimeout(6000);
 const h=await setup(page,{background:MAIN+'/old.svg',storage:{stella_home_theme:width===1440?'nightfall':'classic'}});
 const calls=[];let mode='ok';let hold,started;let listHold=false,listStarted,listRelease;let uploadId='uploaded';
 let rows=[{id:'one',name:'合成山水',ext:'png',url:MAIN+'/one.svg',isDefault:false},{id:'two',name:'保留背景',ext:'png',url:MAIN+'/two.svg',isDefault:false}].map(e=>({...e,media:{url:e.url,status:'ready',width:1600,height:1000,thumbnail:e.url,variants:{original:e.url}}}));
 await context.route(MAIN+'/{old,one,two,new-owner,uploaded-shared,uploaded-local}.svg',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#223b3d"/><circle cx="1150" cy="250" r="110" fill="#c4a977"/><path d="M0 900L450 260L1000 950L1600 410V1000H0" fill="#487a78"/></svg>'}));
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
   if(p==='/homebg/'&&method==='GET'){
     const snapshot=structuredClone(rows);
     if(listHold){listHold=false;listStarted?.();await new Promise(resolve=>listRelease=resolve);return r.fulfill({json:snapshot});}
     return r.fulfill({status:mode==='readfail'?503:200,json:mode==='readfail'?{detail:'图库读回失败（隔离夹具）'}:rows});
   }
   if(p==='/homebg/upload'&&method==='POST'){
     const url=MAIN+'/'+uploadId+'.svg';const item={id:uploadId,name:uploadId,ext:'png',url,isDefault:false,media:{url,status:'ready',width:1600,height:1000,thumbnail:url,variants:{original:url}}};rows.push(item);
     if(mode==='hold-upload'){started?.();await hold;}
     return r.fulfill({json:item});
   }
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
 await context.route(MAIN+'/assets/homebg/default-bg-kimono-1920.webp',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#223b3d"/></svg>'}));
 await context.route(MAIN+'/homebg/media?**',r=>{const url=new URL(r.request().url()).searchParams.get('url');return r.fulfill({json:{url,status:'ready',variants:{original:url}}});});
 try{
  await page.goto(MAIN);await open();await gallery.locator('.cell').first().click();mode='readfail';await gallery.getByRole('button',{name:'确定更换',exact:true}).click();
  await page.waitForFunction(()=>!![...document.querySelectorAll('button')].find(e=>e.textContent==='重试确认'&&!e.disabled));
  assert.equal(h.user.home_bg,MAIN+'/one.svg');
  await gallery.locator('.x').click();await gallery.waitFor({state:'hidden'});mode='ok';
  await page.getByRole('button',{name:'恢复默认',exact:true}).click();
  await page.waitForFunction(async()=>{const {auth}=await import('/src/modules/home/auth.ts');return auth.me.home_bg==='/assets/homebg/default-bg-kimono-1920.webp';});
  await page.getByRole('button',{name:'更换背景',exact:true}).click();await gallery.waitFor();
  const writesBefore=calls.filter(x=>x==='PATCH /auth/me').length;
  for(let i=0;i<2;i++){await gallery.getByRole('button',{name:'重试确认',exact:true}).click();await gallery.getByRole('alert').filter({hasText:'背景尚未确认'}).waitFor();}
  const buttons=await gallery.locator('button').evaluateAll(bs=>bs.map(b=>({text:b.textContent.trim(),disabled:b.disabled})));
  assert(await gallery.getByRole('button',{name:'确定更换',exact:true}).isDisabled());assert.equal(await gallery.getByRole('button',{name:'继续修改',exact:true}).count(),0);
  assert.equal(calls.filter(x=>x==='PATCH /auth/me').length,writesBefore);
  await shot('mismatch-before-exit');
  await gallery.getByRole('button',{name:'采用服务器当前值',exact:true}).click();
  assert.equal(calls.filter(x=>x==='PATCH /auth/me').length,writesBefore);
  assert(await gallery.locator('[title="重命名"]').first().isEnabled());
  assert(await gallery.locator('[title="删除"]').first().isEnabled());
  await shot('mismatch-recovered');
  report.cases.push({name:`R1 same-tab default reset explicit recovery ${width}`,status:'pass',buttons,writesBefore,calls:[...calls]});
  // Same acknowledged mismatch in rename; only an explicit adoption ends the old operation.
  await gallery.locator('[title="重命名"]').first().click();await gallery.locator('.rename-input').fill('旧名称意图');mode='readfail';
  await gallery.getByRole('button',{name:'保存名称',exact:true}).click();await gallery.getByRole('alert').filter({hasText:'图库读回失败'}).waitFor();
  assert.equal(await gallery.getByRole('button',{name:'采用服务器当前值',exact:true}).count(),0);
  rows[0].name='另一设备名称';mode='ok';await gallery.getByRole('button',{name:'重试确认',exact:true}).click();
  await gallery.getByRole('button',{name:'采用服务器当前值',exact:true}).waitFor();
  assert.equal(await gallery.locator('.rename-input').inputValue(),'旧名称意图');await shot('rename-mismatch');
  const renameWrites=calls.filter(x=>x==='PATCH /homebg/one').length;
  await gallery.getByRole('button',{name:'采用服务器当前值',exact:true}).click();
  await gallery.getByText('另一设备名称',{exact:true}).waitFor();assert.equal(calls.filter(x=>x==='PATCH /homebg/one').length,renameWrites);
  await gallery.locator('[title="重命名"]').first().click();await gallery.locator('.rename-input').fill('主动新名称');
  await gallery.getByRole('button',{name:'保存名称',exact:true}).click();await gallery.getByText('主动新名称',{exact:true}).waitFor();assert.equal(rows[0].name,'主动新名称');
  await gallery.locator('[title="删除"]').first().click();await page.getByRole('dialog',{name:'删除背景',exact:true}).getByRole('button',{name:'确认删除',exact:true}).click();
  await page.getByRole('dialog',{name:'删除背景',exact:true}).waitFor({state:'hidden'});assert.deepEqual(rows.map(e=>e.id),['two']);
  report.cases.push({name:`R1 rename mismatch exit + new rename/delete ${width}`,status:'pass'});
  const channels=process.env.UPLOAD_CHANNEL?[process.env.UPLOAD_CHANNEL]:['shared','local'];
  assert(channels.every(c=>['shared','local'].includes(c)));
  for(const channel of channels){
   uploadId='uploaded-'+channel;const began=new Promise(resolve=>listStarted=resolve);
   if(channel==='shared'){
    listHold=true;await page.evaluate(()=>{void import('/src/modules/home/backgroundMedia.ts').then(m=>{window.__oldList=m.loadBackgroundEntries();});});
   }else {
    await gallery.locator('.x').click();await gallery.waitFor({state:'hidden'});
    // The drawer also loads the shared catalog on return. Drain that read first,
    // then hold only BgManager's own reopen load (not the drawer's request).
    await page.evaluate(async()=>{const m=await import('/src/modules/home/backgroundMedia.ts');await m.loadBackgroundEntries();});
    listHold=true;await page.getByRole('button',{name:'更换背景',exact:true}).click();await gallery.waitFor();
   }
   await began;
   await gallery.locator('input[type=file]').setInputFiles({name:uploadId+'.png',mimeType:'image/png',buffer:Buffer.from('isolated synthetic upload')});
   await gallery.getByText(uploadId,{exact:true}).waitFor();assert(rows.some(e=>e.id===uploadId));
   listRelease();if(channel==='shared')await page.evaluate(()=>window.__oldList);await page.waitForTimeout(150);
   assert.equal(await gallery.getByText(uploadId,{exact:true}).count(),1,'acknowledged upload must survive old '+channel+' GET');
   assert.deepEqual(await page.evaluate(async()=>{const m=await import('/src/modules/home/backgroundMedia.ts');return m.backgroundEntries.value.map(e=>e.id);}),rows.map(e=>e.id));
   await shot('upload-'+channel+'-preserved');
   await gallery.getByRole('button',{name:'确定更换',exact:true}).click();await gallery.waitFor({state:'hidden'});assert.equal(h.user.home_bg,MAIN+'/'+uploadId+'.svg');
   await page.getByRole('button',{name:'更换背景',exact:true}).click();await gallery.waitFor();
   report.cases.push({name:`R2 ${channel} stale list + upload/apply ${width}`,status:'pass'});
  }
  assert.equal(calls.filter(x=>x==='POST /homebg/upload').length,channels.length);
  // An acknowledged but delayed upload receipt must not expose the old owner's catalog.
  uploadId='OWNER_A_PRIVATE_UPLOAD';mode='hold-upload';let releaseUpload;
  hold=new Promise(resolve=>releaseUpload=resolve);const uploadStarted=new Promise(resolve=>started=resolve);
  await gallery.locator('input[type=file]').setInputFiles({name:'owner-a.png',mimeType:'image/png',buffer:Buffer.from('synthetic owner A marker, not a real secret')});await uploadStarted;
  Object.assign(h.user,{id:'owner-b',home_bg:MAIN+'/new-owner.svg'});
  rows=[{id:'b',name:'Owner B only',url:MAIN+'/new-owner.svg',ext:'png',isDefault:false}];
  await page.evaluate(async user=>{const {acceptLogin}=await import('/src/modules/home/auth.ts');acceptLogin(user);},h.user);
  const uploadResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/homebg/upload');releaseUpload();await uploadResponse;mode='ok';
  await page.waitForTimeout(150);
  if(await gallery.isVisible()){await gallery.locator('.x').click();await gallery.waitFor({state:'hidden'});}
  if(await page.getByRole('button',{name:'更换背景',exact:true}).isVisible())await page.getByRole('button',{name:'更换背景',exact:true}).click();else await open();
  await gallery.getByText('Owner B only',{exact:true}).waitFor();
  const isolation=await page.evaluate(async()=>{const {auth}=await import('/src/modules/home/auth.ts');const {backgroundEntries}=await import('/src/modules/home/backgroundMedia.ts');return {owner:auth.me.id,ids:backgroundEntries.value.map(e=>e.id),text:document.body.innerText,storage:JSON.stringify(localStorage)};});
  assert.equal(isolation.owner,'owner-b');assert.deepEqual(isolation.ids,['b']);assert(!isolation.text.includes('OWNER_A_PRIVATE'));assert(!isolation.storage.includes('OWNER_A_PRIVATE'));
  assert.equal(await gallery.getByRole('button',{name:'采用服务器当前值',exact:true}).count(),0);
  await shot('late-upload-owner-fenced');report.cases.push({name:`R2 late upload owner/session fenced; no old marker in DOM/storage ${width}`,status:'pass',owner:isolation.owner,ids:isolation.ids});

 }catch(e){report.failures.push({name:`CRUD ${width}`,error:e.stack});await shot('failure');}
 report.cases.push({width,calls,stored:{user:h.user,rows},unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors});
 const unexpectedConsole=h.consoleErrors.filter(x=>!['Failed to load resource: the server responded with a status of 403 (Forbidden)','Failed to load resource: the server responded with a status of 503 (Service Unavailable)','Failed to load resource: net::ERR_CONNECTION_FAILED'].includes(x));
 if(h.unknown.length||h.errors.length||unexpectedConsole.length)report.failures.push({name:`diagnostics ${width}`,unknown:h.unknown,errors:h.errors,unexpectedConsole});await context.close();
 }
}finally{await browser?.close();await server.close();fs.rmSync(harnessFile,{force:true});report.sourceAfter=hashes();assert.deepEqual(report.sourceAfter,sourceBefore);fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));if(report.failures.length)process.exitCode=1;
