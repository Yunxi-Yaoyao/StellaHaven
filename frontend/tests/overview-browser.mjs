// Isolated, read-only browser regression using actual product SFC, chart runtime and styles.
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
const root = new URL('../', import.meta.url).pathname;
const output = process.env.OVERVIEW_EVIDENCE_DIR || '/opt/hermes-workstation/docs/stella-overview-time-20261011/overview';
await mkdir(output,{recursive:true});
const sourcePaths=['src/modules/servers/OverviewView.vue','src/modules/servers/interfaceSelection.ts','src/modules/servers/chartRuntime.ts','src/style.css','tests/overview-browser.mjs'];
const hashes=async()=>Object.fromEntries(await Promise.all(sourcePaths.map(async path=>[path,createHash('sha256').update(await readFile(root+path)).digest('hex')])));
const before=await hashes();
const entry=`import {createApp,h,ref} from 'vue';
import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import '@fontsource-variable/inter'; import '/src/style.css';
import ServersHome from '/src/modules/servers/ServersHome.vue';
import * as runtime from '/src/modules/servers/chartRuntime.ts';
localStorage.setItem('stella_server_world_map_collapsed','1');
const shown=ref(false);window.overviewReveal=()=>shown.value=true;
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/status',component:ServersHome},{path:'/away',component:{render:()=>h('div','away')}}]});
window.overviewRouter=router;window.overviewRuntime=runtime;
await router.push('/status?view=overview');await router.isReady();
createApp({render:()=>h('main',{style:{display:shown.value?'block':'none',height:'100vh',width:'100%'}},h(RouterView))}).use(router).mount('#app');`;
const server=await createServer({root,configFile:false,cacheDir:root+'node_modules/.tmp/overview-browser-vite',plugins:[vue(),{name:'overview-fixture',resolveId(id){if(id==='/overview-fixture-entry')return '\0overview-entry';},load(id){if(id==='\0overview-entry')return entry;},configureServer(s){s.middlewares.use((req,res,next)=>{if(req.url==='/overview-fixture'){res.setHeader('Content-Type','text/html');res.end('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div><script type="module" src="/overview-fixture-entry"></script></body></html>');}else next();});}}],server:{host:'127.0.0.1',port:0,proxy:{}}});
await server.listen();
const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || '/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
const report={commit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--short'],{cwd:root,encoding:'utf8'}).trim(),sourceHashes:before,fixture:'Actual ServersHome/Overview/Dropdown/ServerWorldMap, chartRuntime and styles. GET-only fixture APIs; no production API or auth writes.',runs:[]};
try{
 for(const width of [1280,390]){
  const context=await browser.newContext({viewport:{width,height:900},deviceScaleFactor:1});
  const page=await context.newPage();const errors=[];const expectedHttpFailures=[];const requests=[];let mode='normal';
  page.on('pageerror',e=>errors.push(e.stack||String(e)));
  page.on('console',m=>{if(m.type()==='error'){if(mode==='error'&&m.text()==='Failed to load resource: the server responded with a status of 503 (Service Unavailable)')expectedHttpFailures.push(m.text());else errors.push(m.text());}});
  const nodes=[{id:54,name:'Stella',status:'online',platform:'Linux'},{id:57,name:'5060',status:'online',platform:'Windows'},{id:60,name:'NAS',status:'online',platform:'Linux'}];
  const iface=id=>id===57?'WLAN':id===60?'enp1s0':'eth0';
  await context.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.origin!==origin){await route.abort();throw Error('External origin forbidden: '+u.origin);}
   if(route.request().method()!=='GET'){await route.abort();throw Error('Write forbidden');}
   let body;
   if(u.pathname==='/nodes/'){await new Promise(r=>setTimeout(r,200));body=nodes;}
   else if(u.pathname==='/monitors/')body=[];
   else if(u.pathname==='/nodes/map-topology')body={generated_at:new Date().toISOString(),nodes:[],links:[],stats:{located:0,unknown:0,links:0}};
   else if(/^\/nodes\/\d+$/.test(u.pathname)){
    const id=Number(u.pathname.split('/')[2]);await new Promise(r=>setTimeout(r,id===57?500:250));
    const interfaces={[iface(id)]:{up:true,is_physical:id!==57,is_default:id!==57},lo:{up:true,is_physical:false},docker0:{up:true,is_physical:false},wg0:{up:true,is_physical:false}};
    body={...nodes.find(n=>n.id===id),interfaces,monitored_ifaces:id===60?{missing:{},enp1s0:{}}:null,latest_metrics:[{iface:iface(id),ts:new Date().toISOString(),rx_delta:6000,tx_delta:1000}],latest_sys_metric:{cpu_pct:12,mem_pct:35}};
   }else if(/^\/nodes\/\d+\/metrics$/.test(u.pathname)){
    const id=Number(u.pathname.split('/')[2]);const selected=u.searchParams.get('iface');requests.push({id,iface:selected,start:u.searchParams.get('start'),limit:u.searchParams.get('limit'),mode});
    assert.equal(selected,iface(id));
    if(mode==='error'){await route.fulfill({status:503,contentType:'application/json',body:'{"detail":"fixture unavailable"}'});return;}
    const end=Date.now();body=mode==='empty'?[]:Array.from({length:54},(_,i)=>({iface:selected,ts:new Date(end-i*5000).toISOString(),rx_delta:mode==='zero'?0:62500+(i%10)*32500,tx_delta:mode==='zero'?0:12000+(i%7)*6000}));
   }
   if(body!==undefined)await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});else await route.continue();
  });
  await page.goto(origin+'/overview-fixture');
  await page.waitForFunction(()=>document.querySelector('.traffic-hint')?.textContent.includes('节点加载中'));
  await page.waitForFunction(()=>document.querySelector('.ov-chart'));
  await page.waitForFunction(()=>document.querySelector('.srv-card')?.textContent.includes('CPU'));
  // Let the first full response land while an ancestor is display:none.
  await page.waitForFunction(()=>window.overviewRuntime && !document.querySelector('.traffic-hint'));
  assert.equal(await page.locator('.ov-chart canvas').count(),0);
  await page.evaluate(()=>window.overviewReveal());
  await page.waitForFunction(()=>document.querySelector('.ov-chart canvas')?.width>0);
  const inspect=()=>page.evaluate(()=>{
   const el=document.querySelector('.ov-chart');const chart=window.overviewRuntime.getInstanceByDom(el);const option=chart.getOption();const canvas=el.querySelector('canvas');
   const rect=el.getBoundingClientRect();const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;let blue=0,pink=0;
   for(let i=0;i<pixels.length;i+=4){if(pixels[i+3]>60&&pixels[i+2]>pixels[i]+20&&pixels[i+1]>100)blue++;if(pixels[i+3]>60&&pixels[i]>180&&pixels[i+2]>120&&pixels[i+1]<190)pink++;}
   return {width:rect.width,height:rect.height,canvasWidth:canvas.width,canvasHeight:canvas.height,points:option.series.map(s=>s.data.length),first:option.series[0].data[0],blue,pink,scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,hint:document.querySelector('.traffic-hint')?.textContent||''};
  });
  const capture=async label=>{const metrics=await inspect();assert(metrics.width>0&&metrics.canvasWidth>0);assert.deepEqual(metrics.points,[54,54]);assert(metrics.scrollWidth<=width);await page.locator('.overview').screenshot({path:`${output}/${width}-${label}.png`});return metrics;};
  const run={width,normal:await capture('stella'),requests,errors,expectedHttpFailures};
  assert(run.normal.blue>100&&run.normal.pink>100);
  const selectNode=async name=>{await page.locator('.ov-drop:not(.iface-drop) .dd-btn').click();await page.locator('.ov-drop:not(.iface-drop) .dd-item').filter({hasText:name}).click();};
  await selectNode('5060');await page.waitForFunction(()=>document.querySelector('.iface-drop .dd-label')?.textContent==='WLAN');
  await page.waitForFunction(()=>window.overviewRuntime.getInstanceByDom(document.querySelector('.ov-chart'))?.getOption().series[0].data.length===54&&!document.querySelector('.traffic-hint'));
  run.windows=await capture('5060');assert(requests.some(r=>r.id===57&&r.iface==='WLAN'));
  await selectNode('NAS');await page.waitForFunction(()=>document.querySelector('.iface-drop .dd-label')?.textContent==='enp1s0（默认）');
  await page.waitForFunction(()=>!document.querySelector('.traffic-hint'));run.nas=await capture('nas');
  mode='error';await page.waitForFunction(()=>document.querySelector('.traffic-hint')?.textContent.includes('流量加载失败'));
  run.error=await capture('error-retained');assert(run.error.blue>100);
  mode='empty';await page.locator('.traffic-retry').click();await page.waitForFunction(()=>document.querySelector('.traffic-hint')?.textContent.includes('暂无流量数据'));
  run.empty=await inspect();assert.deepEqual(run.empty.points,[0,0]);await page.locator('.overview').screenshot({path:`${output}/${width}-empty.png`});
  mode='zero';await selectNode('5060');await page.waitForFunction(()=>!document.querySelector('.traffic-hint'));run.zero=await capture('zero');assert.equal(run.zero.first,0);
  // RO handles container-only resize, without dispatching window.resize.
  await page.evaluate(()=>document.querySelector('main').style.width='80%');await page.waitForFunction(()=>{const el=document.querySelector('.ov-chart');return Math.abs(el.querySelector('canvas').width-el.getBoundingClientRect().width)<2;});
  run.resized=await inspect();assert(run.resized.canvasWidth<run.zero.canvasWidth);
  await page.evaluate(()=>window.overviewRouter.push('/away'));await page.waitForFunction(()=>!document.querySelector('.overview'));
  const count=requests.length;await page.waitForTimeout(3300);assert.equal(requests.length,count);
  assert.deepEqual(errors,[]);report.runs.push(run);await context.close();
 }
 assert.deepEqual(await hashes(),before);
 await writeFile(`${output}/browser-report.json`,JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));
}finally{await browser.close();await server.close();}
