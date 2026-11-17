// Actual production build, offline API fixtures, no source injection.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import ts from 'typescript';
import {chromium} from '@playwright/test';
const root=process.cwd(), dist=path.resolve(process.env.HOME_REVIEW_DIST||'/root/.hermes/cache/scratch/review-home-dist');
const out=process.env.HOME_SETTINGS_EVIDENCE;
assert(out,'HOME_SETTINGS_EVIDENCE is required');fs.mkdirSync(out,{recursive:true});
const port=15573, MAIN=`http://127.0.0.1:${port}`;
const harnessFile=path.join(root,'node_modules/.tmp/review-home-build-harness.mjs');fs.mkdirSync(path.dirname(harnessFile),{recursive:true});
fs.writeFileSync(harnessFile,ts.transpileModule(fs.readFileSync(root+'/e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(harnessFile);
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sourceFiles=['src/App.vue','src/modules/home/HomePage.vue','src/modules/home/settings.ts','src/shell/SettingsPanel.vue','src/style.css','tests/home-right-settings/review-build.mjs','e2e/experience-independent-harness.ts'];
const hashes=()=>Object.fromEntries(sourceFiles.map(file=>[file,hash(path.join(root,file))]));
const assets=()=>Object.fromEntries(fs.readdirSync(dist+'/static').filter(f=>/\.(js|css)$/.test(f)).map(f=>[f,hash(dist+'/static/'+f)]));
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--short'],{encoding:'utf8'}),dist,sourceBefore:hashes(),assetsBefore:assets(),cases:[],failures:[]};
const mime={'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'};
const server=http.createServer((req,res)=>{
 const pathname=decodeURIComponent(new URL(req.url,MAIN).pathname);
 const file=path.resolve(dist,'.'+(path.extname(pathname)?pathname:'/index.html'));
 if(!file.startsWith(dist+'/')||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
await new Promise(resolve=>server.listen(port,'127.0.0.1',resolve));
let browser;
async function typography(page){
 const contrast=await page.locator('aside.panel').evaluate(panel=>{
  const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');
  const rgba=c=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=c;ctx.fillRect(0,0,1,1);const v=[...ctx.getImageData(0,0,1,1).data];return [v[0],v[1],v[2],v[3]/255];};
  const over=(fg,bg)=>fg.slice(0,3).map((c,i)=>c*fg[3]+bg[i]*(1-fg[3]));
  const lum=c=>c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  return [...panel.querySelectorAll('*')].filter(el=>(el.tagName==='INPUT'||[...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))&&el.getClientRects().length).flatMap(el=>{
   const chain=[];for(let n=el;n;n=n.parentElement)chain.unshift(n);
   let bg=[0,0,0];const opacity=[];
   for(const n of chain){const s=getComputedStyle(n);bg=over(rgba(s.backgroundColor),bg);opacity.push({tag:n.className||n.tagName,value:Number(s.opacity)});}
   const styles=[{style:getComputedStyle(el),text:el.value||el.textContent.trim(),pseudo:''}];
   if(el.tagName==='INPUT'&&el.placeholder)styles.push({style:getComputedStyle(el,'::placeholder'),text:el.placeholder,pseudo:'::placeholder'});
   return styles.map(({style:s,text,pseudo})=>{const color=rgba(s.color);color[3]*=pseudo?Number(s.opacity):1;const fg=over(color,bg),a=lum(fg),b=lum(bg);return {text,selector:el.className+pseudo,color:s.color,background:bg,foreground:fg,opacity,contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),font:s.fontFamily,size:s.fontSize};});
  });
 });
 const cdp=await page.context().newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
 const doc=await cdp.send('DOM.getDocument');const fonts={};
 for(const selector of ['.p-title','.t-desc','.f-label','.dd-label']){
  const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:doc.root.nodeId,selector});
  fonts[selector]=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId})).fonts;
 }
 await cdp.detach();return {contrast,fonts};
}
try{
 browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
 for(const viewport of [{width:1440,height:1000},{width:393,height:852},{width:320,height:568},{width:852,height:393}]){
  const context=await browser.newContext({viewport});const page=await context.newPage();page.setDefaultTimeout(6000);
  const h=await setup(page,{background:MAIN+'/qa-pattern.svg',storage:{stella_home_theme:'nightfall'}});
  const receipt={viewport,checks:[],unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors,requests:[],failed:[]};report.cases.push(receipt);
  page.on('request',r=>receipt.requests.push({url:r.url(),method:r.method()}));page.on('requestfailed',r=>receipt.failed.push(r.url()));
  const route=(pathname,handler)=>context.route(u=>u.origin===MAIN&&u.pathname===pathname,handler);
  await context.route(u=>u.origin===MAIN&&u.pathname.startsWith('/static/'),r=>r.request().method()==='GET'?r.continue():r.abort());
  const image='<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#29272c"/></svg>';
  for(const p of ['/qa-pattern.svg','/avatar.png','/assets/homebg/default-bg-kimono-1920.webp'])await route(p,r=>r.fulfill({contentType:'image/svg+xml',body:image}));
  await route('/homebg/media',r=>r.fulfill({json:{url:MAIN+'/qa-pattern.svg',status:'ready',variants:{},error:null}}));
  await route('/homebg/',r=>r.fulfill({json:[{id:'qa-bg',name:'离线背景',ext:'.jpg',url:MAIN+'/qa-pattern.svg',isDefault:true,media:{url:MAIN+'/qa-pattern.svg',status:'ready',thumbnail:MAIN+'/qa-pattern.svg',variants:{original:MAIN+'/qa-pattern.svg'}}}]}));
  try{
   await page.clock.install();await page.goto(MAIN);
   const trigger=page.getByRole('button',{name:'主页设置',exact:true}),dialog=page.getByRole('dialog',{name:'主页设置',exact:true});
   await trigger.waitFor();await page.clock.runFor(500);await trigger.click();await dialog.waitFor();await page.clock.runFor(500);
   assert.equal(new URL(page.url()).pathname,'/');
   assert(await page.locator('.shell').evaluate(el=>el.inert&&el.getAttribute('aria-hidden')==='true'));
   assert(await dialog.evaluate(el=>!el.closest('[inert]')&&el.parentElement.parentElement===document.body));
   await page.locator('.home-settings-trigger').evaluate(el=>el.focus());assert(await dialog.evaluate(el=>el.contains(document.activeElement)),'Inert shell cannot take focus');
   await page.getByLabel('大标题',{exact:true}).fill('真实构建主页');
   assert.equal(await page.evaluate(()=>localStorage.getItem('stella_site_title')),'真实构建主页');
   await page.screenshot({path:out+`/drawer-${viewport.width}.png`});
   receipt.typography=await typography(page);
   // Record all evidence before failing, including actual Chromium font usage.
   for(const row of receipt.typography.contrast){
    assert(row.opacity.every(x=>x.value===1),`Composite opacity requires explicit review: ${row.text}`);
    assert(row.contrast>=4.5,`Text contrast ${row.contrast}: ${row.text}`);
   }
   assert(receipt.typography.fonts['.p-title'].some(f=>/WenQuanYi|文泉驿/i.test(f.familyName)),'Chinese drawer title should use installed sans fallback, not AR PL Sungti');
   await page.getByLabel('大标题',{exact:true}).fill('');await page.getByLabel('签名',{exact:true}).fill('');
   await page.screenshot({path:out+`/placeholder-${viewport.width}.png`});
   await page.getByLabel('大标题',{exact:true}).fill('真实构建主页');await page.getByLabel('签名',{exact:true}).fill('夜有星辰，晨有曦光。');
   await dialog.getByRole('button',{name:'压缩1',exact:true}).click();await page.waitForFunction(()=>{const el=document.querySelector('aside.panel .dd-menu');return el&&getComputedStyle(el).opacity==='1';});
   receipt.expandedTypography=await typography(page);
   for(const row of receipt.expandedTypography.contrast){assert(row.opacity.every(x=>x.value===1));assert(row.contrast>=4.5,`Expanded/placeholder contrast ${row.contrast}: ${row.text}`);}
   await dialog.getByRole('button',{name:'原画',exact:true}).click();
   receipt.checks.push('actual build: inert shell, interactive Teleport, persistence, composite contrast, rendered fonts');
   await page.evaluate(()=>{const original=Storage.prototype.setItem;window.__restoreStorage=()=>Storage.prototype.setItem=original;Storage.prototype.setItem=function(k,v){if(k==='stella_signature')throw new DOMException('quota','QuotaExceededError');return original.call(this,k,v);};});
   const signature=page.getByLabel('签名',{exact:true});await signature.fill('失败字段保留焦点');
   await dialog.getByRole('alert').filter({hasText:'签名'}).waitFor();assert(await signature.evaluate(el=>el===document.activeElement));
   await page.getByLabel('大标题',{exact:true}).fill('另一字段独立成功');assert(await dialog.getByRole('alert').filter({hasText:'签名'}).isVisible());
   await page.evaluate(()=>window.__restoreStorage());await dialog.getByRole('button',{name:'重试本地保存'}).click();
   assert.equal(await page.evaluate(()=>localStorage.getItem('stella_signature')),'失败字段保留焦点');
   await page.evaluate(()=>{const original=Storage.prototype.setItem;window.__restoreStorage=()=>Storage.prototype.setItem=original;Storage.prototype.setItem=function(k,v){if(k==='stella_signature')return;return original.call(this,k,v);};});
   await signature.fill('读回不一致的输入');await dialog.getByRole('alert').filter({hasText:'签名'}).waitFor();assert(await signature.evaluate(el=>el===document.activeElement));
   assert.equal(await page.evaluate(()=>localStorage.getItem('stella_signature')),'失败字段保留焦点');
   await page.evaluate(()=>window.__restoreStorage());await dialog.getByRole('button',{name:'重试本地保存'}).click();assert.equal(await page.evaluate(()=>localStorage.getItem('stella_signature')),'读回不一致的输入');
   receipt.checks.push('field error isolation, retained focus, and silent readback mismatch');
   let resetMode='read-failure';const resetCalls=[];
   await route('/auth/me',r=>{const method=r.request().method();resetCalls.push(method);if(method==='PATCH')return r.fulfill({json:{...h.user,home_bg:'/assets/homebg/default-bg-kimono-1920.webp'}});if(resetMode==='read-failure')return r.fulfill({status:503,json:{detail:'offline fixture'}});return r.fulfill({json:{...h.user,id:resetMode==='wrong-owner'?'other':h.user.id,home_bg:'/assets/homebg/default-bg-kimono-1920.webp'}});});
   await dialog.getByRole('button',{name:'恢复默认',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'恢复默认未确认'}).waitFor();
   assert.equal(await dialog.locator('.bg-name').textContent(),'离线背景');assert.deepEqual(resetCalls,['PATCH','GET']);
   resetMode='wrong-owner';await dialog.getByRole('button',{name:'重试恢复默认'}).click();await dialog.getByRole('alert').filter({hasText:'读回不一致'}).waitFor();assert.equal(await dialog.locator('.bg-name').textContent(),'离线背景');
   resetMode='ok';await dialog.getByRole('button',{name:'重试恢复默认'}).click();await dialog.getByText('账号背景已保存',{exact:true}).waitFor();
   assert.equal(await dialog.locator('.bg-name').textContent(),'default-bg-kimono-1920');
   assert.equal(await dialog.locator('.bg-preview img').getAttribute('src'),'/assets/homebg/default-bg-kimono-1920.webp');
   receipt.checks.push('PATCH then failed GET / wrong owner never update; confirmed GET does');
   await dialog.getByRole('button',{name:'更换背景',exact:true}).scrollIntoViewIfNeeded();await page.clock.runFor(500);
   const close=await page.getByRole('button',{name:'关闭主页设置'}).boundingBox();assert(close.y>=0&&close.y+close.height<=viewport.height);
   assert(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth));await page.screenshot({path:out+`/drawer-bottom-${viewport.width}.png`});
   await dialog.getByRole('button',{name:'更换背景',exact:true}).click();await page.locator('.bgm .thumb').dblclick();await page.locator('.crop-wrap').waitFor();
   await page.keyboard.press('Tab');assert(await page.locator('.crop-wrap').evaluate(el=>el.contains(document.activeElement)));
   await page.keyboard.press('Escape');await page.locator('.crop-wrap').waitFor({state:'hidden'});assert(await page.locator('.bgm').evaluate(el=>el.contains(document.activeElement)));
   await page.keyboard.press('Escape');await dialog.waitFor();await page.keyboard.press('Escape');assert(await trigger.evaluate(el=>el===document.activeElement));
   assert(await page.locator('.shell').evaluate(el=>!el.inert));receipt.checks.push('nested gallery/crop focus and all Escape levels');
   await trigger.click();await dialog.waitFor();
   if(viewport.width>440)await page.mouse.click(10,50);else await page.getByRole('button',{name:'关闭主页设置'}).click();
   await dialog.waitFor({state:'hidden'});assert(await trigger.evaluate(el=>el===document.activeElement));receipt.checks.push('pointer close restores focus and shell access');
   // Real router exposed by Vue, no source imports or replacement components.
   const navigate=to=>page.evaluate(to=>document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(to),to);
   await navigate('/settings?section=navigation&module=home');await page.getByRole('button',{name:'到主页调整外观'}).waitFor();
   assert.equal(await page.locator('.theme-row').count(),0);await page.getByRole('button',{name:'到主页调整外观'}).click();await dialog.waitFor();
   assert.equal(await dialog.count(),1);
   for(const endpoint of ['/workspaces/','/documents/','/documents/recent','/documents/favorites','/tags/','/doc-tags/'])await route(endpoint,r=>r.request().method()==='GET'?r.fulfill({json:endpoint==='/workspaces/'?[{id:'qa-home-ws',name:'隔离笔记',user_id:h.user.id}]:[]}):r.abort());
   await context.routeWebSocket(MAIN.replace('http:','ws:')+'/ws/list/qa-home-ws',ws=>ws.onMessage(()=>{}));
   await dialog.getByRole('button',{name:'更换背景',exact:true}).click();await page.locator('.bgm .thumb').dblclick();await page.locator('.crop-wrap').waitFor();
   await navigate('/notes');await page.locator('.notes-page').waitFor();assert.equal(await dialog.count(),0);assert.equal(await page.locator('.bgm,.preview-mask').count(),0);
   await navigate('/');await trigger.click();await dialog.waitFor();await page.keyboard.press('Escape');assert(await trigger.evaluate(el=>el===document.activeElement));
   receipt.checks.push('SettingsPage compatibility and Notes KeepAlive integration');
   await trigger.click();await dialog.getByRole('button',{name:'更换背景',exact:true}).click();await page.locator('.bgm .thumb').dblclick();await page.locator('.crop-wrap').waitFor();
   await route('/auth/me',r=>r.fulfill({status:401,json:{detail:'expired fixture'}}));await route('/auth/refresh',r=>r.fulfill({status:401,json:{detail:'expired fixture'}}));
   await page.clock.fastForward(30000);await page.getByRole('dialog',{name:'Stella 登录'}).waitFor();
   assert.equal(await page.locator('.bgm,.preview-mask,aside.panel').count(),0);receipt.checks.push('real watchdog 401+refresh rejection removes every overlay');
  }catch(e){report.failures.push({viewport,error:e.stack});await page.screenshot({path:out+`/failed-${viewport.width}.png`});}
  const expectedConsole=/Failed to load resource: the server responded with a status of (503|401)/;
  if(h.unknown.length||h.errors.length||h.consoleErrors.some(x=>!expectedConsole.test(x))||receipt.failed.length)report.failures.push({viewport,diagnostics:{unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors,failed:receipt.failed}});
  assert(!receipt.requests.some(r=>new URL(r.url).pathname.startsWith('/src/')),'Must not load source instead of built chunks');
  await context.close();
 }
}finally{
 await browser?.close();await new Promise(resolve=>server.close(resolve));report.sourceAfter=hashes();report.assetsAfter=assets();assert.deepEqual(report.sourceBefore,report.sourceAfter);assert.deepEqual(report.assetsBefore,report.assetsAfter);fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));
}
console.log(JSON.stringify({cases:report.cases.map(c=>({viewport:c.viewport,checks:c.checks})),failures:report.failures},null,2));if(report.failures.length)process.exitCode=1;
