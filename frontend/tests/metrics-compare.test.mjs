import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';

test('Prometheus comparison is explicit, shows real cadence and never claims equivalence', async t => {
 const server=await createServer({configFile:false,appType:'custom',plugins:[vue()],server:{host:'127.0.0.1',port:0},logLevel:'error'});
 server.middlewares.use('/__metrics_test',async(req,res,next)=>{try{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/__metrics_test',`<div id="app"></div><script type="module">import{createApp,h}from'vue';import MetricsCompare from '/src/modules/servers/MetricsCompare.vue';createApp({render:()=>h(MetricsCompare,{nodeId:19,nodeName:'Stella'})}).mount('#app')</script>`));}catch(e){next(e)}});
 await server.listen();t.after(()=>server.close());
 const browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox'],headless:true});t.after(()=>browser.close());const page=await browser.newPage();page.setDefaultTimeout(5000);
 let writes=0,reads=0;let config={enabled:true,url:'http://monitor.example:9090',nodes:{'19':{job:'node',instance:'server:9100'},'20':{job:'hk',instance:'hk:9100'}}};
 await page.route('**/config/prometheus',async route=>{if(route.request().method()==='PUT'){writes++;config=route.request().postDataJSON();}return route.fulfill({json:config});});
 await page.route('**/nodes/19/metrics-comparison',route=>{reads++;return route.fulfill({json:{nodeId:19,legacy:{latestSys:{cpuPct:10,memoryPct:50,diskPct:40,timestamp:1700000000},trafficIntervalSeconds:5,expectedSysIntervalSeconds:60},prometheus:{snapshot:{freshness:'up',cpuPct:{value:11},memoryPct:{value:51},filesystems:[{mountpoint:'/',usedPct:{value:41}}],networks:[]},sampleSpacing:{spacingSeconds:[15,15,15]}},equivalence:{status:'not_equivalent',reason:'sample_spacing_not_5s',cadenceMatches:false}}});});
 await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/__metrics_test`,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'开始对账',exact:true}).waitFor();assert.equal(writes,0);assert.equal(reads,0);
 await page.getByRole('button',{name:'开始对账',exact:true}).click();await page.getByText('15 秒',{exact:false}).waitFor();
 assert.match(await page.locator('body').innerText(),/尚未对齐/);assert.equal(writes,0);assert.equal(reads,1);
 await page.getByLabel('Prometheus 地址').fill('http://new-monitor.example:9090');await page.getByRole('button',{name:'保存对账配置',exact:true}).click();await page.getByText('对账配置已保存',{exact:false}).waitFor();
 assert.equal(writes,1);assert.deepEqual(config.nodes['20'],{job:'hk',instance:'hk:9100'});
});
