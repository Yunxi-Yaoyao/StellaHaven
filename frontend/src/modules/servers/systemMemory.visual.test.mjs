// Actual NodeDetailView, PostgreSQL/readback memory, isolated API (not production).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';
const out = process.env.HARDWARE_TEST_OUTPUT;
assert.ok(out, 'HARDWARE_TEST_OUTPUT must name an isolated evidence directory');
const readback = JSON.parse(readFileSync(resolve(out, '../postgres-readback.json'), 'utf8'));
const files = ['src/modules/servers/HardwareInfoPanel.vue', 'src/modules/servers/NodeDetailView.vue', 'src/modules/servers/StoragePanel.vue', 'src/api/servers.ts', 'src/style.css', 'src/modules/servers/systemMemory.visual.test.mjs'];
const fingerprint = () => Object.fromEntries(files.map(p => [p, createHash('sha256').update(readFileSync(p)).digest('hex')]));
const before = fingerprint();
const bootstrap = `
import { createApp, h } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Detail from '/src/modules/servers/NodeDetailView.vue';
import base from '/src/modules/servers/fixtures/node-55.contract-fixture.json';
import '@fontsource-variable/inter';
import '/src/style.css';
const mode = new URLSearchParams(location.search);
const kind = mode.get('kind');
const saved = ${JSON.stringify(readback)}[kind];
const fixture = structuredClone(base);
fixture.name = 'Generic memory node';
const hw = fixture.sys_info.hardware;
hw.machine = saved.sys_info.hardware.machine;
hw.memory = saved.sys_info.hardware.memory;
const now = new Date().toISOString();
hw.sampled_at = hw.cpu.sampled_at = hw.sensors_sampled_at = now;
for (const gpu of hw.gpus) if (gpu.sampled_at) gpu.sampled_at = now;
fixture.latest_sys_metric.ts = now;
if (kind !== 'physical') {
  fixture.storage = []; // Test inventory fallback gating, not independently reported block devices.
  hw.physical_inventory = {board:{vendor:'Dell',model:'Unscoped inherited board'},bios:null,memory_modules:[],disks:[{name:'unscoped-host-disk',size_bytes:9999}]};
}
hw.platform_inventory = { board: null, bios: { vendor: 'American Megatrends Inc.', version: '5.13' }, source: 'sysfs.dmi', scope: kind === 'container' ? 'host_visible' : 'platform_reported', state: 'available', sampled_at: now };
if (kind === 'legacy') delete hw.platform_inventory;
if (kind === 'container') hw.memory.cgroup = { total_bytes: 2147483648, available_bytes: 1073741824, used_bytes: 1073741824, source: 'cgroup.v2', scope: 'cgroup', state: 'available', sampled_at: hw.memory.sampled_at };
if (mode.has('failure')) { hw.memory.state = 'query_failed'; hw.memory.sampled_at = '2000-01-01T00:00:00Z'; }
window.requests = [];
window.fetch = async (url, options={}) => {
  const path = String(url); window.requests.push({path, method:options.method || 'GET'});
  if (options.method && options.method !== 'GET') throw Error('Unexpected write: '+path);
  let data;
  if (path === '/nodes/' + fixture.id) data = fixture;
  else if (path === '/nodes/' || path === '/monitors/' || path === '/component-installs') data = [];
  else if (path === '/nodes/host') data = { installed: true };
  else if (path === '/config/public-host') data = { value: '' };
  else if (path.includes('/net-tasks/latest')) data = { created_at: now, result_json: { ufw: {}, rules: [], marks: [], tables: {} } };
  else if (path.includes('/metrics') || path.includes('/sys-metrics')) data = [];
  else if (path.includes('/traffic-stats')) data = null;
  else throw Error('Unexpected API: '+path);
  return new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}});
};
const router = createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]});
await router.push('/'); await router.isReady();
createApp({render:()=>h(Detail,{nodeId:fixture.id})}).use(router).mount('#app');
`;
const server = await createServer({ configFile:false, root:resolve('.'), cacheDir:resolve(process.env.TMPDIR, 'memory-vite'), plugins:[vue(),{
  name:'memory-qa', resolveId(id){if(id==='/memory-entry.js') return '\0memory-entry';}, load(id){if(id==='\0memory-entry')return bootstrap;},
  configureServer(s){s.middlewares.use(async(req,res,next)=>{if(!req.url?.startsWith('/memory-fixture'))return next();res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml('/memory-fixture','<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app" style="max-width:1024px;margin:auto"></div><script type="module" src="/memory-entry.js"></script></body></html>'));});}
}], server:{host:'127.0.0.1',port:0,proxy:{},hmr:false}});
let browser;
const results=[];
try {
  await mkdir(out,{recursive:true}); await server.listen();
  const origin='http://127.0.0.1:'+server.httpServer.address().port;
  browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();
  await page.clock.install({time:new Date(readback.unknown.sys_info.hardware.memory.sampled_at)});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
  for(const width of [390,1440]) for(const kind of ['physical','virtual','container','unknown','legacy']) {
    await page.setViewportSize({width,height:1000});
    await page.goto(origin+'/memory-fixture?kind='+kind);
    await page.locator('.hardware-panel').waitFor();
    if(kind==='legacy') assert.equal(await page.locator('.system-memory').count(),0);
    else {
      assert.match(await page.locator('.system-memory').textContent(),/7.6 GiB/);
      assert.match(await page.locator('.system-memory').textContent(),/可用0 B/);
      await page.locator('.system-memory').scrollIntoViewIfNeeded();
    }
    if(kind!=='physical') {
      assert.equal(await page.locator('[aria-label="物理机清单"]').count(),0);
      assert.equal(await page.locator('.physical-disk-row').count(),0);
    }
    if(kind==='unknown') {
      assert.equal(await page.locator('.d-head .machine-badge').textContent(),'未判定');
      assert.match(await page.locator('.d-head .machine-badge').getAttribute('title'),/证据不足/);
      assert.match(await page.locator('.platform-inventory').textContent(),/平台报告信息/);
    }
    if(kind==='container') assert.match(await page.locator('.system-memory').textContent(),/宿主可见.*控制组限额.*2 GiB/s);
    const bounds=await page.evaluate(()=> {
      const selectors=['.detail','.hardware-panel','.system-memory','.cgroup-memory','.memory-capacity','.platform-inventory'];
      return selectors.flatMap(selector=>[...document.querySelectorAll(selector)].map(el=>({selector,scroll:el.scrollWidth,client:el.clientWidth,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right})));
    });
    for(const b of bounds){assert.ok(b.scroll<=b.client+1,JSON.stringify(b));assert.ok(b.left>=-1&&b.right<=width+1,JSON.stringify(b));}
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const contrast = await page.evaluate(() => {
      const rgb = color => color.match(/[\d.]+/g).slice(0,3).map(Number);
      const luminance = rgb => rgb.map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v+.055)/1.055)**2.4; }).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      const bg = luminance(rgb(getComputedStyle(document.body).backgroundColor));
      return [...document.querySelectorAll('.system-memory .hardware-note, .platform-inventory .hardware-note')].map(el => {
        const fg = luminance(rgb(getComputedStyle(el).color));
        return { text: el.textContent, ratio: (Math.max(bg,fg)+.05)/(Math.min(bg,fg)+.05) };
      });
    });
    for (const item of contrast) assert.ok(item.ratio >= 4.5, JSON.stringify(item));
    assert.deepEqual(errors,[]);
    await page.screenshot({path:resolve(out,kind+'-'+width+'.png')});
    if(kind!=='legacy') await page.locator('.system-memory').screenshot({path:resolve(out,kind+'-'+width+'-memory.png')});
    results.push({width,kind,bounds,requests:await page.evaluate(()=>window.requests)});
  }
  await page.goto(origin+'/memory-fixture?kind=unknown&failure');
  await page.locator('.system-memory').waitFor();
  assert.match(await page.locator('.system-memory').textContent(),/刷新失败.*数据已过期/s);
  await page.locator('.system-memory').screenshot({path:resolve(out,'failure-memory.png')});
  results.push({kind:'failure',text:await page.locator('.system-memory').textContent()});
  assert.deepEqual(before,fingerprint()); assert.deepEqual(errors,[]);
  await writeFile(resolve(out,'results.json'),JSON.stringify({revision:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),sourceHashes:before,results,errors},null,2));
  console.log(JSON.stringify({cases:results.length,errors,out}));
} finally {await browser?.close(); await server.close();}
