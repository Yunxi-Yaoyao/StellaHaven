// Service-UID collector -> real JSONB -> NodeDetail public HTTP -> actual Vue.
// Isolated component harness; not the production page or a running-agent report.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';
const out = process.env.HARDWARE_TEST_OUTPUT;
assert.ok(out);
const input = process.env.HARDWARE_REAL_READBACK;
assert.ok(input);
const readback = JSON.parse(readFileSync(input, 'utf8'));
const actual = readback.sys_info.hardware;
assert.equal(actual.machine.kind, 'unknown');
assert.equal(actual.memory.state, 'available');
const files = ['src/modules/servers/HardwareInfoPanel.vue', 'src/api/servers.ts', 'src/style.css', 'src/modules/servers/serviceUidMemory.visual.test.mjs'];
const fingerprint = () => Object.fromEntries(files.map(p => [p, createHash('sha256').update(readFileSync(p)).digest('hex')]));
const before = fingerprint();
const bootstrap = `
import { createApp, h } from 'vue';
import Panel from '/src/modules/servers/HardwareInfoPanel.vue';
import { machineTypeLabel, machineTypeTitle } from '/src/api/servers.ts';
import '@fontsource-variable/inter';
import '/src/style.css';
const actual = ${JSON.stringify(actual)};
// Empty required presentation slots have no invented CPU/GPU measurement.
const hardware = {cpu:{},gpus:[],sensors:[],availability:{},...actual};
window.evidence = actual;
const failed = new URLSearchParams(location.search).has('failure');
if (failed) hardware.memory = {...actual.memory, state:'query_failed'};
createApp({render:()=>h('main',{style:'max-width:1024px;margin:auto;padding:16px'},[
  h('h2','NAS · 服务 UID 归档样本'),
  h('p','真实采集 → 隔离 PostgreSQL / API 回读 · 非生产页面'),
  h('p',{style:'overflow-wrap:anywhere'},'原始采样时间：' + actual.memory.sampled_at + ' · 非本次实时采样'),
  h('p',{class:'machine-badge',title:machineTypeTitle(actual.machine)},machineTypeLabel(actual.machine)),
  failed ? h('p','以下刷新失败为合成故障注入') : null,
  h(Panel,{hardware,status:'online',now:Date.parse(actual.memory.sampled_at),refreshFailed:false})
])}).mount('#app');
`;
const server = await createServer({configFile:false,root:resolve('.'),cacheDir:resolve(process.env.TMPDIR,'service-uid-memory-vite'),plugins:[vue(),{
  name:'service-uid-evidence',resolveId(id){if(id==='/service-uid-entry.js')return '\0service-uid-entry';},
  load(id){if(id==='\0service-uid-entry')return bootstrap;},
  configureServer(s){s.middlewares.use(async(req,res,next)=>{if(!req.url?.startsWith('/service-uid-fixture'))return next();res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml('/service-uid-fixture','<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div><script type="module" src="/service-uid-entry.js"></script></body></html>'));});}
}],server:{host:'127.0.0.1',port:0,proxy:{},hmr:false}});
let browser;
const results=[]; const errors=[];
try {
  await mkdir(out,{recursive:true}); await server.listen();
  const origin='http://127.0.0.1:'+server.httpServer.address().port;
  browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();
  page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
  for(const width of [390,1440]) {
    await page.setViewportSize({width,height:900});
    await page.goto(origin+'/service-uid-fixture');
    await page.locator('.system-memory').waitFor();
    assert.equal(await page.locator('.machine-badge').textContent(),'未判定');
    assert.match(await page.locator('.machine-badge').getAttribute('title'),/证据不足/);
    assert.match(await page.locator('.system-memory').textContent(),/系统可见容量.*7.6 GiB/s);
    assert.equal(await page.locator('.system-memory .memory-status').count(),0);
    assert.match(await page.locator('.platform-inventory').textContent(),/平台提供.*不作为物理机判据.*American Megatrends Inc.*5.13/s);
    assert.equal(await page.locator('.physical-inventory').count(),0);
    assert.deepEqual(await page.evaluate(()=>window.evidence),actual);
    const bounds=await page.evaluate(()=>[...document.querySelectorAll('main,.hardware-panel,.system-memory,.platform-inventory,.memory-capacity')].map(el=>({selector:el.className,scroll:el.scrollWidth,client:el.clientWidth,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right})));
    for(const b of bounds){assert.ok(b.scroll<=b.client+1,JSON.stringify(b));assert.ok(b.left>=-1&&b.right<=width+1,JSON.stringify(b));}
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.deepEqual(errors,[]);
    await page.screenshot({path:resolve(out,'nas-service-uid-'+width+'.png'),fullPage:true});
    results.push({width,evidence:'real_service_UID_candidate_functions_via_JSONB_public_HTTP',bounds,text:await page.locator('.system-memory').textContent()});
  }
  await page.goto(origin+'/service-uid-fixture?failure');
  await page.locator('.system-memory').waitFor();
  assert.match(await page.locator('.system-memory').textContent(),/刷新失败.*7.6 GiB/s);
  await page.locator('.system-memory').screenshot({path:resolve(out,'synthetic-refresh-failure.png')});
  results.push({evidence:'synthetic_failure_overlay_on_real_sample',text:await page.locator('.system-memory').textContent()});
  assert.deepEqual(before,fingerprint()); assert.deepEqual(errors,[]);
  await writeFile(resolve(out,'results.json'),JSON.stringify({revision:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--short'],{encoding:'utf8'}),sourceHashes:before,readbackSha256:createHash('sha256').update(readFileSync(input)).digest('hex'),results,errors},null,2));
  console.log(JSON.stringify({cases:results.length,errors,out}));
} finally {await browser?.close();await server.close();}
