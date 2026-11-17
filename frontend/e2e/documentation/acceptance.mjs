// One sequential browser, built UI and loopback-only mocked guest endpoints.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const out=process.env.STELLA_DOC_OUTPUT;
if(!out)throw Error('STELLA_DOC_OUTPUT required');
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.STELLA_CHROMIUM||process.env.CHROME_BIN||chromium.executablePath(),args:['--no-sandbox']});
const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write'],serviceWorkers:'block'});
const page=await context.newPage(),steps=[],errors=[],requests=[];
page.on('pageerror',error=>errors.push(error.stack));context.on('page',p=>p.on('pageerror',error=>errors.push(error.stack)));
await context.route('**/*',route=>{
 const u=new URL(route.request().url());
 if(u.origin!=='http://127.0.0.1:15591'&&!['data:','blob:'].includes(u.protocol))return route.abort();
 if(!['GET','HEAD'].includes(route.request().method()))requests.push({method:route.request().method(),path:u.pathname});
 return route.continue();
});
const step=async(name,run)=>{await run();steps.push({name,status:'passed'});fs.writeFileSync(path.join(out,'browser-progress.json'),JSON.stringify({steps,errors,requests},null,2));};
const shot=async name=>{await page.screenshot({path:path.join(out,name+'.png'),animations:'disabled'});};
try{
 if(process.env.STELLA_DOC_CAPTURE==='1')await step('capture actual frozen components in simulated viewport',async()=>{
  await page.goto('http://127.0.0.1:15591/__doc-fixture');await page.locator('.appearance-settings').waitFor();await page.evaluate(()=>document.fonts.ready);assert.equal(await page.locator('.appearance-settings').evaluate(el=>getComputedStyle(el).padding),'20px');
  await page.locator('main').screenshot({path:'src/modules/documentation/images/appearance-test.png'});
  await page.goto('http://127.0.0.1:15591/__doc-fixture/website');await page.locator('.inline-editor').waitFor();await page.locator('.auth-options > summary').click();await page.locator('main').screenshot({path:'src/modules/documentation/images/website-test.png'});
  await page.goto('http://127.0.0.1:15591/__doc-fixture/sso');await page.locator('.provider-card').waitFor();await page.locator('main').screenshot({path:'src/modules/documentation/images/sso-test.png'});
  const env={...process.env};delete env.NODE_ENV;
  const build=spawnSync(process.execPath,['node_modules/typescript/bin/tsc','--version'],{encoding:'utf8',env});assert.equal(build.status,0);
  const result=spawnSync('npm',['run','build'],{encoding:'utf8',env,timeout:180000});fs.writeFileSync(path.join(out,'browser-built-source.log'),result.stdout+result.stderr);assert.equal(result.status,0,'build after screenshot');
 });
 await step('real system navigation enters built help without private user data',async()=>{
  await page.goto('http://127.0.0.1:15591/help');await page.locator('.documentation').waitFor();
  await page.locator('.sidebar a[href="/help"]').click();assert.equal(await page.locator('.doc-reading h1').textContent(),'开始使用');
  assert.equal(await page.locator('iframe').count(),0);await shot('desktop-guide');
 });
 await step('directory search, no results, clear and guide selection',async()=>{
  await page.locator('#doc-search').fill('不可能匹配xyz-文档');await page.locator('.no-results').waitFor();await shot('search-empty');
  await page.getByRole('button',{name:'清除搜索',exact:true}).click();
  await page.getByRole('link',{name:'笔记、新建与模板目录',exact:true}).click();assert.equal(await page.locator('.doc-reading h1').textContent(),'笔记、新建与模板目录');
 });
 await step('real screenshot zoom, keyboard modal and focus return',async()=>{
  const image=page.getByRole('button',{name:'放大图片：网页项目重命名后的引用提示'});await image.scrollIntoViewIfNeeded();await image.focus();await page.keyboard.press('Enter');
  await page.locator('dialog[open]').waitFor();await page.getByRole('button',{name:'缩小图片',exact:true}).focus();await page.keyboard.press('Shift+Tab');assert.equal(await page.getByRole('button',{name:'关闭图片',exact:true}).evaluate(el=>el===document.activeElement),true);await page.keyboard.press('Tab');assert.equal(await page.getByRole('button',{name:'缩小图片',exact:true}).evaluate(el=>el===document.activeElement),true);assert.ok(await page.locator('dialog img').evaluate(i=>i.complete&&i.naturalWidth>0));
  await page.getByRole('button',{name:'放大图片',exact:true}).click();await shot('image-view');
  await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),0);assert.equal(await image.evaluate(i=>i===document.activeElement),true);
 });
 await step('chapter hash direct link, refresh and visible target',async()=>{
  await page.getByRole('navigation',{name:'本页目录'}).getByRole('link',{name:'重命名与移动',exact:true}).click();assert.ok(page.url().endsWith('#chapter-4'));
  const url=page.url();await page.reload();await page.locator('#chapter-4').waitFor();assert.equal(page.url(),url);
  const box=await page.locator('#chapter-4').boundingBox(),header=await page.locator('.doc-header').boundingBox();assert.ok(box.y>=header.y+header.height);assert.ok(box.y<900);
 });
 await step('API full operation, request parameters and actual clipboard',async()=>{
  await page.getByRole('button',{name:'API 参考',exact:true}).click();assert.equal(await page.locator('.doc-reading h1').textContent(),'认证与会话');
  await page.locator('#doc-search').fill('POST /auth/login');await page.getByRole('navigation',{name:'文章目录'}).getByRole('link',{name:'POST /auth/login',exact:true}).click();
  const expected=await page.locator('.doc-prose pre code').first().textContent();await page.getByRole('button',{name:'复制代码',exact:true}).first().click();await page.getByText('代码已复制喵~',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),expected);assert.ok(expected.includes('<REPLACE_ME>'));
  await shot('desktop-api');
 });
 await step('clipboard failure is persistent and normal text stays selectable',async()=>{
  await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>Promise.reject(Error('fixture clipboard blocked'))}});});
  await page.getByRole('button',{name:'复制代码',exact:true}).first().click();await page.getByText('复制未完成，请选中代码手动复制喵~',{exact:true}).waitFor();
  const selected=await page.locator('.doc-prose p').first().evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(range);return s.toString();});assert.ok(selected.length>0);
  await shot('copy-failed');
 });
 await step('page close/reopen preserves query and article without user preference writes',async()=>{
  const old=await page.evaluate(()=>localStorage.getItem('stella_doc_center_reading_v1'));
  await page.close();const reopened=await context.newPage();await reopened.goto('http://127.0.0.1:15591/help');await reopened.locator('.documentation').waitFor();
  assert.equal(await reopened.locator('.doc-reading h1').textContent(),'POST /auth/login');assert.equal(await reopened.locator('#doc-search').inputValue(),'POST /auth/login');assert.equal(await reopened.evaluate(()=>localStorage.getItem('stella_doc_center_reading_v1')),old);const restored=JSON.parse(old).scroll['post:/auth/login'];assert.ok(restored>0);assert.ok(Math.abs(await reopened.locator('.doc-reading').evaluate(el=>el.scrollTop)-restored)<2);
  await reopened.close();
 });
 // Continue on a fresh page in the SAME browser/context. Reassign through holder.
 const mobile=await context.newPage();
 await step('mobile portrait/landscape reading, directory, keyboard and no page overflow',async()=>{
  await mobile.setViewportSize({width:393,height:852});await mobile.goto('http://127.0.0.1:15591/help?section=guide&page=backup');await mobile.locator('.documentation').waitFor();
  await mobile.getByRole('button',{name:'文档目录',exact:true}).click();assert.equal(await mobile.locator('#doc-search').evaluate(el=>el===document.activeElement),true);await mobile.keyboard.press('Escape');assert.equal(await mobile.locator('#doc-directory').isVisible(),false);assert.equal(await mobile.getByRole('button',{name:'文档目录',exact:true}).evaluate(el=>el===document.activeElement),true);await mobile.getByRole('button',{name:'文档目录',exact:true}).click();await mobile.locator('#doc-search').fill('备份');await mobile.getByRole('navigation',{name:'文章目录'}).getByRole('link',{name:'备份、保留与恢复',exact:true}).click();
  assert.equal(await mobile.locator('#doc-directory').isVisible(),false);assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await mobile.screenshot({path:path.join(out,'mobile-portrait.png')});
  await mobile.getByRole('navigation',{name:'本页目录'}).getByRole('link',{name:'恢复设置与全站恢复',exact:true}).focus();await mobile.keyboard.press('Enter');assert.ok(mobile.url().includes('#chapter-4'));
  await mobile.setViewportSize({width:852,height:393});assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await mobile.screenshot({path:path.join(out,'mobile-landscape.png')});
 });
 await step('200 percent equivalent viewport and reduced motion',async()=>{
  await mobile.emulateMedia({reducedMotion:'reduce'});await mobile.setViewportSize({width:720,height:500});await mobile.goto('http://127.0.0.1:15591/help?section=api&page=get%3A%2Fdocuments%2F');await mobile.locator('.documentation').waitFor();
  assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await mobile.screenshot({path:path.join(out,'narrow-zoom-equivalent.png')});
 });
 await step('all guide screenshots load, schema models read, and palette B follows existing tokens',async()=>{
  await mobile.setViewportSize({width:1440,height:1000});
  for(const [id,title,count] of [['notes','笔记、新建与模板目录',1],['preferences','外观、阅读与账号偏好',1],['websites','导航、外部网站与独立服务',0],['services','OpenList、Immich 与 SSO',1]]){await mobile.goto(`http://127.0.0.1:15591/help?section=guide&page=${id}`);await mobile.getByRole('heading',{name:title,exact:true}).waitFor();const images=mobile.locator('.doc-image img');assert.equal(await images.count(),count,`${id} documented screenshot inventory`);for(const image of await images.all()){await image.evaluate(async img=>{await img.decode();if(!img.naturalWidth)throw Error('missing documentation image');});}}
  await mobile.evaluate(()=>localStorage.setItem('stella_appearance','B'));
  await mobile.goto('http://127.0.0.1:15591/help?section=api&page=model%3ALoginIn');await mobile.locator('.documentation').waitFor();assert.equal(await mobile.locator('.doc-reading h1').textContent(),'模型 · LoginIn');assert.equal(await mobile.evaluate(()=>document.documentElement.dataset.appearance),'B');
  await mobile.locator('#doc-search').fill('LoginIn');await mobile.screenshot({path:path.join(out,'desktop-palette-b-model.png'),animations:'disabled'});
 });
 assert.deepEqual(errors,[]);assert.deepEqual(requests.filter(r=>!['/auth/refresh'].includes(r.path)),[],'docs must not perform writes or create backups');
 fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({passed:true,steps,errors,requests,environment:'production Vite build, loopback mocked guest auth only; simulated viewports, not real device/production'},null,2));
 console.log(JSON.stringify({passed:true,steps:steps.length,errors,requests}));
}catch(error){fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({passed:false,steps,errors,requests,error:error.stack},null,2));throw error;}finally{await browser.close();}
