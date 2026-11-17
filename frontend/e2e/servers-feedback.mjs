// Offline component/geometry acceptance. Every application HTTP call is intercepted.
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from 'playwright';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=process.cwd(), out=process.env.STELLA_QA_OUTPUT;
assert(out,'STELLA_QA_OUTPUT required'); await mkdir(out,{recursive:true});
const cache=await mkdtemp(path.join(tmpdir(),'servers-feedback-vite-'));
const html=`<html lang="zh-CN"><meta name="viewport" content="width=device-width, initial-scale=1"><div id="app"></div><script type="module">
import {createApp,h} from 'vue';
import {createRouter,createWebHistory,RouterView} from 'vue-router';
import Page from '/src/modules/servers/ServersPage.vue';
import Home from '/src/modules/servers/ServersHome.vue';
import '/src/style.css';
const router=createRouter({history:createWebHistory(),routes:[{path:'/status',component:Page,children:[{path:'',component:Home}]}]});
createApp({render:()=>h(RouterView)}).use(router).mount('#app');
</script><style>html,body,#app{height:100%;margin:0;overflow:hidden}#app{display:block;padding:0;background:#16191e}</style></html>`;
const server=await createServer({root,configFile:false,appType:'custom',cacheDir:cache,plugins:[vue()],optimizeDeps:{entries:[],include:['vue','vue-router','echarts/core','echarts/charts','echarts/components','echarts/renderers']},server:{host:'127.0.0.1',port:0},});
server.middlewares.use(async(req,res,next)=>{if(req.url?.startsWith('/status')){res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/index.html',html));}else next();});
await server.listen(); const base=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const nodes=[1,2].map(id=>({id,name:`节点 ${id}`,status:'online',platform:'linux',net_type:'public',interfaces:{}}));
let tasks=[],posts=0,groups=[],groupWrites=0;const stamp=new Date().toISOString();
const history=Array.from({length:65},(_,i)=>({id:200-i,node_id:1,target:`manual-${i}.example.invalid`,protocol:'icmp',trigger:'manual',status:'done',created_at:stamp,params_json:{count:10},result_json:{hubs:[{host:'192.0.2.1',loss:0,avg:3.2}]}}));
const monitors=[1,2,3].map(id=>({id,name:`监控 ${id}`,node_id:id===2?2:1,type:id===2?'tcp':'ping',target:'example.invalid',status:id===2?'down':'up',interval:60,timeout:5,last_check_at:stamp,last_latency_ms:12.3}));
const errors=[],geometry=[];
try{
 const page=await browser.newPage(); page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error'||m.type()==='warning')console.log('browser',m.type(),m.text());});
 page.on('requestfailed',r=>console.log('requestfailed',r.url(),r.failure()));
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url()), p=u.pathname.replace(/\/$/,'');
  if(u.origin!==base) return route.abort();
  let data;
  if(p==='/nodes')data=nodes;
  else if(/^\/nodes\/\d+$/.test(p))data={...nodes[0],latest_metrics:[]};
  else if(p==='/iperf-tasks'||p==='/commands')data=[];
  else if(p==='/mtr-tasks')data=[...tasks,...history];
  else if(p==='/mtr-jobs'){
   posts++;const body=route.request().postDataJSON();tasks=body.node_ids.map((id,i)=>({id:500+i,job_id:'fixture-job',node_id:id,target:body.target,protocol:body.protocol,params_json:body.params,trigger:'manual',status:'running',created_at:stamp,live_json:{hops:[{hop:1,host:'192.0.2.1',loss:0,snt:1,avg:3.2}]}}));data=tasks;
  } else if(/^\/mtr-tasks\/\d+$/.test(p))data=tasks.find(t=>t.id===Number(p.split('/').at(-1)));
  else if(p==='/monitors')data=monitors;
  else if(p==='/monitors/groups'){
   if(route.request().method()==='POST'){groupWrites++;const body=route.request().postDataJSON();groups=[{...body,id:1,status:'down',down_count:1,unknown_count:0}];data=groups[0];}else data=groups;
  }else if(p==='/monitors/groups/1'&&route.request().method()==='DELETE'){groups=[];return route.fulfill({status:204});}
  else if(/\/series$/.test(p)) data=Array.from({length:12},(_,i)=>({ts:new Date(Date.now()-(12-i)*300000).toISOString(),success:i!==4,latency_ms:10+i,loss_pct:i===4?6.7:0}));
  else if(p==='/nodes/map-topology')data={nodes:[],links:[]};
  if(data!==undefined)return route.fulfill({json:data});
  if(p.startsWith('/auth')||p.startsWith('/api')||p.startsWith('/nodes')||p.startsWith('/monitors'))return route.fulfill({status:501,json:{detail:'No fixture for '+p}});
  return route.continue();
 });
 for(const width of [1280,390]){
  await page.setViewportSize({width,height:800});
  await page.goto(base+'/status?view=tools&tool=records');await page.screenshot({path:path.join(out,'loaded.png')});await page.locator('.rec-row').first().waitFor();
  const g=await page.locator('.rec-page').evaluate(el=>({client:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY,width:el.clientWidth,scrollWidth:el.scrollWidth}));geometry.push({view:'records',width,...g});
  await page.screenshot({path:path.join(out,`records-${width}.png`)});
  assert(g.scroll>g.client && ['auto','scroll'].includes(g.overflow),'Records must own a real bounded scroll container');
  assert(g.scrollWidth<=g.width+1,'records page must not overflow horizontally');
 }
 await page.setViewportSize({width:1280,height:800});await page.goto(base+'/status?view=tools&tool=mtr');await page.locator('input[placeholder="如 8.8.8.8 或 example.com"]').fill('example.invalid');
 await page.locator('.mtr-nodes input[value="2"]').check();await page.getByRole('button',{name:'开始 MTR',exact:true}).click();
 await page.locator('.mtr-live').waitFor();assert.equal(posts,1);await page.getByRole('button',{name:'下一个节点'}).click();await page.locator('.mtr-node-result').filter({hasText:'节点 2'}).waitFor();
 await page.waitForFunction(()=>{const el=document.querySelector('.mtr-node-result');return el&&getComputedStyle(el).opacity==='1'&&!el.className.includes('enter');});
 await page.screenshot({path:path.join(out,'mtr-running-1280.png')});
 tasks=tasks.map(t=>({...t,status:'done',result_json:{hubs:[{host:'192.0.2.1',loss:0,avg:3.2}]}}));
 await page.getByRole('button',{name:'开始 MTR',exact:true}).waitFor({timeout:10000});
 assert.equal(await page.locator('input[placeholder="如 8.8.8.8 或 example.com"]').inputValue(),'example.invalid');assert.equal(posts,1);
 await page.setViewportSize({width:390,height:800});await page.screenshot({path:path.join(out,'mtr-done-390.png')});
 await page.goto(base+'/status?view=overview');await page.locator('.mon-card').first().waitFor();
 const cards=await page.locator('.mon-card').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect(),spark=el.querySelector('.spark')?.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,spark:spark?.width};}));geometry.push({view:'overview',cards});
 await page.locator('.mon-grid').screenshot({path:path.join(out,'overview-390.png')});
 assert.equal(cards.length,3);assert(cards[1].y>cards[0].y && cards[2].y>cards[1].y,'monitor cards must stack vertically');
 await page.setViewportSize({width:1280,height:900});await page.locator('.mon-grid').screenshot({path:path.join(out,'overview-1280.png')});
 const wide=await page.locator('.mon-card').evaluateAll(els=>els.map(el=>({x:el.getBoundingClientRect().x,y:el.getBoundingClientRect().y,width:el.getBoundingClientRect().width,spark:el.querySelector('.spark')?.getBoundingClientRect().width})));
 geometry.push({view:'overview-wide',cards:wide});assert(wide[1].y>wide[0].y,'desktop cards must stack');assert(wide.every(c=>c.spark>c.width-45),'charts must fill card width');
 const canvasWidths=await page.locator('.spark').evaluateAll(els=>els.map(el=>({container:el.getBoundingClientRect().width,canvas:el.querySelector('canvas')?.getBoundingClientRect().width??0})));
 assert(canvasWidths.every(c=>Math.abs(c.canvas-c.container)<2),'actual chart canvases must resize to the full container, not just CSS boxes');
 await page.getByRole('button',{name:'父子监控',exact:true}).click();await page.getByRole('dialog').waitFor();
 await page.getByRole('dialog').locator('input[maxlength="64"]').fill('固定父监控');
 await page.getByRole('dialog').locator('input[type="checkbox"][value="1"]').check();await page.getByRole('dialog').locator('input[type="checkbox"][value="2"]').check();
 await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
 await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===2);
 assert.equal(groupWrites,1);assert.equal(posts,1);
 const parent=page.locator('.mon-card').filter({has:page.locator('.mon-name',{hasText:'固定父监控'})});
 assert((await parent.textContent()).includes('1 项异常'));await parent.locator('button[data-child-id="2"]').click();
 await page.waitForFunction(()=>document.querySelector('.mon-card .mon-target')?.textContent?.includes('tcp'));
 await page.locator('.mon-grid').screenshot({path:path.join(out,'grouped-1280.png')});
 assert.equal(await parent.locator('.mon-name').textContent(),'固定父监控');assert((await parent.textContent()).includes('1 项异常'));
 await page.setViewportSize({width:390,height:800});await page.locator('.mon-grid').screenshot({path:path.join(out,'grouped-390.png')});
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',posts,groupWrites,geometry,errors},null,2));
}finally{await writeFile(path.join(out,'geometry.json'),JSON.stringify({geometry,errors},null,2));await browser.close();await server.close();await rm(cache,{recursive:true,force:true});}
