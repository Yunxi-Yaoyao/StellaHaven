import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const origin=process.env.NAV_BROWSER_ORIGIN,out=process.env.NAV_EVIDENCE;
assert(origin&&out);await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.STELLA_CHROMIUM?{executablePath:process.env.STELLA_CHROMIUM}:{})});const context=await browser.newContext({ignoreHTTPSErrors:true,storageState:process.env.NAV_QA_STATE,viewport:{width:1440,height:1000}});
const page=await context.newPage();const report={steps:[],pageerrors:[],console:[],requests:[],screenshots:[]};
page.on('pageerror',e=>report.pageerrors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.console.push(m.text());});
page.on('request',r=>{if(new URL(r.url()).origin===origin)report.requests.push([r.method(),new URL(r.url()).pathname]);});
await context.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin===origin)return route.continue();return route.abort();});
const read=async()=>{const r=await context.request.get(origin+'/nav-data');assert.equal(r.status(),200);return r.json();};
const dialog=()=>page.locator('.nav-dialog[open]');
async function footerReachable(){const geometry=await dialog().evaluate(el=>{const r=el.getBoundingClientRect(),footer=el.querySelector('footer').getBoundingClientRect(),button=el.querySelector('footer button').getBoundingClientRect();return {dialog:r.toJSON(),footer:footer.toJSON(),viewport:{width:innerWidth,height:innerHeight},hit:!!document.elementFromPoint(button.x+button.width/2,button.y+button.height/2)?.closest('footer button')};});assert(geometry.dialog.top>=0&&geometry.dialog.bottom<=geometry.viewport.height,JSON.stringify(geometry));assert(geometry.footer.top>=geometry.dialog.top&&geometry.footer.bottom<=geometry.dialog.bottom,JSON.stringify(geometry));assert(geometry.hit,JSON.stringify(geometry));report.geometry??=[];report.geometry.push(geometry);}

const settings=async()=>{await page.getByRole('button',{name:'导航设置',exact:true}).click();await expect(dialog()).toBeVisible();};
const shot=async name=>{await page.screenshot({path:out+'/'+name});report.screenshots.push(name);};
const step=async(name,fn)=>{await fn();report.steps.push(name);console.log('PASS',name);};
try{
 await page.goto(origin+'/away');await page.getByRole('link',{name:'进入原生导航',exact:true}).click();await expect(page.getByText('多窗口同步已连接',{exact:true})).toBeVisible();
 await step('WS authoritative revision preserves open draft and three-way rebase saves only intended edit',async()=>{
  await settings();await dialog().getByLabel('导航标题',{exact:true}).fill('draft title');
  const other=await read();other.data.preferences.padding=32;
  assert.equal((await context.request.put(origin+'/nav-data',{headers:{Origin:origin},data:{...other,mutation_id:crypto.randomUUID()}})).status(),200);
  await expect(dialog().getByRole('button',{name:'以最新版本重新应用草稿',exact:true})).toBeVisible();
  await expect(dialog().getByLabel('导航标题',{exact:true})).toHaveValue('draft title');
  await dialog().getByRole('button',{name:'以最新版本重新应用草稿',exact:true}).click();
  await dialog().getByRole('button',{name:'保存',exact:true}).click();await expect(dialog()).toHaveCount(0);
  const actual=await read();assert.equal(actual.data.preferences.padding,32);assert.equal(actual.data.preferences.title,'draft title');
 });
 await step('native router leave/reenter restores owner-private memory draft without any write; cancel discards it',async()=>{
  const before=await read();await settings();await dialog().getByLabel('导航标题',{exact:true}).fill('UNSAVED route draft');
  await page.goBack();await expect(page.getByRole('heading',{name:'离页验收',exact:true})).toBeVisible();
  await page.getByRole('link',{name:'进入原生导航',exact:true}).click();await page.getByRole('button',{name:'恢复未保存导航草稿',exact:true}).click();await expect(dialog().getByLabel('导航标题',{exact:true})).toHaveValue('UNSAVED route draft');
  assert.deepEqual(await read(),before);await dialog().getByRole('button',{name:'取消',exact:true}).click();await expect(page.getByRole('button',{name:'恢复未保存导航草稿',exact:true})).toHaveCount(0);
 });
 await step('explicit module rebind through shared Dropdown and consent invalidation commits with asset bytes in PG',async()=>{
  await settings();await dialog().getByRole('button',{name:'数据工具',exact:true}).click();
  await dialog().getByLabel('待解析的导航 JSON',{exact:true}).fill(await fs.readFile(process.env.NAV_SYNTHETIC_TRANSFER,'utf8'));
  await dialog().getByRole('button',{name:'完整包预览（不写入）',exact:true}).click();
  const confirm=dialog().getByLabel('我已检查差异，确认替换导航及上述打开方式映射',{exact:true});await confirm.check();
  const bind=dialog().getByRole('button',{name:/迁移网站 .* 的模块绑定/});await bind.click();await page.getByRole('option',{name:'Docs',exact:true}).click();await expect(confirm).not.toBeChecked();
  await shot('rebind-preview.png');await confirm.check();await dialog().getByRole('button',{name:'确认原子导入',exact:true}).click();await expect(dialog()).toHaveCount(0);
  const actual=await read(),card=actual.data.groups[0].items[0];assert.equal(card.module_id,'docs');await expect(page.locator(`[data-card="${card.id}"] > a`)).toHaveAttribute('href','/apps/docs');
  const asset=await context.request.get(origin+actual.data.preferences.backgroundUrl);assert.equal(asset.status(),200);assert((await asset.body()).length>0);
 });
 await step('393px and CSS 200% equivalent width: real content and settings controls remain reachable',async()=>{
  await page.setViewportSize({width:393,height:852});await shot('nav-393.png');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await settings();await expect(dialog().getByRole('button',{name:'取消',exact:true})).toBeVisible();await footerReachable();await shot('settings-393.png');await dialog().getByRole('button',{name:'取消',exact:true}).click();
  await page.setViewportSize({width:720,height:500});await page.evaluate(()=>document.documentElement.style.zoom='2');await settings();await expect(dialog().getByRole('button',{name:'取消',exact:true})).toBeVisible();await footerReachable();await shot('settings-csszoom-200.png');await dialog().getByRole('button',{name:'取消',exact:true}).click();
 });
 assert.deepEqual(report.pageerrors,[]);
}finally{await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2));await context.close();await browser.close();}
