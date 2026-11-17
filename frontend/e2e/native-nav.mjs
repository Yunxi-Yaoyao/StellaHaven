import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const origin='https://127.0.0.1:33171';
const output=process.env.NAV_EVIDENCE;
assert(output&&process.env.NAV_QA_STATE,'explicit private fixture/evidence paths required');
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const result={origin,steps:[],pageErrors:[],consoleErrors:[],failedResponses:[],externalRequests:[],screenshots:[]};
let current='setup';
const context=await browser.newContext({ignoreHTTPSErrors:true,storageState:process.env.NAV_QA_STATE,viewport:{width:1440,height:1000}});
const page=await context.newPage();
page.on('pageerror',e=>result.pageErrors.push(e.message));
page.on('console',m=>{if(m.type()==='error')result.consoleErrors.push(m.text());});
page.on('response',r=>{if(r.status()>=400)result.failedResponses.push({status:r.status(),path:new URL(r.url()).pathname});});
await page.route('**/*',async route=>{if(!route.request().url().startsWith(origin+'/')){result.externalRequests.push(route.request().url());await route.abort();}else await route.continue();});
const read=async()=>{const r=await context.request.get(origin+'/nav-data');assert.equal(r.status(),200);return r.json();};
const step=async(name,fn)=>{current=name;await fn();result.steps.push(name);console.log('PASS',name);};
const dialog=()=>page.locator('.nav-dialog[open]');
const choose=async(scope,label,text)=>{await scope.getByRole('button',{name:label,exact:true}).click();await scope.getByRole('option',{name:text,exact:true}).click();};
const save=async()=>{await dialog().getByRole('button',{name:'保存',exact:true}).click();await expect(dialog()).toHaveCount(0);};
const openSettings=async()=>{await page.getByRole('button',{name:'导航设置',exact:true}).click();await expect(dialog()).toBeVisible();};
const shot=async(name)=>{await expect(page.locator('.toast-stack .toast')).toHaveCount(0);await page.mouse.move(1,1);await page.screenshot({path:path.join(output,name)});result.screenshots.push(name);};
try{
 await step('actual authenticated Stella shell and native sidebar route',async()=>{
  assert.equal((await context.request.get(origin+'/auth/me')).status(),200);
  await page.goto(origin+'/help');await page.locator('#site-sidebar a[href="/nav"]').click();
  await expect(page).toHaveURL(origin+'/nav');await expect(page.getByRole('button',{name:'新增分组',exact:true})).toBeEnabled();
  assert.equal(await page.locator('.native-nav iframe').count(),0);
 });
 await step('group create and nullable group style readback',async()=>{
  await page.getByRole('button',{name:'新增分组',exact:true}).click();
  await dialog().getByLabel('分组名称',{exact:true}).fill('工作与文档');
  await dialog().getByLabel('分组描述',{exact:true}).fill('合成数据 · 实际 PostgreSQL');
  await choose(dialog(),'卡片布局','详情');
  await choose(dialog(),'详情描述','显示');await save();
  const s=await read();assert.equal(s.data.groups[0].style.hideDescription,false);assert.equal(s.data.groups[0].style.layout,'info');
 });
 await step('card create public/private text icon and refresh persistence',async()=>{
  await page.getByRole('button',{name:'新增网站',exact:true}).click();
  await dialog().getByLabel('网站名称',{exact:true}).fill('文档中心');
  await dialog().getByLabel('公网地址',{exact:true}).fill('https://example.test/docs?q=1#intro');
  await dialog().getByLabel('内网地址',{exact:true}).fill('http://192.0.2.5/docs');
  await dialog().getByLabel('图标内容',{exact:true}).fill('文');
  await dialog().getByLabel('描述',{exact:true}).fill('查阅知识与接口 · 长描述仍保留');await save();
  const before=await read();assert.equal(before.data.groups[0].items[0].lanUrl,'http://192.0.2.5/docs');
  await page.reload();await expect(page.getByRole('button',{name:'编辑网站 文档中心',exact:true})).toBeVisible();assert.deepEqual(await read(),before);
  await choose(page,'此设备线路','内网');assert.equal(await page.locator('.nav-card>a').getAttribute('href'),'http://192.0.2.5/docs');
  await choose(page,'此设备线路','公网');
 });
 await step('search filters description/address and slash/escape work',async()=>{
  await page.locator('h1').click();await page.keyboard.press('/');await expect(page.getByRole('textbox',{name:'搜索网站',exact:true})).toBeFocused();
  await page.getByRole('textbox',{name:'搜索网站',exact:true}).fill('192.0.2.5');assert.equal(await page.locator('.nav-card').count(),1);
  await page.getByRole('textbox',{name:'搜索网站',exact:true}).fill('does-not-match');await expect(page.getByText('没有匹配的网站',{exact:true})).toBeVisible();
  await page.keyboard.press('Escape');await expect(page.locator('.nav-card')).toHaveCount(1);
 });
 await step('cancel does not write and definite save failure retains draft/retry',async()=>{
  const before=await read();await page.getByRole('button',{name:'编辑网站 文档中心',exact:true}).click();await dialog().getByLabel('网站名称',{exact:true}).fill('取消的草稿');await page.keyboard.press('Escape');assert.deepEqual(await read(),before);
  await page.getByRole('button',{name:'编辑网站 文档中心',exact:true}).click();await dialog().getByLabel('网站名称',{exact:true}).fill('文档中心 · 已修改');
  await page.route('**/nav-data',async route=>{if(route.request().method()==='PUT')await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'合成保存失败，请重试'})});else await route.continue();},{times:1});
  await dialog().getByRole('button',{name:'保存',exact:true}).click();await expect(dialog().getByRole('alert')).toContainText('合成保存失败');await expect(dialog().getByLabel('网站名称',{exact:true})).toHaveValue('文档中心 · 已修改');assert.deepEqual(await read(),before);await save();
 });
 await step('conflict explicit three-way rebase keeps unrelated server settings',async()=>{
  await page.getByRole('button',{name:'编辑网站 文档中心 · 已修改',exact:true}).click();await dialog().getByLabel('网站名称',{exact:true}).fill('文档中心 · 合并');
  const actual=await read();actual.data.preferences.title='另一设备的标题';
  const r=await context.request.put(origin+'/nav-data',{data:{...actual,mutation_id:crypto.randomUUID()}});assert.equal(r.status(),200);
  await dialog().getByRole('button',{name:'保存',exact:true}).click();await expect(dialog().getByRole('alert')).toContainText('其他窗口已修改');
  await dialog().getByRole('button',{name:'读取服务端版本（保留草稿）'}).click();await expect(dialog().getByRole('button',{name:'以最新版本重新应用草稿'})).toBeVisible();await dialog().getByRole('button',{name:'以最新版本重新应用草稿'}).click();await save();
  const after=await read();assert.equal(after.data.preferences.title,'另一设备的标题');assert.equal(after.data.groups[0].items[0].title,'文档中心 · 合并');
 });
 await step('global style/group override and all three inheritance states',async()=>{
  await openSettings();await choose(dialog(),'卡片布局','图标');await choose(dialog(),'详情描述','隐藏');await save();
  await page.getByRole('button',{name:'编辑分组 工作与文档',exact:true}).click();await choose(dialog(),'图标标题','隐藏');await save();
  let s=await read();assert.equal(s.data.groups[0].style.hideTitle,true);assert.equal(s.data.groups[0].style.hideDescription,false);assert.equal(s.data.preferences.hideDescription,true);
  await page.getByRole('button',{name:'编辑分组 工作与文档',exact:true}).click();await choose(dialog(),'图标标题','显示');await save();
  s=await read();assert.equal(s.data.groups[0].style.hideTitle,false);
  await page.getByRole('button',{name:'编辑分组 工作与文档',exact:true}).click();await choose(dialog(),'图标标题','继承全局');await save();s=await read();assert.equal(s.data.groups[0].style.hideTitle,null);
 });
 await step('second group/card sorting and cross-group move',async()=>{
  await page.getByRole('button',{name:'新增分组',exact:true}).click();await dialog().getByLabel('分组名称',{exact:true}).fill('生活与工具');await save();
  await page.getByRole('button',{name:'向 生活与工具 新增网站',exact:true}).click();await dialog().getByLabel('网站名称',{exact:true}).fill('工具箱');await dialog().getByLabel('公网地址',{exact:true}).fill('https://example.test/tools');await dialog().getByLabel('图标内容',{exact:true}).fill('工');await save();
  await page.getByRole('button',{name:'上移分组 生活与工具',exact:true}).click();await expect(page.locator('.nav-section h2').first()).toContainText('生活与工具');assert.equal((await read()).data.groups[0].title,'生活与工具');
  await page.getByRole('button',{name:'编辑网站 工具箱',exact:true}).click();const target=(await read()).data.groups.find(g=>g.title==='工作与文档');await choose(dialog(),'所属分组',target.title);await save();
  await page.getByRole('button',{name:'上移网站 工具箱',exact:true}).click();await expect(page.locator(`[data-group="${target.id}"] .nav-card strong`).first()).toHaveText('工具箱');assert.equal((await read()).data.groups.find(g=>g.id===target.id).items[0].title,'工具箱');
 });
 await step('search engine native settings persist and hidden search disables slash',async()=>{
  await openSettings();await dialog().getByRole('button',{name:'搜索',exact:true}).click();await dialog().getByRole('button',{name:'新增引擎',exact:true}).click();await dialog().getByLabel('名称',{exact:true}).fill('示例搜索');await dialog().getByLabel('搜索地址',{exact:true}).fill('https://example.test/search?q={query}');await dialog().getByLabel('显示搜索栏（斜杠聚焦）').uncheck();await save();
  assert.equal((await read()).data.preferences.engines[0].title,'示例搜索');assert.equal(await page.getByRole('textbox',{name:'搜索网站',exact:true}).count(),0);
  await page.locator('h1').click();await page.keyboard.press('/');assert.equal(await page.locator('.nav-search input:focus').count(),0);
  await openSettings();await dialog().getByRole('button',{name:'搜索',exact:true}).click();await dialog().getByLabel('显示搜索栏（斜杠聚焦）').check();await save();
 });
 await step('asset upload/image selection/background readback and reference safety',async()=>{
  await openSettings();await dialog().getByRole('button',{name:'素材',exact:true}).click();const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qXYAAAAASUVORK5CYII=','base64');
  await dialog().locator('input[type=file]').setInputFiles({name:'合成像素.png',mimeType:'image/png',buffer:png});await expect(dialog().locator('.nav-material-grid').getByText('合成像素.png',{exact:true})).toBeVisible();
  const list=await (await context.request.get(origin+'/nav-assets')).json();assert.equal(list.length,1);assert.deepEqual(await (await context.request.get(origin+list[0].url)).body(),png);
  await dialog().getByRole('button',{name:'背景',exact:true}).click();await choose(dialog(),'背景来源','导航独立背景');await dialog().getByRole('button',{name:'选择背景素材',exact:true}).click();await dialog().getByRole('button',{name:'背景素材 '+list[0].name,exact:true}).click();const mask=dialog().getByRole('slider',{name:'遮罩',exact:true});await mask.press('End');for(let i=0;i<5;i++)await mask.press('ArrowLeft');await save();assert.equal((await read()).data.preferences.mask,0.75);
  assert.equal((await context.request.delete(origin+list[0].url,{headers:{Origin:origin}})).status(),409);
  await page.getByRole('button',{name:'编辑网站 工具箱',exact:true}).click();await choose(dialog(),'图标类型','图片');await dialog().getByRole('button',{name:'选择图片素材',exact:true}).click();await dialog().getByRole('button',{name:'图片素材 '+list[0].name,exact:true}).click();await save();
 });
 await step('native full-settings export download and read-only compatibility preview',async()=>{
  await openSettings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();const downloadPromise=page.waitForEvent('download');await dialog().getByRole('button',{name:'导出导航配置',exact:true}).click();const download=await downloadPromise;assert.match(download.suggestedFilename(),/Stella-Native-Navigation/);const downloaded=JSON.parse(await fs.readFile(await download.path(),'utf8'));assert.equal(downloaded.appName,'Stella-Native-Nav');assert.equal(downloaded.boundary.asset_bytes,false);assert.equal(downloaded.data.preferences.engines[0].title,'示例搜索');
  const before=await read();await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(JSON.stringify(downloaded));await dialog().getByRole('button',{name:'解析与差异预览',exact:true}).click();await expect(dialog().locator('.nav-import-preview')).toContainText('2 个分组');assert.deepEqual(await read(),before);await dialog().getByRole('button',{name:'取消',exact:true}).click();
 });
 await step('lost ACK commits once then blocks replay and reconciles with real PG',async()=>{
  await page.getByRole('button',{name:'编辑网站 文档中心 · 合并',exact:true}).click();await dialog().getByLabel('描述',{exact:true}).fill('丢 ACK 后的真实提交');
  let writes=0;const observe=req=>{if(new URL(req.url()).pathname==='/nav-data'&&req.method()==='PUT')writes++;};page.on('request',observe);
  await page.route('**/nav-data',async route=>{if(route.request().method()==='PUT'){const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');}else await route.continue();},{times:1});
  await dialog().getByRole('button',{name:'保存',exact:true}).click();await expect(dialog().getByRole('alert')).toContainText('保存未确认');await expect(dialog().getByRole('button',{name:'保存',exact:true})).toBeDisabled();
  assert.equal((await read()).data.groups.flatMap(g=>g.items).find(c=>c.title==='文档中心 · 合并').description,'丢 ACK 后的真实提交');
  await dialog().getByRole('button',{name:'读取服务端版本（保留草稿）'}).click();await expect(dialog().getByRole('button',{name:'以最新版本重新应用草稿'})).toBeVisible();assert.equal(writes,1);await dialog().getByRole('button',{name:'取消',exact:true}).click();page.off('request',observe);
 });
 await step('cancelled import preview late response cannot repopulate a new dialog',async()=>{
  const exported=await (await context.request.get(origin+'/nav-export')).json();await openSettings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(JSON.stringify(exported));
  let release,seen;const held=new Promise(r=>release=r),started=new Promise(r=>seen=r);let settled;const done=new Promise(r=>settled=r);
  await page.route('**/nav-import-preview',async route=>{const response=await route.fetch();seen();await held;await route.fulfill({response});settled();},{times:1});
  await dialog().getByRole('button',{name:'解析与差异预览',exact:true}).click();await started;await dialog().getByRole('button',{name:'取消',exact:true}).click();await openSettings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();release();await done;await page.waitForTimeout(120);assert.equal(await dialog().locator('.nav-import-preview').count(),0);await expect(dialog().getByLabel('待解析的导航 JSON',{exact:true})).toHaveValue('');await dialog().getByRole('button',{name:'取消',exact:true}).click();
 });
 await step('desktop/narrow actual layout and editors stay inside viewport',async()=>{
  await shot('native-desktop.png');
  await page.setViewportSize({width:393,height:852});await page.waitForTimeout(220);await shot('native-narrow.png');
  const geometry=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,cards:[...document.querySelectorAll('.nav-card')].map(x=>{const r=x.getBoundingClientRect();return {x:r.x,right:r.right,width:r.width};})}));assert(geometry.width<=geometry.viewport+1);for(const r of geometry.cards)assert(r.x>=0&&r.right<=geometry.viewport+1);
  await page.getByRole('button',{name:'编辑网站 文档中心 · 合并',exact:true}).click();await dialog().getByLabel('描述',{exact:true}).scrollIntoViewIfNeeded();await shot('native-editor-narrow.png');const d=await dialog().boundingBox();assert(d.x>=0&&d.x+d.width<=393&&d.y>=0&&d.y+d.height<=852);await dialog().getByRole('button',{name:'取消',exact:true}).click();
  await fs.writeFile(path.join(output,'geometry.json'),JSON.stringify(geometry,null,2));await page.setViewportSize({width:320,height:740});await page.waitForTimeout(220);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await shot('native-320.png');await page.setViewportSize({width:1440,height:1000});
 });
 await step('delete exact card and empty group through confirmation/readback',async()=>{
  await page.getByRole('button',{name:'删除网站 工具箱',exact:true}).click();await expect(dialog()).toContainText('工具箱');await dialog().getByRole('button',{name:'确认删除',exact:true}).click();await expect(dialog()).toHaveCount(0);assert.equal((await read()).data.groups.flatMap(g=>g.items).some(c=>c.title==='工具箱'),false);
  await page.getByRole('button',{name:'删除分组 生活与工具',exact:true}).click();await dialog().getByRole('button',{name:'确认删除',exact:true}).click();await expect(dialog()).toHaveCount(0);assert.equal((await read()).data.groups.some(g=>g.title==='生活与工具'),false);
 });
 await step('guest cannot read native navigation/assets',async()=>{const guest=await browser.newContext({ignoreHTTPSErrors:true});try{assert.equal((await guest.request.get(origin+'/nav-data')).status(),401);assert.equal((await guest.request.get(origin+'/nav-export')).status(),401);assert.equal((await guest.request.get(origin+'/nav-assets')).status(),401);}finally{await guest.close();}});
 assert.deepEqual(result.pageErrors,[]);assert.deepEqual(result.externalRequests,[]);
 assert.deepEqual(result.failedResponses,[{status:503,path:'/nav-data'},{status:409,path:'/nav-data'}]);
 assert.equal(result.consoleErrors.length,3);assert(result.consoleErrors.some(x=>x.includes('503'))&&result.consoleErrors.some(x=>x.includes('409'))&&result.consoleErrors.some(x=>x.includes('ERR_FAILED')));
 result.finalSnapshot=await read();result.status='passed';
}catch(error){result.status='failed';result.failedStep=current;result.error=String(error);console.error(error);try{await shot('failure.png');}catch{}process.exitCode=1;}
finally{await fs.writeFile(path.join(output,'browser-results.json'),JSON.stringify(result,null,2));await context.close();await browser.close();}
