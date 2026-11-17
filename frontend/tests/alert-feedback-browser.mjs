// Real owned PostgreSQL + real alert routes, auth-boundary stub (not full App login).
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
const root=process.cwd(),repo=resolve(root,'..');
const out=process.env.ALERT_FEEDBACK_EVIDENCE||resolve(repo,'remediation/alert-feedback-evidence');
const scratch=process.env.TMPDIR||'/root/.hermes/cache/scratch';
await mkdir(out,{recursive:true});
const work=await mkdtemp(resolve(scratch,'alert-feedback-browser-'));
const env={...process.env,PYTHONPATH:repo};
for(const key of Object.keys(env))if(/^(HERMES_(WORKER|BROKER|BRIDGE|MCP)|UV_PROJECT_ENVIRONMENT$|VIRTUAL_ENV$|NODE_ENV$)/.test(key))delete env[key];
const backend=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'tests_alert_feedback/browser_fixture.py')],{cwd:work,env,stdio:['ignore','pipe','pipe']});
let backendLog='';backend.stderr.on('data',d=>backendLog+=d);
const lines=createInterface({input:backend.stdout});
const config=await Promise.race([(async()=>{for await(const l of lines){try{const v=JSON.parse(l);if(v.port)return v;}catch{}}throw Error('backend exited '+backendLog);})(),new Promise((_,rej)=>setTimeout(()=>rej(Error('backend startup timeout '+backendLog)),20000).unref())]);
const target=`http://127.0.0.1:${config.port}`;
const server=await createServer({root,configFile:false,envDir:false,cacheDir:resolve(work,'vite-cache'),optimizeDeps:{entries:[],include:['vue','vue-router']},plugins:[vue(),{
 name:'alert-feedback-owned-browser',enforce:'pre',
 resolveId(id){if(id==='/feedback-entry.js')return '\0feedback-entry';if(/\/home\/auth(?:\.ts)?(?:\?.*)?$/.test(id))return '\0fixture-auth';},
 load(id){if(id==='\0fixture-auth')return `import {ref} from 'vue';export const loggedIn=ref(true);export const auth={me:{id:'fixture-owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false};export const refreshAccess=async()=>false;`;
 if(id==='\0feedback-entry')return `import {createApp,h} from 'vue';import {createRouter,createWebHistory} from 'vue-router';import '@fontsource-variable/inter';import '/src/style.css';import Alerts from '/src/modules/servers/AlertsView.vue';import Bell from '/src/shell/NotificationBell.vue';const router=createRouter({history:createWebHistory(),routes:[{path:'/:pathMatch(.*)*',component:Alerts}]});createApp({render:()=>[h('div',{class:'fixture-bar'},[h(Bell)]),h('main',[h(Alerts)])]}).use(router).mount('#app');`;},
 configureServer(s){s.middlewares.use((req,res,next)=>{if(!req.url?.startsWith('/fixture'))return next();res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stella 告警</title><style>html,body,#app{height:100%;margin:0}#app{display:flex;flex-direction:column;background:#191b20}.fixture-bar{padding:12px 22px;border-bottom:1px solid #ffffff15}main{min-height:0;flex:1;display:flex;overflow:hidden}</style><div id="app"></div><script type="module" src="/feedback-entry.js"></script></html>');});}
 }],server:{host:'127.0.0.1',port:0,proxy:Object.fromEntries(['/alerts','/notifications','/nodes','/monitors','/__fixture'].map(k=>[k,{target}])),strictPort:true}});
await server.listen();const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const errors=[],checks=[],screens=[];
try{
 for(const width of [1440,720,390,320]){
  const context=await browser.newContext({viewport:{width,height:900},timezoneId:'Asia/Shanghai',locale:'zh-CN'});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{const u=new URL(route.request().url());return u.origin===origin?route.continue():route.abort();});
  await page.goto(origin+'/fixture?view=alerts');
  await expect(page.getByRole('heading',{name:'当前告警',exact:true})).toBeVisible();
  await expect(page.locator('[aria-label="当前告警"] article')).toHaveCount(1);
  await page.screenshot({path:resolve(out,`items-${width}.png`)});screens.push(`items-${width}.png`);
  await page.getByRole('button',{name:'添加告警',exact:true}).click();
  await page.getByRole('button',{name:'累计流量',exact:true}).click();
  await expect(page.locator('.metrics-panel form')).toBeVisible();
  await expect(page.getByText('累计流量达到',{exact:true})).toBeVisible();
  await page.locator('.metrics-panel form').scrollIntoViewIfNeeded();
  const geometry=await page.evaluate(()=>{const el=document.querySelector('.alerts-view');return {width:innerWidth,doc:document.documentElement.scrollWidth,view:el.clientWidth,scroll:el.scrollWidth,scrollHeight:el.scrollHeight,height:el.clientHeight,fields:[...document.querySelectorAll('.metrics-panel input,.metrics-panel select')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.left<0||r.right>innerWidth+1);}).map(e=>e.outerHTML)};});
  expect(geometry.doc).toBeLessThanOrEqual(width);expect(geometry.scroll).toBeLessThanOrEqual(geometry.view+1);expect(geometry.fields).toEqual([]);expect(geometry.scrollHeight).toBeGreaterThan(geometry.height);
  checks.push({width,geometry});await page.screenshot({path:resolve(out,`volume-${width}.png`)});screens.push(`volume-${width}.png`);
  if(width===320){
   const form=page.locator('.metrics-panel form');await form.locator('select').nth(0).selectOption(String(config.node_id));await form.locator('select').nth(3).selectOption('eth0');
   await form.locator('[data-zone]').selectOption('UTC');await form.locator('input[inputmode=decimal]').first().fill('150');
   const dates=form.locator('input[type=datetime-local]');await dates.nth(0).fill(new Date(Date.now()-3600000).toISOString().slice(0,16));await dates.nth(1).fill(new Date(Date.now()+3600000).toISOString().slice(0,16));
   await form.getByRole('button',{name:'保存规则',exact:true}).click();await expect(form).toHaveCount(0);
   const saved=await fetch(target+'/alerts/v2/rules').then(r=>r.json());expect(saved.find(r=>r.condition?.metric==='network.volume').condition.threshold).toBe('150000000000');
  }
  await page.getByRole('button',{name:'告警记录',exact:true}).click();
  await expect(page.locator('[aria-label="告警记录"] article')).toHaveCount(2);
  await page.locator('[aria-label="告警记录"] .record-title').first().click();
  await expect(page.locator('[data-incident-detail]')).toBeVisible();
  await expect(page.locator('[data-incident-detail]')).toContainText('开始时间');
  await expect(page.locator('[data-incident-detail]')).toContainText('持续异常提醒');
  await page.screenshot({path:resolve(out,`incident-${width}.png`)});screens.push(`incident-${width}.png`);
  await page.keyboard.press('Escape');await expect(page.locator('[data-incident-detail]')).toHaveCount(0);
  const history=page.locator('[aria-label="告警记录"]');await history.locator('select').nth(2).selectOption('resolved');await history.getByRole('button',{name:'筛选',exact:true}).click();await expect(history.locator('article')).toHaveCount(1);await expect(history).toContainText('持续 10分钟');
  await page.screenshot({path:resolve(out,`history-${width}.png`)});screens.push(`history-${width}.png`);
  await page.getByRole('button',{name:'通知',exact:true}).click();
  await expect(page.locator('[data-notification-panel] .item')).toHaveCount(4);
  const pathBefore=new URL(page.url()).pathname;
  await page.locator('[data-notification-panel] .item').first().click();
  await expect(page.locator('[data-notification-detail]')).toContainText('发送时间');expect(new URL(page.url()).pathname).toBe(pathBefore);
  const link=page.locator('[data-notification-detail] a.entity');await expect(link).toHaveAttribute('href',`/status/${config.node_id}`);
  expect(await link.evaluate(el=>!!el.closest('button'))).toBe(false);
  await page.screenshot({path:resolve(out,`notification-${width}.png`)});screens.push(`notification-${width}.png`);
  if(width===390){await link.click();await expect(page).toHaveURL(new RegExp(`/status/${config.node_id}`));}
  await context.close();
 }
 const receipt=await fetch(target+'/__fixture/receipt').then(r=>r.json());expect(receipt.events).toBe(3);expect(receipt.notifications).toBe(4);expect(receipt.unread).toBe(3);expect(receipt.open_state).toBe('firing');
 expect(errors).toEqual([]);
 await writeFile(resolve(out,'result.json'),JSON.stringify({passed:true,boundary:'Owned PG + real alert routers + real Vue; explicit auth stub, not deployment or full-login acceptance',checks,screens,errors,receipt},null,2));
 console.log(JSON.stringify({passed:true,checks,screens,receipt}));
}catch(e){await writeFile(resolve(out,'failure.json'),JSON.stringify({error:String(e),checks,errors,backendLog},null,2));throw e;}
finally{await browser.close();await server.close();const cleanup=await fetch(target+'/__fixture/cleanup',{method:'POST'}).then(r=>r.json());await writeFile(resolve(out,'cleanup.json'),JSON.stringify(cleanup));backend.kill('SIGTERM');await once(backend,'exit');await rm(work,{recursive:true,force:true});expect(cleanup.remaining_tables).toBe(0);}
