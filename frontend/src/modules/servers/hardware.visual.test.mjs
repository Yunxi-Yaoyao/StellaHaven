// Local-only browser regression: actual detail component and charts, fixture APIs.
// Run from frontend: node src/modules/servers/hardware.visual.test.mjs
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';

const out = process.env.HARDWARE_TEST_OUTPUT || '/root/.hermes/cache/scratch/hardware-frontend';
await mkdir(out, { recursive: true });
const bootstrap = `
import { createApp, h } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Detail from '/src/modules/servers/NodeDetailView.vue';
import Nodes from '/src/modules/servers/NodesView.vue';
import { node } from '/src/modules/servers/hardware.testFixtures.ts';
import '/src/style.css';
const fixture = structuredClone(node);
fixture.arch = 'AMD64'; fixture.agent_version = '0.10.0';
fixture.os_name = 'Windows 11'; fixture.last_seen_at = new Date().toISOString();
fixture.sys_info.hardware.sampled_at = new Date().toISOString();
fixture.sys_info.hardware.cpu.sampled_at = new Date().toISOString();
fixture.sys_info.hardware.sensors_sampled_at = new Date().toISOString();
const mode = new URLSearchParams(location.search);
if (mode.has('virtual')) fixture.sys_info.hardware.machine.kind = 'virtual';
if (mode.has('wmi')) Object.assign(fixture.sys_info.hardware.cpu, {
  frequency_source: 'Win32_Processor.CurrentClockSpeed (WMI; not measured boost)',
  max_frequency_mhz: null, base_frequency_mhz: 3800,
  base_frequency_source: 'Win32_Processor.MaxClockSpeed',
});
if (location.search.includes('long')) {
  fixture.sys_info.hardware.cpu.model = 'CPU-' + 'LongModel'.repeat(24);
  fixture.sys_info.hardware.gpus.push({ ...fixture.sys_info.hardware.gpus[0], id: 'GPU-2', name: 'GPU-' + 'LongModel'.repeat(24) });
}
window.hardwareFixtureRequests = [];
window.fetch = async (url, options = {}) => {
  const path = String(url);
  window.hardwareFixtureRequests.push({ path, method: options.method || 'GET' });
  if (options.method && options.method !== 'GET') throw new Error('Unexpected write: ' + path);
  let data;
  if (path === '/nodes/7') data = fixture;
  else if (path === '/nodes/') data = ['physical', 'virtual', 'container', 'unknown', null].map((kind, index) => {
    const row = structuredClone(fixture); row.id = 7 + index; row.name = 'Generic node ' + index;
    row.sys_info.hardware.machine = kind ? { ...row.sys_info.hardware.machine, kind } : undefined;
    return row;
  });
  else if (path === '/nodes/host') data = { installed: true };
  else if (path === '/config/public-host') data = { value: '' };
  else if (path === '/component-installs') data = [];
  else if (path === '/monitors/') data = [];
  else if (path.startsWith('/nodes/7/net-tasks/latest')) data = { created_at: new Date().toISOString(), result_json: { ufw: {}, rules: [], marks: [], tables: {} } };
  else if (path.startsWith('/nodes/7/metrics') || path.startsWith('/nodes/7/sys-metrics')) data = [];
  else if (path.startsWith('/nodes/7/traffic-stats')) data = null;
  else throw new Error('Unexpected API: ' + path);
  return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
await router.push('/'); await router.isReady();
createApp({ render: () => h(mode.has('list') ? Nodes : Detail, { nodeId: 7 }) }).use(router).mount('#app');
`;
const server = await createServer({
  configFile: false, root: resolve('.'), cacheDir: resolve(out, 'visual-vite-cache'),
  plugins: [vue(), {
    name: 'hardware-fixture-entry',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url?.startsWith('/hardware-fixture')) {
          res.setHeader('Content-Type', 'text/html');
          res.end(await server.transformIndexHtml('/hardware-fixture', '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="app"></div><script type="module" src="/hardware-entry.js"></script></body></html>'));
        } else next();
      });
    },
    resolveId(id) { if (id === '/hardware-entry.js') return '\0hardware-entry'; },
    load(id) { if (id === '\0hardware-entry') return bootstrap; },
  }],
  server: { host: '127.0.0.1', port: 0, proxy: {}, hmr: false },
});
let browser;
const results = [];
try {
  await server.listen();
  const port = server.httpServer.address().port;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/sbin/google-chrome-stable', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== `http://127.0.0.1:${port}`) return route.abort();
    return route.continue();
  });
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1100 });
    await page.goto(`http://127.0.0.1:${port}/hardware-fixture`);
    await page.locator('.gpu-card').waitFor();
    assert.equal(await page.locator('.d-head .machine-badge').textContent(), '物理机');
    assert.equal(await page.locator('[aria-label="物理机清单"]').count(), 1);
    assert.match(await page.locator('.sample-status').textContent(), /最近采样/);
    const nameLayout = await page.locator('.d-head .name').evaluate(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height }));
    assert.equal((width > 768 || nameLayout.width >= 120) && nameLayout.height <= 60, true, `machine badge squeezes node name at ${width}: ${JSON.stringify(nameLayout)}`);
    await page.screenshot({ path: resolve(out, `hardware-${width}.png`), fullPage: true });
    const layout = await page.evaluate(() => {
      const detail = document.querySelector('.detail-body');
      const hardware = document.querySelector('.hardware-panel');
      const outside = [...hardware.querySelectorAll('*')].filter(el => {
        const r = el.getBoundingClientRect(), p = hardware.getBoundingClientRect();
        return r.width && (r.right > p.right + 1 || r.left < p.left - 1);
      }).map(el => el.className || el.tagName);
      return { width: innerWidth, documentWidth: document.documentElement.scrollWidth, detailWidth: detail.clientWidth, detailScrollWidth: detail.scrollWidth, outside, background: getComputedStyle(hardware).backgroundColor, requests: window.hardwareFixtureRequests };
    });
    results.push(layout);
    await writeFile(resolve(out, 'visual-layout.json'), JSON.stringify(results, null, 2));
    assert.equal(layout.documentWidth <= width, true, `document horizontal overflow at ${width}`);
    assert.equal(layout.detailScrollWidth <= layout.detailWidth, true, `detail horizontal overflow at ${width}: ${JSON.stringify(layout)}`);
    assert.deepEqual(layout.outside, [], `hardware content overflow at ${width}`);
    assert.equal(layout.background, 'rgb(20, 23, 31)');
  }
  await page.setViewportSize({ width: 360, height: 1100 });
  await page.goto(`http://127.0.0.1:${port}/hardware-fixture?long`);
  await page.locator('.gpu-card').nth(1).waitFor();
  const stress = await page.locator('.hardware-panel').evaluate(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth }));
  assert.equal(stress.scrollWidth <= stress.width, true, 'long multi-GPU model overflows');
  await page.screenshot({ path: resolve(out, 'hardware-long-360.png'), fullPage: true });
  await page.goto(`http://127.0.0.1:${port}/hardware-fixture?virtual`);
  await page.locator('.gpu-card').waitFor();
  assert.equal(await page.locator('.d-head .machine-badge').textContent(), '虚拟机');
  assert.equal(await page.locator('[aria-label="物理机清单"], .sensors-card').count(), 0);
  await page.screenshot({ path: resolve(out, 'hardware-virtual-360.png'), fullPage: true });
  await page.goto(`http://127.0.0.1:${port}/hardware-fixture?wmi`);
  await page.locator('.cpu-card').waitFor();
  assert.match(await page.locator('.cpu-card').textContent(), /WMI 标称元数据.*非实测最高/s);
  await page.screenshot({ path: resolve(out, 'hardware-wmi-360.png'), fullPage: true });
  for (const width of [360, 1440]) {
    await page.setViewportSize({ width, height: 1100 });
    await page.goto(`http://127.0.0.1:${port}/hardware-fixture?list`);
    await page.locator('.grid > .card').nth(4).waitFor();
    assert.deepEqual(await page.locator('.grid > .card .machine-badge').allTextContents(), ['物理机', '虚拟机', '容器', '未确定', '未确定']);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: resolve(out, `hardware-list-${width}.png`), fullPage: true });
  }
  assert.deepEqual(errors, [], 'browser runtime errors');
  console.log(JSON.stringify({ passed: true, classificationAndInventory: true, listLabels: true, wmiMobile: true, viewports: results, longModel: stress, browserErrors: errors }, null, 2));
} finally {
  await browser?.close(); await server.close();
}
