// Isolated real-component browser acceptance. Synthetic API, no PG/auth claim.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium,expect} from '@playwright/test';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
const root=process.cwd(),out=resolve(root,'../remediation/alerts-window-evidence');
await mkdir(out,{recursive:true});
const files=['src/modules/servers/MetricAlertsPanel.vue','src/modules/servers/alertMetricTime.ts','src/modules/servers/alertMetricUnits.ts','src/api/alertMetrics.ts','src/style.css','tests/alerts-window-browser.mjs'];
async function hashes(){return Object.fromEntries(await Promise.all(files.map(async f=>[f,createHash('sha256').update(await readFile(resolve(root,f))).digest('hex')])));}
const before=await hashes();
const server=await createServer({root,configFile:false,envDir:false,plugins:[vue(),{
 name:'isolated-alert-fixture',
 resolveId(id,importer){if(id==='/alerts-entry.js')return '\0alerts-entry';if(id==='./client'&&importer?.includes('/src/api/'))return '\0fixture-api';},
 load(id){if(id==='\0fixture-api')return `export async function api(path,options){const response=await fetch(path,options);const body=await response.json();if(!response.ok)throw body;return body;}`;
 if(id==='\0alerts-entry')return `import {createApp} from 'vue';import '@fontsource-variable/inter';import '/src/style.css';import Panel from '/src/modules/servers/MetricAlertsPanel.vue';createApp(Panel,{nodes:[{id:1,name:'边缘节点',interfaces:{eth0:{}}}]}).mount('#app');`;},
 configureServer(s){s.middlewares.use((req,res,next)=>{if(req.url!=='/alerts-fixture')return next();res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Alerts isolated acceptance</title><style>body{margin:0;padding:12px;background:#191817}#app{max-width:1100px;margin:auto}</style><div id="app"></div><script type="module" src="/alerts-entry.js"></script></html>');});}
 }],server:{host:'127.0.0.1',port:0,proxy:{},strictPort:true}});
await server.listen();
const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const errors=[],expectedNetworkErrors=[],requests=[],screens=[],checks=[];
const now='2026-10-16T00:00:00Z';
function rules(){return [{id:7,revision:2,node_id:1,label:'十月出口流量',condition:{metric:'network.volume',direction:'out',interface:'eth0',threshold:'9007199254740993',window:{kind:'fixed',start:'2026-10-01T00:00:00.123456Z',end:'2026-10-31T00:00:00.654321Z',timezone:'Asia/Shanghai'}},severity:'warning',debounce:2,repeat_minutes:0,email:false,enabled:true,state:'ok',preview:{value:'12000000000',lower:'12000000000',upper:'12000000000',quality:'valid',reason:'',watermark:'2026-10-15T23:00:00Z',unit:'byte',bad:false},evaluated_at:'2026-10-15T23:00:00Z'}];}
try{
 for(const width of [1280,390,320]){
  const context=await browser.newContext({viewport:{width,height:900},timezoneId:'Asia/Shanghai',locale:'zh-CN',isMobile:width<500,hasTouch:width<500});
  const page=await context.newPage();let stored=rules(),failSave=false;
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'){if(m.text().includes('status of 422')&&m.location().url===origin+'/alerts/v2/rules/7')expectedNetworkErrors.push(m.text());else errors.push(m.text());}});
  await page.clock.install({time:new Date(now)});
  await page.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());if(url.origin!==origin){errors.push('blocked external '+req.url());return route.abort();}
   if(url.pathname.startsWith('/alerts/')){
    requests.push({width,path:url.pathname,method:req.method(),body:req.postDataJSON()});
    if(url.pathname==='/alerts/v2/preview')return route.fulfill({json:{value:null,lower:null,upper:null,quality:'unknown',reason:'history_missing',unit:'byte',watermark:null,bad:null}});
    if(url.pathname==='/alerts/v2/rules'&&req.method()==='GET')return route.fulfill({json:stored});
    if(url.pathname==='/alerts/v2/rules/7'&&req.method()==='PUT'){
     if(failSave)return route.fulfill({status:422,json:{detail:'保存失败，请核对日期喵~'}});
     stored=[{...stored[0],...req.postDataJSON(),revision:stored[0].revision+1}];return route.fulfill({json:{id:7,revision:stored[0].revision}});
    }
    errors.push('unhandled fixture API '+req.method()+' '+url.pathname);return route.abort();
   }
   return route.continue();
  });
  await page.goto(origin+'/alerts-fixture');
  await expect(page.locator('.current-status')).toContainText('数据已过期');
  await expect(page.locator('.last-observation')).toContainText('12000000000 byte');
  const historyRows=await page.locator('.last-observation').evaluate(el=>[...el.children].map(c=>({top:c.getBoundingClientRect().top,bottom:c.getBoundingClientRect().bottom})));
  expect(historyRows[1].top).toBeGreaterThanOrEqual(historyRows[0].bottom);
  await page.getByRole('button',{name:'编辑',exact:true}).click();
  const dates=page.locator('input[type="datetime-local"]');await expect(dates).toHaveCount(2);
  await expect(dates.nth(0)).toHaveValue('2026-10-01T08:00:00.123');
  await expect(page.locator('[data-zone]')).toHaveValue('Asia/Shanghai');
  const save=page.getByRole('button',{name:'保存规则',exact:true});
  await save.focus();await page.keyboard.press('Tab');await expect(page.locator('form select').nth(1)).toBeFocused();
  await page.keyboard.press('Shift+Tab');await expect(save).toBeFocused();
  await page.getByRole('button',{name:'只读预览',exact:true}).click();await expect(page.locator('.preview')).toContainText('所选范围没有可用历史');
  // Real keyboard Escape after a temporarily disabled async preview button.
  await page.keyboard.press('Escape');await expect(page.locator('form')).toHaveCount(0);await expect(page.getByRole('button',{name:'编辑',exact:true})).toBeFocused();
  await page.getByRole('button',{name:'编辑',exact:true}).click();
  await page.locator('[data-zone]').selectOption('America/New_York');await expect(dates.nth(0)).toHaveValue('2026-09-30T20:00:00.123');
  await dates.nth(0).fill('2026-10-02T10:11:12.345');
  failSave=true;await save.click();await expect(page.locator('form [role="alert"]')).toContainText('草稿已保留');await expect(dates.nth(0)).toHaveValue('2026-10-02T10:11:12.345');
  failSave=false;await save.click();await expect(page.locator('form')).toHaveCount(0);
  expect(stored[0].condition.window.start).toBe('2026-10-02T14:11:12.345Z');expect(stored[0].condition.window.end).toBe('2026-10-31T00:00:00.654321Z');expect(stored[0].condition.threshold).toBe('9007199254740993');
  await page.getByRole('button',{name:'编辑',exact:true}).click();await expect(dates.nth(0)).toHaveValue('2026-10-02T10:11:12.345');
  await page.locator('[data-zone]').selectOption('Asia/Shanghai');
  await page.getByRole('button',{name:'只读预览',exact:true}).click();await expect(page.locator('.preview')).toContainText('所选范围没有可用历史');
  const geometry=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('fieldset,input,select,.actual-window,.preview')].filter(el=>{const r=el.getBoundingClientRect();return r.right>innerWidth||r.left<0||el.scrollWidth>el.clientWidth+2;}).map(el=>({tag:el.tagName,cls:el.className,width:el.clientWidth,scroll:el.scrollWidth}))}));
  checks.push({width,geometry});
  const parentOverflow=await page.locator('fieldset input,fieldset select').evaluateAll(els=>els.filter(el=>el.getBoundingClientRect().right>el.closest('fieldset').getBoundingClientRect().right-8).map(el=>({type:el.type,right:el.getBoundingClientRect().right,parentRight:el.closest('fieldset').getBoundingClientRect().right})));
  expect(parentOverflow).toEqual([]);
  await page.screenshot({path:`${out}/window-${width}.png`,fullPage:true});screens.push(`window-${width}.png`);
  expect(geometry.document).toBeLessThanOrEqual(width);expect(geometry.overflow).toEqual([]);
  await dates.nth(0).evaluate(el=>el.scrollIntoView({block:'start'}));await page.screenshot({path:`${out}/window-fields-${width}.png`});screens.push(`window-fields-${width}.png`);
  if(width===1280){
   await page.locator('[data-zone]').selectOption('America/New_York');await dates.nth(1).fill('2026-11-02T01:30');await dates.nth(0).fill('2026-11-01T01:30');
   await expect(save).toBeDisabled();await page.locator('[data-fold="start"]').selectOption('2026-11-01T06:30:00.000Z');await expect(save).toBeEnabled();
   await page.screenshot({path:`${out}/dst-fold-desktop.png`,fullPage:true});screens.push('dst-fold-desktop.png');
   await dates.nth(0).fill('2026-03-08T02:30');await expect(page.locator('#window-error')).toContainText('不存在');await expect(save).toBeDisabled();
  }
  await context.close();
 }
 expect(errors).toEqual([]);expect(expectedNetworkErrors).toHaveLength(3);expect(await hashes()).toEqual(before);
 await writeFile(`${out}/browser-result.json`,JSON.stringify({fixture:'real Vue component / synthetic in-memory API; not PG or full App',hashes:before,checks,screens,requests,errors,expectedNetworkErrors,passed:true},null,2));
 console.log(JSON.stringify({passed:true,screens,checks,errors}));
}catch(e){await writeFile(`${out}/browser-failure.json`,JSON.stringify({error:String(e),checks,errors,requests,hashes:before},null,2));throw e;}
finally{await browser.close();await server.close();}
