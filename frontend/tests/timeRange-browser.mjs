// Isolated real-App fixture browser QA. No backend proxy, cookies or live writes.
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = process.env.TIME_RANGE_OUTPUT || '/opt/hermes-workstation/docs/stella-overview-time-20261011/time';
const baseline = process.argv.includes('--baseline');
const source = resolve(root, 'src/modules/servers/NodeDetailView.vue');
const sourceBytes = baseline ? execFileSync('git', ['show', '4163e97:frontend/src/modules/servers/NodeDetailView.vue'], { cwd: root }) : await readFile(source);
const hash = data => createHash('sha256').update(data).digest('hex');
await mkdir(output, { recursive: true });
const server = await createServer({ root, configFile: false, cacheDir: 'node_modules/.tmp/time-browser-vite',
  plugins: [{ name: 'time-baseline', enforce: 'pre', transform(code, id) { if (baseline && id === source) return sourceBytes.toString(); } }, vue()],
  server: { host: '127.0.0.1', port: 0, proxy: {}, strictPort: false },
});
let browser;
const report = { mode: baseline ? 'baseline' : 'candidate', fixture: true, sourceHash: hash(sourceBytes),
  commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root }).toString().trim(),
  dirty: execFileSync('git', ['status', '--short'], { cwd: root }).toString(), scenarios: [] };
try {
  await server.listen();
  const port = server.httpServer.address().port, origin = `http://127.0.0.1:${port}`;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/sbin/google-chrome-stable', headless: true, args: ['--no-sandbox'] });
  for (const [timezoneId, initialTab] of [['America/Los_Angeles', 'overview'], ['America/Los_Angeles', 'network'], ...(!baseline ? [['Asia/Tokyo', 'overview']] : [])]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, timezoneId });
    const page = await context.newPage();
    const requests = [], unknown = [], errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.clock.install({ time: new Date('2026-10-10T08:00:00Z') });
    await page.clock.pauseAt(new Date('2026-10-10T08:00:01Z'));
    await page.routeWebSocket('**/*', socket => socket.close());
    await page.route('**/*', async route => {
      const req = route.request(), u = new URL(req.url()), p = u.pathname;
      if (u.origin !== origin) { unknown.push(u.href); return route.abort(); }
      if (req.resourceType() === 'document' || p.startsWith('/src/') || p.startsWith('/@') || p.startsWith('/node_modules/') || p === '/favicon.svg') return route.continue();
      requests.push({ path: p, method: req.method(), start: u.searchParams.get('start'), end: u.searchParams.get('end') });
      const ok = json => route.fulfill({ json });
      const node = { id: 7, name: 'Time fixture server', host: 'fixture.test', status: 'online', installed: true, platform: 'linux', net_type: 'internal',
        interfaces: { eth0: { is_default: true, up: true } }, storage: [], components: {},
        latest_metrics: [{ iface: 'eth0', ts: '2026-10-10T07:59:55Z' }], latest_sys_metric: { ts: '2026-10-10T07:59:55Z' } };
      if (p === '/auth/me' || p === '/auth/refresh') return ok({ id: 'fixture-owner', username: 'Fixture', display_name: 'Fixture', is_admin: false, home_bg: '' });
      if (p === '/nodes/7') return ok(node);
      if (p === '/nodes/') return ok([node]);
      if (p === '/nodes/host') return ok(null);
      if (p === '/nodes/7/metrics') return ok(Array.from({ length: 12 }, (_, i) => ({ ts: new Date(Date.parse('2026-10-10T07:59:55Z') - i * 5000).toISOString(), rx_delta: 625000 + i * 50000, tx_delta: i * 10000 })));
      if (p === '/nodes/7/sys-metrics') return ok(Array.from({ length: 12 }, (_, i) => ({ ts: new Date(Date.parse('2026-10-10T07:59:55Z') - i * 60000).toISOString(), cpu_pct: 20 + i, mem_pct: 40, disk_pct: 30 })));
      if (p === '/nodes/7/traffic-stats') return ok({ sample_count: 12, rx_95: 625000, tx_95: 10000, rx_total: 100, tx_total: 30, rx_max: 700000, rx_min: 500000, tx_max: 10000, tx_min: 0 });
      if (p === '/nodes/7/net-tasks/latest') return ok({ created_at: '2026-10-10T08:00:00Z', result_json: { ufw: {}, rules: [], marks: [], tables: {} } });
      if (p === '/monitors/' || p === '/notifications/' || p === '/external-modules' || p === '/homebg/') return ok([]);
      if (p === '/navigation') return ok({ entries: [], settings_route: '/settings' });
      if (p === '/notifications/unread-count') return ok({ count: 0 });
      if (p === '/auth/activity') return ok({ ok: true });
      if (p === '/auth/security') return ok({ enabled: false, configured: true, elevated: false });
      if (p.startsWith('/config/')) return ok({ value: '' });
      if (p === '/homebg/media') return ok({ url: '', variants: {}, status: 'ready' });
      if (p === '/avatar.png') return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg"/>' });
      if (p.startsWith('/assets/homebg/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg"/>' });
      unknown.push(req.method() + ' ' + p); return route.fulfill({ status: 501, json: { detail: 'Unmocked request blocked' } });
    });
    await page.goto(origin + '/status/7' + (initialTab === 'network' ? '?tab=network' : ''));
    await page.locator('.d-head .name').filter({ hasText: 'Time fixture server' }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.chart canvas').length === 2);
    await page.clock.runFor(600); // Complete the real App route entrance transition before visual capture.
    const measure = async () => page.evaluate(async () => {
      const { getInstanceByDom } = await import('/src/modules/servers/chartRuntime.ts');
      return [...document.querySelectorAll('.detail-body .chart')].map(el => {
        const chart = getInstanceByDom(el), canvas = el.querySelector('canvas');
        return { container: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height,
          canvasWidth: canvas?.width || 0, chartWidth: chart?.getWidth(), data: chart?.getOption().series.map(s => s.data) };
      });
    });
    const hidden = initialTab === 'network' ? await measure() : null;
    if (initialTab === 'network') { await page.getByRole('button', { name: '概览', exact: true }).click(); await page.clock.runFor(300); }
    const initial = await measure();
    const scenario = { timezoneId, initialTab, hidden, initial, requests, unknown, errors }; report.scenarios.push(scenario);
    await page.screenshot({ path: resolve(output, `${baseline ? 'baseline' : 'candidate'}-${timezoneId.replace('/', '-')}-${initialTab}-desktop.png`) });
    if (!baseline) {
      for (const c of initial) { assert(c.canvasWidth > 0, 'initial canvas must have width'); assert(c.data.some(s => s.length > 0), 'initial chart must contain data'); }
      const count = () => requests.filter(r => ['/nodes/7/metrics', '/nodes/7/sys-metrics', '/nodes/7/traffic-stats'].includes(r.path)).length;
      const dates = page.locator('.chart-toolbar input[type=datetime-local]');
      assert.equal(await dates.count(), 2);
      const beforeLive = count();
      await page.locator('.live-btn').click(); await page.clock.runFor(100);
      // Existing live mode seeds history, then starts its immediate delta poll.
      // Wait for both groups before measuring requests caused by date input.
      for (let i = 0; i < 100 && count() < beforeLive + 6; i++) await new Promise(resolve => setTimeout(resolve, 10));
      await page.waitForFunction(() => !document.querySelector('.detail-body .empty[role=status]'));
      const before = count();
      await dates.nth(0).fill('2026-10-09T00:00');
      assert((await page.locator('.preset-btn').textContent()).includes('自定义'));
      assert(!(await page.locator('.live-btn').getAttribute('class')).includes(' on'));
      await page.clock.runFor(100); await dates.nth(1).fill('2026-10-10T00:00');
      await page.clock.runFor(249); assert.equal(count(), before);
      await page.clock.runFor(1); await page.waitForFunction(() => !document.querySelector('.detail-body .empty[role=status]'));
      assert.equal(count(), before + 3);
      const custom = requests.filter(r => r.start).slice(-3);
      assert(custom.every(r => r.start === '2026-10-08T16:00:00.000Z' && r.end === '2026-10-09T16:00:00.000Z'));
      scenario.custom = await measure();
      for (const c of scenario.custom) { assert(c.canvasWidth > 0); assert(c.data.some(s => s.length > 0)); }
      await dates.nth(0).fill('2026-10-11T00:00'); await page.clock.runFor(1000);
      assert.equal(count(), before + 3); assert((await page.locator('.range-error').textContent()).includes('晚于'));
      await page.screenshot({ path: resolve(output, `candidate-${timezoneId.replace('/', '-')}-${initialTab}-invalid.png`) });
      await dates.nth(0).fill('2026-10-09T00:00'); await page.clock.runFor(250);
      await page.setViewportSize({ width: 393, height: 852 }); await page.clock.runFor(300);
      scenario.mobile = await measure();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      for (const c of scenario.mobile) { assert(c.canvasWidth > 0); assert.equal(c.chartWidth, c.container); assert(c.data.some(s => s.length > 0)); }
      await page.locator('.chart-toolbar').scrollIntoViewIfNeeded();
      await page.screenshot({ path: resolve(output, `candidate-${timezoneId.replace('/', '-')}-${initialTab}-mobile.png`) });
      assert.equal(errors.length, 0, errors.join('\n')); assert.equal(unknown.length, 0, unknown.join('\n'));
    }
    await context.close();
  }
  assert.equal(hash(baseline ? sourceBytes : await readFile(source)), report.sourceHash, 'source changed during browser evidence');
} finally {
  await writeFile(resolve(output, `${baseline ? 'baseline' : 'candidate'}-browser.json`), JSON.stringify(report, null, 2));
  await browser?.close(); await server.close();
}
console.log(JSON.stringify(report, null, 2));
