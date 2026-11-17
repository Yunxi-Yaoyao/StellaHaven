// Real Vue/browser geometry and interactions; API responses intentionally synthetic.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium,expect} from '@playwright/test';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
const out=process.env.WG13_EVIDENCE;if(!out)throw Error('WG13_EVIDENCE required');
await mkdir(out,{recursive:true});
const work=await mkdtemp(resolve(process.env.TMPDIR||'/root/.hermes/cache/scratch','wg13-browser-'));
const server=await createServer({root:process.cwd(),configFile:false,envDir:false,cacheDir:resolve(work,'vite'),
 optimizeDeps:{entries:[],include:['vue','vue-router']},plugins:[vue(),{
 name:'manual-wg-fixture',enforce:'pre',
 resolveId(id){if(id==='/wg13-entry.js')return '\0wg13-entry';if(/\/home\/auth(?:\.ts)?(?:\?.*)?$/.test(id))return '\0wg13-auth';},
 load(id){if(id==='\0wg13-auth')return `import {ref} from 'vue';export const loggedIn=ref(true);export const auth={me:{id:'fixture'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false};export const refreshAccess=async()=>false;`;
 if(id==='\0wg13-entry')return `import {createApp,h} from 'vue';import {createRouter,createWebHistory} from 'vue-router';import '@fontsource-variable/inter';import '/src/style.css';import Alerts from '/src/modules/servers/AlertsView.vue';const router=createRouter({history:createWebHistory(),routes:[{path:'/:pathMatch(.*)*',component:Alerts}]});createApp({render:()=>h(Alerts)}).use(router).mount('#app');`;},
 configureServer(s){s.middlewares.use((req,res,next)=>{if(!req.url?.startsWith('/fixture'))return next();res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body,#app{height:100%;margin:0}#app{display:flex;background:#191b20;min-width:0}</style><div id="app"></div><script type="module" src="/wg13-entry.js"></script></html>');});}
 }],server:{host:'127.0.0.1',port:0,strictPort:true}});
await server.listen();const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const checks=[],errors=[];
try{
 for(const width of [1440,390,320]){
  const context=await browser.newContext({viewport:{width,height:900},locale:'zh-CN'});const page=await context.newPage();
  let saved=false;const calls=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url());if(u.origin!==origin)return route.abort();
   if(!/^\/(alerts|nodes|monitors|notifications)(\/|\?|$)/.test(u.pathname))return route.continue();
   let body=[];
   if(u.pathname==='/nodes/')body=[{id:12,name:'合成源节点',status:'online'}];
   else if(u.pathname.includes('map-topology'))body={links:[]};
   else if(u.pathname.startsWith('/alerts/incidents'))body={items:[],total:0,limit:30,offset:0};
   else if(u.pathname==='/alerts/rules'){
    if(req.method()==='POST'){calls.push(req.postDataJSON());saved=true;body={id:1};}
    else body=saved?[{id:1,kind:'wg_link',target:'manual:synthetic',label:'合成源节点 · wg-real → 10.42.0.2',severity:'warning',state:'ok',enabled:true,email:false,debounce:2,repeat_minutes:30,wg_manual:{node_id:12,interface:'wg-real',target:'10.42.0.2'},wg_observation:{health:'unknown',reason:'missing_or_expired_probe',checked_at:null}}]:[];
   }
   return route.fulfill({json:body});
  });
  await page.goto(origin+'/fixture');await page.getByRole('button',{name:'添加告警',exact:true}).click();await page.getByRole('button',{name:'WG 链路中断',exact:true}).click();
  await page.getByLabel('WG 目标来源',{exact:true}).selectOption('manual');await page.getByLabel('WG 源节点',{exact:true}).selectOption('12');
  await page.getByLabel('本地 WG 接口',{exact:true}).fill('wg-real');await page.getByLabel('目标 WG IPv4',{exact:true}).fill('10.42.0.2');
  await page.getByRole('button',{name:'添加',exact:true}).scrollIntoViewIfNeeded();
  const geometry=await page.evaluate(()=>{const v=document.querySelector('.alerts-view');return {doc:document.documentElement.scrollWidth,view:v.clientWidth,scroll:v.scrollWidth,bad:[...document.querySelectorAll('.wg-field input,.wg-field select')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.left<0||r.right>innerWidth+1)}).length}});
  expect(geometry.doc).toBeLessThanOrEqual(width);expect(geometry.scroll).toBeLessThanOrEqual(geometry.view+1);expect(geometry.bad).toBe(0);
  await page.screenshot({path:resolve(out,`manual-form-${width}.png`)});
  await page.getByRole('button',{name:'添加',exact:true}).click();await expect(page.locator('.rule-meta').first()).toContainText('手动单向');
  expect(calls[0]).toMatchObject({kind:'wg_link',target:'',wg_manual:{node_id:12,interface:'wg-real',target:'10.42.0.2'}});
  await expect(page.locator('.state-dot')).toHaveClass(/unknown/);
  await page.screenshot({path:resolve(out,`manual-unknown-${width}.png`)});
  checks.push({width,geometry,payload:calls[0]});await context.close();
 }
 expect(errors).toEqual([]);await writeFile(resolve(out,'browser-result.json'),JSON.stringify({passed:true,boundary:'Actual Vue + Chromium, explicitly synthetic API; not live agent or full application acceptance',checks,errors},null,2));
 console.log(JSON.stringify({passed:true,checks,errors}));
}finally{await browser.close();await server.close();await rm(work,{recursive:true,force:true});}
