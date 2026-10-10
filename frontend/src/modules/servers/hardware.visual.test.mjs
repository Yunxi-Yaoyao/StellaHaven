// Isolated browser regression: real whole NodeDetailView / NodesView + product
// style.css, real captured response bases and explicitly labelled contract fixtures.
// No live API, writes, deployment, or production session. Run from frontend.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';
const out = process.env.HARDWARE_TEST_OUTPUT || '/opt/hermes-workstation/docs/stella-hardware-refine-20261010/frontend';
const revision = execFileSync('git', ['rev-parse', 'HEAD'], { encoding:'utf8' }).trim();
const sourceDiff = execFileSync('git', ['diff', 'HEAD', '--', 'src/modules/servers/HardwareInfoPanel.vue', 'src/modules/servers/hardwareDisplay.ts', 'src/modules/servers/hardware.test.ts', 'src/modules/servers/hardware.visual.test.mjs'], { encoding:'utf8' });
const sourceFiles = ['src/modules/servers/HardwareInfoPanel.vue','src/modules/servers/hardwareDisplay.ts','src/modules/servers/hardware.visual.test.mjs','src/modules/servers/NodeDetailView.vue','src/modules/servers/StoragePanel.vue','src/modules/servers/NodesView.vue','src/api/servers.ts','src/style.css', ...readdirSync('src/modules/servers/fixtures').filter(file => file.endsWith('.json')).map(file => 'src/modules/servers/fixtures/'+file)];
const fingerprint = () => Object.fromEntries(sourceFiles.map(file => [file,createHash('sha256').update(readFileSync(file)).digest('hex')]));
const sourceManifest = fingerprint();
await mkdir(out, { recursive: true });
const bootstrap = `
import { createApp, h } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Detail from '/src/modules/servers/NodeDetailView.vue';
import Nodes from '/src/modules/servers/NodesView.vue';
import nas from '/src/modules/servers/fixtures/node-55.contract-fixture.json';
import windows from '/src/modules/servers/fixtures/node-57.contract-fixture.json';
import oldNas from '/src/modules/servers/fixtures/node-55.captured.json';
import oldWindows from '/src/modules/servers/fixtures/node-57.captured.json';
import '@fontsource-variable/inter';
import '/src/style.css';
const mode = new URLSearchParams(location.search);
if (mode.has('content980')) Object.assign(document.querySelector('#app').style, { width: '1024px', margin: '0 auto' });
const fixture = structuredClone(mode.has('nas') ? (mode.has('legacy') ? oldNas : nas) : (mode.has('legacy') ? oldWindows : windows));
if (mode.has('drm')) Object.assign(fixture.sys_info.hardware.gpus[0], { graphics_clock_mhz: 100, telemetry_status: 'available', source: 'Intel DRM' });
if (mode.has('gpu-invalid')) {
  Object.assign(fixture.sys_info.hardware.gpus[0], { telemetry_status: mode.get('gpu-invalid'), temperature_c:0, utilization_pct:0, power_w:0, memory_used_mib:0, memory_total_mib:0, graphics_clock_mhz:0, memory_clock_mhz:0, fan_pct:0 });
}
if (mode.has('gpu-stale')) fixture.sys_info.hardware.gpus[0].sampled_at = '2026-10-10T11:22:50Z';
if (mode.has('virtual')) fixture.sys_info.hardware.machine.kind = 'virtual';
if (mode.has('wmi')) Object.assign(fixture.sys_info.hardware.cpu, { frequency_source: 'Win32_Processor.CurrentClockSpeed (WMI)', frequency_mhz: 3900 });
if (mode.has('long')) {
  fixture.name = '设备-' + 'LongNode'.repeat(10);
  fixture.sys_info.hardware.cpu.model = 'CPU-' + 'LongModel'.repeat(24);
  fixture.sys_info.hardware.gpus.push({ ...fixture.sys_info.hardware.gpus[0], id: 'GPU-2', name: 'GPU-' + 'LongModel'.repeat(24) });
}
window.hardwareFixtureRequests = [];
window.fetch = async (url, options = {}) => {
  const path = String(url);
  window.hardwareFixtureRequests.push({ path, method: options.method || 'GET' });
  if (options.method && options.method !== 'GET') throw new Error('Unexpected write: ' + path);
  let data;
  if (path === '/nodes/' + fixture.id) data = fixture;
  else if (path === '/nodes/') data = ['physical', 'virtual', 'container', 'unknown', null].map((kind, index) => {
    const row = structuredClone(fixture); row.id = 70 + index; row.name = 'Generic node ' + index;
    row.sys_info.hardware.machine = kind ? { ...row.sys_info.hardware.machine, kind } : undefined;
    return row;
  });
  else if (path === '/nodes/host') data = { installed: true };
  else if (path === '/config/public-host') data = { value: '' };
  else if (path === '/component-installs' || path === '/monitors/') data = [];
  else if (path.includes('/net-tasks/latest')) data = { created_at: new Date().toISOString(), result_json: { ufw: {}, rules: [], marks: [], tables: {} } };
  else if (path.includes('/metrics') || path.includes('/sys-metrics')) data = [];
  else if (path.includes('/traffic-stats')) data = null;
  else throw new Error('Unexpected API: ' + path);
  return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
await router.push('/'); await router.isReady();
createApp({ render: () => h(mode.has('list') ? Nodes : Detail, { nodeId: fixture.id }) }).use(router).mount('#app');
`;
const server = await createServer({ configFile: false, root: resolve('.'), cacheDir: resolve(process.env.TMPDIR || '/root/.hermes/cache/scratch', 'hardware-visual/vite-cache'), plugins: [vue(), {
  name: 'hardware-fixture-entry',
  configureServer(server) { server.middlewares.use(async (req, res, next) => {
    if (!req.url?.startsWith('/hardware-fixture')) return next();
    res.setHeader('Content-Type', 'text/html');
    res.end(await server.transformIndexHtml('/hardware-fixture', '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="app"></div><script type="module" src="/hardware-entry.js"></script></body></html>'));
  }); },
  resolveId(id) { if (id === '/hardware-entry.js') return '\0hardware-entry'; },
  load(id) { if (id === '\0hardware-entry') return bootstrap; },
}], server: { host: '127.0.0.1', port: 0, proxy: {}, hmr: false } });
const results = [];
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/sbin/google-chrome-stable', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.clock.install({ time: new Date('2026-10-10T12:22:50Z') });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/*', route => new URL(route.request().url()).origin !== origin ? route.abort() : route.continue());
  async function inspect(name, width, query, { physical, volumes, badge, long = false, primaryCount = name === 'NAS' ? 1 : 2 } = {}) {
    await page.setViewportSize({ width, height: 1100 });
    await page.goto(`${origin}/hardware-fixture?${query}`);
    await page.locator('.cpu-card').waitFor();
    assert.equal(await page.locator('.name').textContent(), long ? '设备-' + 'LongNode'.repeat(10) : name === 'NAS' ? 'NAS' : '5060');
    if (badge) assert.equal(await page.locator('.d-head .machine-badge').textContent(), badge);
    if (physical != null) assert.equal(await page.locator('.physical-disk-row').count(), physical);
    if (volumes != null) assert.equal(await page.locator('.volume-row').count(), volumes);
    assert.equal(await page.locator('.physical-disk-row .usage-track, .disk-ring').count(), 0);
    assert.equal(await page.locator('.hardware-panel time').count(), 0);
    const cpu = await page.locator('.cpu-card').textContent();
    assert.doesNotMatch(cpu, /报告上限|标称|来源|未读取/);
    assert.match(cpu, name === 'NAS' ? /15.1 %/ : /20.8 %/);
    if (!long) assert.doesNotMatch(await page.locator('.system-strip').textContent(), /AMD Ryzen|Intel\(R\)/);
    const body = await page.locator('.hardware-panel').textContent();
    assert.doesNotMatch(body, /0 RPM.*转速比例|来源|未读取/);
    const inventoryGpu = page.locator('.gpu-inventory-row').filter({ hasText: '集成显卡' });
    if (!query.includes('legacy')) {
      assert.equal(await inventoryGpu.count(), 1);
      assert.equal(await inventoryGpu.locator('dd').count(), 0);
    }
    const layout = await page.evaluate(() => {
      const detail = document.querySelector('.detail-body');
      const hardware = document.querySelector('.hardware-panel');
      const storage = document.querySelector('.storage-panel');
      const outside = [...hardware.querySelectorAll('*'), ...storage.querySelectorAll('*')].filter(el => {
        const r = el.getBoundingClientRect(), p = el.closest('.hardware-panel,.storage-panel').getBoundingClientRect();
        return r.width && (r.right > p.right + 1 || r.left < p.left - 1);
      }).map(el => el.className || el.tagName);
      const rect = el => { const r = el.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height, bottom:r.bottom, right:r.right }; };
      const cards = [...document.querySelectorAll('.hardware-card')].map(el => ({ class:el.className,...rect(el) }));
      const grid = document.querySelector('.hardware-grid');
      const primary = [...grid.children].map(el => ({ class:el.className,...rect(el) }));
      const sensor = document.querySelector('.sensors-card');
      const strips = [...document.querySelectorAll('.gpu-inventory-row')].map(rect);
      const overlaps = cards.flatMap((a,i) => cards.slice(i+1).filter(b => a.x < b.right-1 && a.right > b.x+1 && a.y < b.bottom-1 && a.bottom > b.y+1).map(b => [a.class,b.class]));
      return { width:innerWidth, documentWidth:document.documentElement.scrollWidth, detailWidth:detail.clientWidth, detailScrollWidth:detail.scrollWidth, outside, overlaps, cards,
        storage:rect(storage), hardware:rect(hardware), gridAlign:getComputedStyle(grid).alignItems,
        primary, grid:rect(grid), sensor:sensor ? rect(sensor) : null, sensorInGrid:!!grid.querySelector('.sensors-card'),
        stripInGrid:!!grid.querySelector('.gpu-inventory-row'), strips,
        background:getComputedStyle(storage).backgroundColor, rows:[...document.querySelectorAll('.physical-disk-row,.volume-row')].map(el => ({ text:el.textContent,...rect(el) })), requests:window.hardwareFixtureRequests };
    });
    results.push({ name, query, ...layout });
    await writeFile(resolve(out, 'visual-layout.json'), JSON.stringify(results,null,2));
    assert.equal(layout.documentWidth <= width, true, 'document overflow');
    assert.equal(layout.detailScrollWidth <= layout.detailWidth, true, 'detail inner overflow');
    assert.deepEqual(layout.outside, [], 'card child overflow');
    assert.deepEqual(layout.overlaps, [], 'cards overlap');
    assert.equal(layout.gridAlign, 'start', 'cards must have independent natural heights');
    assert.equal(layout.sensorInGrid, false, 'secondary sensors must not create tall primary grid rows');
    assert.equal(layout.stripInGrid, false, 'inventory GPU must not consume a primary grid column');
    if (!long) {
      assert.equal(layout.primary.length, primaryCount, 'only CPU and meaningful GPU telemetry belong in the primary grid');
      const lastBottom = Math.max(...layout.primary.map(c => c.bottom));
      assert.ok(Math.abs(layout.grid.bottom-lastBottom)<2, 'primary grid has no trailing empty row height');
      for (const strip of layout.strips) {
        assert.ok(strip.y>=lastBottom, 'inventory follows all primary cards');
        assert.ok(strip.height <= (width>=1000 ? 56 : 110), 'inventory row is compact');
      }
      if (layout.sensor) {
        assert.ok(Math.abs(layout.sensor.width-layout.hardware.width)<1, 'sensors use independent full width');
        assert.ok(layout.sensor.y>=lastBottom, 'sensors are below primary summaries');
        if (width>=1000) assert.ok(layout.sensor.height<320, 'sensor area must not be a long single-column card');
      }
      if (width>=1000 && name==='5060' && primaryCount===2) {
        assert.ok(Math.abs(layout.primary[0].y-layout.primary[1].y)<1, 'CPU and telemetry GPU share one summary row');
        assert.ok(Math.abs(layout.primary[0].height-layout.primary[1].height)<90, 'no large vacant half-row under CPU');
      }
      if (width>=1000 && name==='NAS') assert.ok(layout.primary[0].width<=560, 'CPU-only summary stays moderately sized');
    }
    if (query.includes('content980')) assert.ok(Math.abs(layout.hardware.width-980)<1, 'actual 980px allocated content width');
    assert.equal(layout.background, 'rgb(20, 23, 31)', 'Stella dark blue palette');
    assert.equal(Math.abs(layout.storage.width-layout.hardware.width)<1, true, 'storage is full width');
    assert.equal(layout.storage.y >= layout.hardware.bottom-1, true, 'storage does not overlap hardware');
    assert.equal(layout.requests.every(r => r.method === 'GET'), true, 'no state-changing API');
    if (width >= 1000 && layout.cards.length > 1) {
      const sizing = await page.locator('.hardware-card').evaluateAll(cards => cards.map(card => {
        const before = card.getBoundingClientRect();
        const clone = card.cloneNode(true);
        clone.style.cssText += `;position:fixed;width:${before.width}px;box-sizing:border-box;height:auto;min-height:0;max-height:none;left:-10000px;`;
        card.parentElement.append(clone);
        const natural = clone.getBoundingClientRect().height;
        clone.remove();
        return { actual: before.height, natural };
      }));
      assert.ok(sizing.every(c => Math.abs(c.actual-c.natural)<2), 'cards match independently measured intrinsic height, even when equal by coincidence');
    }
    for (let i=1;i<layout.rows.length;i++) assert.equal(layout.rows[i].y>=layout.rows[i-1].bottom-1,true,'storage rows overlap');
    const headings = await page.locator('.d-head .name').evaluate(el => ({ ...(() => { const r=el.getBoundingClientRect();return { width:r.width,height:r.height }; })(), lineHeight:parseFloat(getComputedStyle(el).lineHeight) }));
    assert.equal(headings.lineHeight<=25,true,'real detail header typography');
    if (!long) assert.equal(headings.height<=60,true,'badge must not squeeze name');
    const variant = query.includes('gpu-invalid') ? `gpu-${new URLSearchParams(query).get('gpu-invalid')}` : query.includes('gpu-stale') ? 'gpu-stale' : query.includes('content980') ? 'content980' : query.includes('drm') ? 'drm' : query.includes('legacy') ? 'captured' : query.includes('wmi') ? 'wmi' : long ? 'stress' : query.includes('virtual') ? 'virtual' : 'contract';
    const stem = `${name}-${variant}-${width}`;
    // Preserve the actual bounded scroller viewport before expanding ONLY for
    // an archival full-content capture. Layout assertions above use product CSS.
    await page.screenshot({ path:resolve(out, `${stem}-viewport.png`), fullPage:true });
    await page.locator('.storage-panel').scrollIntoViewIfNeeded();
    await page.screenshot({ path:resolve(out, `${stem}-storage-viewport.png`), fullPage:true });
    const fullHeight = await page.locator('.detail-body').evaluate(el => {
      const height=el.scrollHeight; el.scrollTop=0; el.style.height=height+'px'; el.style.overflow='visible'; return height;
    });
    assert.ok(fullHeight > 1100, 'full archive must include all storage rows and the real chart sections');
    await page.screenshot({ path:resolve(out, `${stem}.png`), fullPage:true });
    const capture = await page.evaluate(() => ({ documentHeight:document.documentElement.scrollHeight,
      rows:[...document.querySelectorAll('.physical-disk-row,.volume-row')].map(el => ({text:el.textContent,bottom:el.getBoundingClientRect().bottom})) }));
    assert.ok(capture.rows.every(row => row.bottom <= capture.documentHeight), 'every disk row must be in full archive');
  }
  for (const width of [1440,390,360]) {
    await inspect('5060',width,'',{ physical:2,volumes:3,badge:'物理机' });
    const sensors=await page.locator('.sensors-card').textContent();
    for(const value of ['温度探头 1 · Temperature #1','风扇 2 · Fan #2','核心簇 1 温度 · CCD1 (Tdie)']) assert.ok(sensors.includes(value),value);
    assert.doesNotMatch(sensors,/ITE IT8613E|Core \(Tctl\/Tdie\)/);
    await inspect('NAS',width,'nas',{ physical:7,volumes:5,badge:'未确定' });
    for(const mount of ['/vol1','/vol2','/vol3','/boot/efi']) assert.equal(await page.locator('.volume-row').filter({hasText:mount}).count(),1,mount);
    assert.equal(await page.locator('.volume-row.system-volume').count(),2);
    assert.equal(await page.locator('.volume-row .usage-track').count(),5);
  }
  await inspect('5060',1440,'content980',{ physical:2,volumes:3,badge:'物理机' });
  await inspect('NAS',1440,'nas&content980&drm',{ physical:7,volumes:5,badge:'未确定' });
  assert.match(await page.locator('.gpu-inventory-row').textContent(), /100 MHz/);
  for (const state of ['unsupported','driver_missing','query_failed']) {
    await inspect('5060',390,`gpu-invalid=${state}`,{physical:2,volumes:3,badge:'物理机',primaryCount:1});
    const invalid = page.locator('.gpu-inventory-row').filter({hasText:'NVIDIA'});
    assert.equal(await invalid.count(),1,'invalid telemetry retains model');
    assert.doesNotMatch(await invalid.textContent(), /MHz|MiB|°C|RPM|%| W/);
    if (state!=='unsupported') assert.equal(await page.locator('.sample-status').textContent(),'刷新失败');
  }
  await inspect('5060',1440,'gpu-stale',{physical:2,volumes:3,badge:'物理机'});
  assert.equal(await page.locator('.sample-status').textContent(),'数据已过期');
  await inspect('5060',360,'legacy',{physical:2,volumes:0,badge:'物理机'});
  await inspect('NAS',360,'nas&legacy',{physical:7,volumes:3,badge:'未确定'});
  await inspect('5060',360,'wmi',{physical:2,volumes:3,badge:'物理机'});
  assert.doesNotMatch(await page.locator('.cpu-card').textContent(),/当前频率|3900 MHz|WMI/);
  await inspect('5060',360,'long',{physical:2,volumes:3,badge:'物理机',long:true});
  await inspect('5060',360,'virtual',{physical:2,volumes:3,badge:'虚拟机'});
  assert.equal(await page.locator('[aria-label="物理机清单"], .sensors-card').count(),0);
  for(const width of [360,1440]) {
    await page.setViewportSize({width,height:1100});
    await page.goto(`${origin}/hardware-fixture?list`);
    await page.locator('.grid > .card').nth(4).waitFor();
    assert.deepEqual(await page.locator('.grid > .card .machine-badge').allTextContents(),['物理机','虚拟机','容器','未确定','未确定']);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:resolve(out,`list-${width}.png`),fullPage:true});
  }
  assert.deepEqual(errors,[],'browser runtime errors');
  assert.deepEqual(fingerprint(),sourceManifest,'rendered source must not change during screenshot capture');
  const summary={ passed:true, revision, uiSourceClean:sourceDiff === '', sourceManifest, frontendWorkingChanges:execFileSync('git',['status','--porcelain','--','.'],{encoding:'utf8'}).trim(), mode:'isolated real components, captured bases + contract fixtures; NOT real new API/deployment', scenarios:results.length, listViewports:2, browserErrors:errors, results };
  await writeFile(resolve(out,'visual-result.json'),JSON.stringify(summary,null,2));
  console.log(JSON.stringify({passed:true,scenarios:results.length,listViewports:2,browserErrors:errors}));
} finally { await browser?.close(); await server.close(); }
