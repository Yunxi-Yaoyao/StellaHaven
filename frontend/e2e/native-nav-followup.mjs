import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
const origin='https://127.0.0.1:33171',out=process.env.NAV_EVIDENCE;
assert(out&&process.env.NAV_QA_STATE);await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true}),context=await browser.newContext({ignoreHTTPSErrors:true,storageState:process.env.NAV_QA_STATE,viewport:{width:1440,height:1000}}),page=await context.newPage();
const report={steps:[],errors:[],external:[],screenshots:[]};let current='setup';
page.on('pageerror',e=>report.errors.push(e.message));
const step=async(name,fn)=>{current=name;await fn();report.steps.push(name);console.log('PASS',name);};
const read=async()=>{const r=await context.request.get(origin+'/nav-data');assert.equal(r.status(),200);return r.json();};
const choose=async(scope,label,text)=>{await scope.getByRole('button',{name:label,exact:true}).click();await scope.getByRole('option',{name:text,exact:true}).click();};
const dialog=()=>page.locator('.nav-dialog[open]');
const settings=async()=>{await page.getByRole('button',{name:'导航设置',exact:true}).click();await expect(dialog()).toBeVisible();};
const cancel=async()=>{await dialog().getByRole('button',{name:'取消',exact:true}).click();await expect(dialog()).toHaveCount(0);};
const save=async()=>{await dialog().getByRole('button',{name:'保存',exact:true}).click();await expect(dialog()).toHaveCount(0);};
const shot=async(name)=>{await page.locator('.toast-stack .toast').count().then(async n=>{if(n)await expect(page.locator('.toast-stack .toast')).toHaveCount(0);});await page.screenshot({path:path.join(out,name)});report.screenshots.push(name);};
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qXYAAAAASUVORK5CYII=','base64');
await page.route('**/*',async route=>{if(route.request().url().startsWith(origin+'/'))return route.continue();const r=route.request(),u=new URL(r.url());report.external.push({url:r.url(),headers:await r.allHeaders()});if(u.origin==='https://www.wikipedia.org'&&['/favicon.ico','/apple-touch-icon.png','/favicon.png'].includes(u.pathname))return route.fulfill({status:200,headers:{'Access-Control-Allow-Origin':'*'},contentType:'image/png',body:png});return route.abort();});
try{
 await page.goto(origin+'/nav');await expect(page.getByRole('button',{name:'新增分组',exact:true})).toBeEnabled();
 // Repeat only on this synthetic owner: normalize prior failed-run scaffolding.
 const me=await (await context.request.get(origin+'/auth/me')).json();assert.equal(me.username,'native-nav-browser');
 const initial=await read();initial.data.groups=initial.data.groups.filter(g=>g.items.length);if(initial.data.groups[0])initial.data.groups[0].title='工作与文档';assert.equal((await context.request.put(origin+'/nav-data',{headers:{Origin:origin},data:{...initial,mutation_id:crypto.randomUUID()}})).status(),200);await page.reload();await expect(page.getByRole('button',{name:'新增分组',exact:true})).toBeEnabled();
 await step('real shared Dropdown keyboard + complete preferences persist',async()=>{
  assert.equal(await page.locator('.native-nav select,.native-nav datalist').count(),0);
  await settings();const b=dialog().getByRole('button',{name:'宽度单位',exact:true});await b.focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('End');await page.keyboard.press('Enter');await expect(b).toContainText('%');await b.click();await page.keyboard.press('Escape');await expect(dialog()).toBeVisible();await expect(b).toHaveAttribute('aria-expanded','false');
  await dialog().getByLabel('内容宽度',{exact:true}).fill('85');await dialog().getByLabel('横向边距（px）',{exact:true}).fill('7');await dialog().getByLabel('顶部边距（%）',{exact:true}).fill('4');await dialog().getByLabel('底部边距（%）',{exact:true}).fill('10');
  await dialog().getByRole('button',{name:'文字颜色 #a5decb',exact:true}).click();await shot('settings-dropdown-color.png');const controlSizes=await dialog().evaluate(el=>({checks:[...el.querySelectorAll('input[type=checkbox]')].map(x=>x.getBoundingClientRect().width),colors:[...el.querySelectorAll('input[type=color]')].map(x=>x.getBoundingClientRect().width)}));assert(controlSizes.checks.every(w=>w<=24));assert(controlSizes.colors.every(w=>w<=40));
  await dialog().getByRole('button',{name:'搜索',exact:true}).click();await dialog().getByLabel('外部搜索在新窗口打开',{exact:true}).uncheck();await save();
  const p=(await read()).data.preferences;assert.equal(p.width,85);assert.equal(p.widthUnit,'%');assert.equal(p.marginX,7);assert.equal(p.marginTop,4);assert.equal(p.marginBottom,10);assert.equal(p.newWindowOpen,false);assert.equal(p.textColor,'#a5decb');
 });
 await step('actual pointer drag reorder groups and cross-group cards preserves keyboard controls',async()=>{
  await page.getByRole('button',{name:'新增分组',exact:true}).click();await dialog().getByLabel('分组名称',{exact:true}).fill('拖拽目标');await save();
  const initial=await read(),source=initial.data.groups[0],target=initial.data.groups.find(g=>g.title==='拖拽目标'),card=source.items[0];
  await page.getByRole('button',{name:'拖动分组 拖拽目标',exact:true}).dragTo(page.locator(`[data-group="${source.id}"] .nav-section-head`));
  await expect.poll(async()=>(await read()).data.groups[0].id).toBe(target.id);
  await page.getByRole('button',{name:'拖动网站 '+card.title,exact:true}).dragTo(page.locator(`[data-group="${target.id}"] .nav-cards`));
  await expect.poll(async()=>(await read()).data.groups.find(g=>g.id===target.id).items[0]?.id).toBe(card.id);
  await expect(page.getByRole('button',{name:'下移分组 拖拽目标',exact:true})).toBeEnabled();
  await shot('dragged-desktop.png');
 });
 await step('bounded explicit favicon candidates browser-only, anonymous, no state writes',async()=>{
  const before=await read(),card=before.data.groups.flatMap(g=>g.items)[0];await page.getByRole('button',{name:'编辑网站 '+card.title,exact:true}).click();await dialog().getByLabel('公网地址',{exact:true}).fill('https://www.wikipedia.org/private?token=synthetic');await choose(dialog(),'图标类型','图片');await dialog().getByRole('button',{name:'发现公开favicon（最多3候选）',exact:true}).click();await expect(dialog().locator('.nav-favicon-candidates button')).toHaveCount(2); // This Chromium blocks favicon.ico with ERR_ABORTED before routing; verify both anonymous PNG fallbacks.
  const urls=[...new Set(report.external.map(x=>x.url))];assert.equal(urls.length,2);assert(urls.every(u=>u.endsWith('.png')));for(const r of report.external){assert(!r.url.includes('token'));assert(!r.headers.cookie);assert(!r.headers.authorization);assert(!r.headers.referer);}
  await shot('favicon-and-visual-assets.png');await cancel();assert.deepEqual(await read(),before);
 });
 await step('visual material and main wallpaper catalog picker is reused',async()=>{
  await settings();await dialog().getByRole('button',{name:'背景',exact:true}).click();await choose(dialog(),'背景来源','导航独立背景');await dialog().getByRole('button',{name:'选择背景素材',exact:true}).click();await expect(dialog().locator('.nav-material-grid.is-picker')).toBeVisible();await shot('wallpaper-picker.png');await cancel();
 });
 await step('asset dimensions/category filter/batch refusal is all-or-none and explicit batch delete',async()=>{
  await settings();await dialog().getByRole('button',{name:'素材',exact:true}).click();
  for(const name of ['批量A.png','批量B.png']){await dialog().locator('input[type=file]').setInputFiles({name,mimeType:'image/png',buffer:png});await expect(dialog().getByText(name,{exact:true})).toBeVisible();}
  const before=(await (await context.request.get(origin+'/nav-assets')).json());const picked=before.filter(a=>a.name.startsWith('批量'));
  for(const a of picked)await dialog().getByRole('checkbox',{name:'选择素材 '+a.name,exact:true}).check();
  await choose(dialog(),'批量用途分类','标识');await dialog().getByRole('button',{name:'应用分类',exact:true}).click();
  await expect.poll(async()=>(await (await context.request.get(origin+'/nav-assets')).json()).filter(a=>a.name.startsWith('批量')&&a.category==='logo').length).toBe(2);
  await choose(dialog(),'素材分类筛选','标识');await expect(dialog().locator('.nav-material-grid article')).toHaveCount(2);await dialog().locator('.nav-material-grid article').first().getByText('素材详情',{exact:true}).click();await expect(dialog().locator('.nav-material-grid article').first()).toContainText('1 × 1');await expect(dialog().locator('.nav-material-grid article').first()).toContainText('SHA-256');await shot('asset-category-details.png');
  await choose(dialog(),'素材分类筛选','全部分类');await dialog().getByRole('button',{name:'选择当前分类',exact:true}).click();page.once('dialog',d=>d.accept());await dialog().getByRole('button',{name:'删除所选',exact:true}).click();await expect(dialog().getByRole('alert')).toContainText('未删除任何素材');assert.equal((await (await context.request.get(origin+'/nav-assets')).json()).length,before.length);
  await dialog().getByRole('button',{name:'清除选择',exact:true}).click();await choose(dialog(),'素材分类筛选','标识');await dialog().getByRole('button',{name:'选择当前分类',exact:true}).click();page.once('dialog',d=>d.accept());await dialog().getByRole('button',{name:'删除所选',exact:true}).click();await expect(dialog().locator('.nav-material-grid article')).toHaveCount(0);assert.equal((await (await context.request.get(origin+'/nav-assets')).json()).length,before.length-2);await cancel();
 });
 await step('complete package download bytes / preview cancel / explicit confirm import and PG readback',async()=>{
  await settings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();const event=page.waitForEvent('download');await dialog().getByRole('button',{name:'导出完整包（含素材字节）',exact:true}).click();const download=await event;const pack=JSON.parse(await fs.readFile(await download.path(),'utf8'));assert.equal(pack.version,2);assert(pack.assets.length>0);assert.deepEqual(Buffer.from(pack.assets[0].base64,'base64'),png);
  const before=await read();await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(JSON.stringify(pack));await dialog().getByRole('button',{name:'完整包预览（不写入）',exact:true}).click();await expect(dialog().getByRole('button',{name:'确认原子导入',exact:true})).toBeDisabled();assert.deepEqual(await read(),before);await shot('complete-package-preview.png');await cancel();assert.deepEqual(await read(),before);
  await settings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(JSON.stringify(pack));await dialog().getByRole('button',{name:'完整包预览（不写入）',exact:true}).click();await dialog().getByLabel('我已检查差异，确认替换导航及上述打开方式映射',{exact:true}).check();await dialog().getByRole('button',{name:'确认原子导入',exact:true}).click();await expect(dialog()).toHaveCount(0);const after=await read();assert.equal(after.revision,before.revision+1);assert.deepEqual(after.data.groups.map(g=>g.title),before.data.groups.map(g=>g.title));assert.deepEqual(await (await context.request.get(origin+after.data.preferences.backgroundUrl)).body(),png);
 });
 await step('complete package CAS and lost ACK preserve atomicity and block replay',async()=>{
  let pack=await (await context.request.get(origin+'/nav-package')).json();const source=JSON.stringify(pack);
  const openPreview=async()=>{await settings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(source);await dialog().getByRole('button',{name:'完整包预览（不写入）',exact:true}).click();await dialog().getByLabel('我已检查差异，确认替换导航及上述打开方式映射',{exact:true}).check();};
  await openPreview();const before=await read(),assetsBefore=await (await context.request.get(origin+'/nav-assets')).json();before.data.preferences.title='完整包并发对照';assert.equal((await context.request.put(origin+'/nav-data',{headers:{Origin:origin},data:{...before,mutation_id:crypto.randomUUID()}})).status(),200);
  await dialog().getByRole('button',{name:'确认原子导入',exact:true}).click();await expect(dialog().getByRole('alert')).toContainText('导航已变化');assert.deepEqual(await (await context.request.get(origin+'/nav-assets')).json(),assetsBefore);assert.equal((await read()).data.preferences.title,'完整包并发对照');await dialog().getByRole('button',{name:'读取服务端版本（保留草稿）',exact:true}).click();await cancel();
  await openPreview();let posts=0;page.on('request',r=>{if(new URL(r.url()).pathname==='/nav-package-import'&&r.method()==='POST')posts++;});const revision=(await read()).revision;
  await page.route('**/nav-package-import',async route=>{const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');},{times:1});
  await dialog().getByRole('button',{name:'确认原子导入',exact:true}).click();await expect(dialog().getByRole('alert')).toContainText('保存未确认');await expect(dialog().getByRole('button',{name:'确认原子导入',exact:true})).toBeDisabled();assert.equal((await read()).revision,revision+1);assert.equal((await (await context.request.get(origin+'/nav-assets')).json()).length,assetsBefore.length);
  await dialog().getByRole('button',{name:'读取服务端版本（保留草稿）',exact:true}).click();assert.equal(posts,1);await cancel();
 });
 await step('synthetic current legacy panel/searchEngine/bytes maps openMethod3 only after manual confirmation',async()=>{
  assert(process.env.NAV_SYNTHETIC_SOURCE,'synthetic old-site transfer fixture required');const source=await fs.readFile(process.env.NAV_SYNTHETIC_SOURCE,'utf8');
  const before=await read();await settings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(source);await dialog().getByRole('button',{name:'完整包预览（不写入）',exact:true}).click();await expect(dialog().locator('.nav-import-preview')).toContainText('旧 openMethod=3');await expect(dialog().locator('.nav-import-preview')).toContainText('独立新标签打开');assert.deepEqual(await read(),before);await shot('legacy-explicit-open-method-difference.png');
  await dialog().getByLabel('我已检查差异，确认替换导航及上述打开方式映射',{exact:true}).check();await dialog().getByRole('button',{name:'确认原子导入',exact:true}).click();await expect(dialog()).toHaveCount(0);const after=await read();assert.equal(after.revision,before.revision+1);assert.equal(after.data.preferences.newWindowOpen,false);assert.equal(after.data.preferences.layout,'info');assert.equal(after.data.preferences.defaultEngine,after.data.preferences.engines[1].id);assert.equal(after.data.preferences.marginX,5);assert.equal(after.data.preferences.marginTop,4);assert.equal(after.data.preferences.marginBottom,10);assert.equal(after.data.preferences.widthUnit,'%');assert.equal(after.data.groups[0].items[0].openMethod,2);assert.equal(await page.locator('.native-nav iframe').count(),0);assert.equal(await page.locator('.native-nav script').count(),0);assert.deepEqual(await (await context.request.get(origin+after.data.preferences.backgroundUrl)).body(),png);
 });
 await step('new native UI narrow and color/material editor fit actual viewport',async()=>{await page.setViewportSize({width:393,height:852});await shot('followup-narrow.png');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await settings();await shot('followup-settings-narrow.png');const r=await dialog().boundingBox();assert(r.x>=0&&r.x+r.width<=393);await cancel();});
 assert.deepEqual(report.errors,[]);report.status='passed';report.final=await read();
}catch(e){report.status='failed';report.failedStep=current;report.error=String(e);console.error(e);process.exitCode=1;try{await shot('failure.png');}catch{}}
finally{await fs.writeFile(path.join(out,'browser-results.json'),JSON.stringify(report,null,2));await context.close();await browser.close();}
