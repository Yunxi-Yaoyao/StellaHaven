// Isolated built-app proof: strict local HTTP fixtures, normal HTTP cache, no route interception.
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';
const [beforeDir, afterDir, outDir] = process.argv.slice(2);
assert(beforeDir && afterDir && outDir, 'usage: node tests/shell-perf-browser.mjs before-dist after-dist report-dir');
await fs.mkdir(outDir, { recursive: true });
const API_DELAY = 120, STATIC_DELAY = 40;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const defaultBg = '/assets/homebg/default-bg-kimono-1920.webp';
const me = { id: 'fixture-owner', username: 'fixture', display_name: 'Isolated Owner', is_admin: true, home_bg: defaultBg, avatar_url: '/avatar.png', email: '', email_verified: false };
const media = { url: defaultBg, status: 'ready', thumbnail: defaultBg, variants: { original: defaultBg }, width: 100, height: 60 };
const svg = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"><rect width="100" height="60" fill="#14171f"/></svg>');
async function serve(dir, label) {
 const requests = [], unknown = [];
 const jsons = new Map([
  ['/auth/me', me], ['/auth/security', { enabled: true, configured: true, elevated: false, expires_at: null, single_user: true, setup_required: false }],
  ['/navigation', { entries: [], settings_route: '/settings' }], ['/external-modules', []], ['/notifications/unread-count', { count: 0 }],
  ['/notifications/', []], ['/auth/avatars', []], ['/auth/sessions', []], ['/auth/email-service', { ready: false, configured: false, enabled: false }],
  ['/config/public-host', { value: '' }], ['/homebg/', [{ id: 'fixture-bg', name: 'Isolated default', ext: 'webp', url: defaultBg, isDefault: true, media }]],
  ['/homebg/media', media], ['/integration-targets', []], ['/integration-presets', {}], ['/search', { items: [{ kind: 'module', id: '/settings', label: 'fixture-search-result', path: '/settings' }] }],
  ['/auth/status', { initialized: true, has_users: true }], ['/config/site-background', { value: defaultBg }]
 ]);
 const routes = new Set(['/', '/settings', '/login', '/missing-stella-page']);
 const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost'); const p = url.pathname;
  const record = { label, path: p, method: req.method, start: performance.now() }; requests.push(record);
  const send = async (status, type, buffer, cache = 'no-store', delay = API_DELAY) => {
   await sleep(delay); let body = buffer;
   const headers = { 'Content-Type': type, 'Cache-Control': cache };
   if (req.headers['accept-encoding']?.includes('gzip') && /javascript|text\/css|application\/json/.test(type)) { body = gzipSync(buffer); headers['Content-Encoding'] = 'gzip'; headers.Vary = 'Accept-Encoding'; }
   headers['Content-Length'] = String(body.length); res.writeHead(status, headers); res.end(body);
   Object.assign(record, { status, bytes: body.length, end: performance.now() });
  };
  try {
   if (req.method === 'POST' && p === '/auth/activity') return await send(200, 'application/json', Buffer.from('{"ok":true}'));
   if (req.method !== 'GET') { unknown.push({ method: req.method, path: p }); return await send(501, 'application/json', Buffer.from('{"detail":"Unapproved write blocked"}')); }
   if (jsons.has(p)) return await send(200, 'application/json', Buffer.from(JSON.stringify(jsons.get(p))));
   if (p === defaultBg) return await send(200, 'image/svg+xml', svg, 'public,max-age=31536000,immutable', STATIC_DELAY);
   if (routes.has(p)) return await send(200, 'text/html', await fs.readFile(path.join(dir, 'index.html')), 'no-cache', STATIC_DELAY);
   if (p.startsWith('/static/') || p === '/avatar.png' || p === '/favicon.svg') {
    assert(!p.includes('..')); const body = await fs.readFile(path.join(dir, p));
    const ext = path.extname(p); const type = ({ '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png', '.svg': 'image/svg+xml' })[ext] || 'application/octet-stream';
    return await send(200, type, body, 'public,max-age=31536000,immutable', STATIC_DELAY);
   }
   unknown.push({ method: req.method, path: p }); await send(501, 'application/json', Buffer.from('{"detail":"Unknown endpoint blocked"}'));
  } catch (error) { unknown.push({ path: p, error: String(error) }); if (!res.headersSent) res.writeHead(500); res.end(); }
 });
 server.on('upgrade', (req, socket) => {
  if (req.url !== '/ws/notifications') { unknown.push({ websocket: req.url }); return socket.destroy(); }
  const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  socket.on('data', data => { if ((data[0] & 15) === 8) socket.end(Buffer.from([0x88, 0])); });
  socket.on('error', () => {});
 });
 await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
 const origin = `http://127.0.0.1:${server.address().port}`;
 return { server, origin, requests, unknown, label, dir };
}
async function graph(dir) {
 const manifest = JSON.parse(await fs.readFile(path.join(dir, '.vite/manifest.json'), 'utf8'));
 const entry = Object.keys(manifest).find(k => manifest[k].isEntry);
 const seen = new Set(); function walk(key) { if (seen.has(key)) return; seen.add(key); for (const next of manifest[key]?.imports || []) walk(next); } walk(entry);
 const closure = await Promise.all([...seen].map(async key => { const file = manifest[key].file; const bytes = await fs.readFile(path.join(dir, file)); return { key, file, bytes: bytes.length, gzip: gzipSync(bytes).length, imports: manifest[key].imports || [] }; }));
 const allJs = (await fs.readdir(path.join(dir, 'static'))).filter(p => p.endsWith('.js'));
 return { entry, entryClosure: closure, entryClosureBytes: closure.reduce((n, p) => n + p.bytes, 0), totalJsBytes: (await Promise.all(allJs.map(async p => (await fs.stat(path.join(dir, 'static', p))).size))).reduce((a,b) => a+b, 0), manifest };
}
const services = [await serve(beforeDir, 'before'), await serve(afterDir, 'after')];
const report = { environment: { browser: '', viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1, apiDelayMs: API_DELAY, staticDelayMs: STATIC_DELAY, network: 'loopback + fixed synthetic delay; not production latency', httpCache: 'normal; no context.route/CDP Fetch; static immutable gzip', live2d: 'off, unchanged source' }, samples: [], functional: {}, graph: { before: await graph(beforeDir), after: await graph(afterDir) } };
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-background-networking'] });
report.environment.browser = browser.version();
async function contextFor(service) {
 const context = await browser.newContext({ viewport: report.environment.viewport, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block' });
 await context.addInitScript(() => {
  localStorage.setItem('stella_live2d', 'off'); localStorage.setItem('stella_home_particles', 'off'); localStorage.setItem('stella_home_theme', 'daybreak');
  localStorage.setItem('stella_bootstrap', JSON.stringify({ userId: 'fixture-owner', workspaceId: 'fixture-workspace' }));
 });
 const page = await context.newPage(); const errors = [], foreign = [];
 page.on('pageerror', e => errors.push(e.message));
 page.on('console', message => { if (message.type() === 'error') errors.push('console: ' + message.text()); });
 page.on('request', req => { if (new URL(req.url()).origin !== service.origin) foreign.push(req.url()); });
 return { context, page, errors, foreign };
}
async function snapshot(page) {
 return await page.evaluate(() => ({ readyMs: performance.now(), resources: performance.getEntriesByType('resource').map(r => ({ path: new URL(r.name).pathname, initiatorType: r.initiatorType, startTime: r.startTime, responseStart: r.responseStart, responseEnd: r.responseEnd, duration: r.duration, transferSize: r.transferSize, encodedBodySize: r.encodedBodySize, decodedBodySize: r.decodedBodySize })), dom: ['.sidebar', 'main.content', '.daybreak', '.daybreak h1'].map(selector => { const el = document.querySelector(selector); return { selector, text: selector.includes('h1') ? el?.textContent : undefined, rect: el?.getBoundingClientRect().toJSON(), display: el && getComputedStyle(el).display }; }), live2dScript: !!document.querySelector('script[src*="cubism"]') }));
}
try {
 for (let round = 0; round < 5; round++) {
  for (const service of round % 2 ? [...services].reverse() : services) {
   const { context, page, errors, foreign } = await contextFor(service);
   for (const cache of ['cold', 'warm']) {
    const startRequest = service.requests.length;
    if (cache === 'cold') await page.goto(service.origin + '/', { waitUntil: 'domcontentloaded' }); else await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.daybreak h1');
    await page.waitForFunction(() => document.querySelector('.sidebar .name')?.textContent === 'Isolated Owner');
    const ready = await snapshot(page);
    await page.waitForLoadState('networkidle'); const settled = await snapshot(page);
    const js = settled.resources.filter(r => r.path.endsWith('.js'));
    const sample = { label: service.label, round, cache, ...ready, settledDom: settled.dom, settledResources: settled.resources, requestedJs: js.map(r => r.path), requestedJsDecodedBytes: js.reduce((n,r) => n+r.decodedBodySize,0), transferredJsBytes: js.reduce((n,r) => n+r.transferSize,0), jsCacheHits: js.filter(r => r.transferSize === 0).length, serverRequests: service.requests.slice(startRequest), errors: [...errors], foreign: [...foreign] };
    assert.equal(settled.dom[0].rect.width, 232); assert.equal(settled.dom[1].rect.x, 232);
    assert.equal(settled.dom[2].rect.y, 0); assert.equal(settled.dom[2].rect.width, 1208);
    assert.deepEqual(errors, []); assert.deepEqual(foreign, []); assert.equal(ready.live2dScript, false);
    if (service.label === 'after') assert(!sample.requestedJs.some(p => /CommandPalette|QuickRecordDialog|BgManager|servers-/.test(p)), 'closed optional graph must stay unloaded');
    report.samples.push(sample);
    if (round === 0 && cache === 'cold') await page.screenshot({ path: path.join(outDir, service.label + '-home.png') });
   }
   await context.close();
  }
 }
 const service = services[1]; const { context, page, errors, foreign } = await contextFor(service);
 await page.goto(service.origin + '/'); await page.waitForSelector('.daybreak h1'); await page.waitForLoadState('networkidle');
 assert.equal(await page.locator('.command-palette-root').count(), 1, 'global integration marker must exist without loading the palette');
 // Model a workspace selected earlier in this authenticated session; App correctly
 // discards a pre-auth bootstrap cache, so seed only after the owner is verified.
 await page.evaluate(() => localStorage.setItem('stella_bootstrap', JSON.stringify({ userId: 'fixture-owner', workspaceId: 'fixture-workspace' })));
 let requested = []; page.on('request', req => { if (req.url().endsWith('.js')) requested.push(new URL(req.url()).pathname); });
 // Exercise the first-load race without routing/interception: Escape while a delayed chunk loads.
 await page.keyboard.press('Control+k'); await page.keyboard.press('Escape'); await page.waitForLoadState('networkidle');
 assert.equal(await page.getByRole('dialog', { name: '统一搜索与快捷命令' }).count(), 0);
 await page.keyboard.press('Control+k'); const palette = page.getByRole('dialog', { name: '统一搜索与快捷命令' }); await palette.waitFor();
 await page.getByRole('textbox', { name: '统一搜索', exact: true }).fill('fixture-search');
 await page.getByRole('option').filter({ hasText: 'fixture-search-result' }).waitFor();
 const paletteDom = await palette.boundingBox(); assert(paletteDom.x >= 0 && paletteDom.y >= 0 && paletteDom.x + paletteDom.width <= 1440 && paletteDom.y + paletteDom.height <= 960);
 await page.screenshot({ path: path.join(outDir, 'after-palette.png') });
 await page.keyboard.press('Control+k'); assert.equal(await palette.count(), 0);
 await page.keyboard.press('Meta+k'); await palette.waitFor(); await page.keyboard.press('Escape'); assert.equal(await palette.count(), 0);
 await page.evaluate(() => window.dispatchEvent(new Event('stella:command-palette'))); await palette.waitFor();
 await page.getByRole('button', { name: '快捷记录', exact: true }).click(); await page.getByRole('dialog', { name: '快捷记录', exact: true }).waitFor();
 await page.getByRole('textbox', { name: '记录标题' }).fill('local-unsaved');
 await page.getByRole('button', { name: '取消', exact: true }).click();
 await page.keyboard.press('Control+k'); await palette.waitFor(); await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter'); await page.waitForSelector('.daybreak h1');
 const paletteJs = [...requested]; requested = [];
 await page.getByTitle('主页设置', { exact: true }).click(); await page.waitForURL('**/settings?section=navigation&module=home');
 await page.getByRole('button', { name: '更换背景', exact: true }).click(); await page.locator('.bgm').waitFor();
 await page.locator('.bgm .cell').waitFor(); await page.screenshot({ path: path.join(outDir, 'after-background.png') });
 const backgroundDom = await page.locator('.bgm').boundingBox(); assert(backgroundDom.x >= 0 && backgroundDom.y >= 0 && backgroundDom.x + backgroundDom.width <= 1440 && backgroundDom.y + backgroundDom.height <= 960);
 await page.locator('.bgm .x').click(); await page.locator('.bgm').waitFor({ state: 'hidden' });
 await page.getByRole('button', { name: '更换背景', exact: true }).click(); await page.locator('.bgm').waitFor();
 await page.locator('.bgm').getByRole('button', { name: '取消', exact: true }).click(); await page.locator('.bgm').waitFor({ state: 'hidden' });
 await page.waitForLoadState('networkidle');
 report.functional = { passed: true, keyboardFirstOpen: true, pendingEscape: true, ctrlToggle: true, metaShortcut: true, customEvent: true, arrowEnter: true, search: true, quickRecordOpenCancel: true, legacyGearRedirect: true, backgroundOpenCloseReopen: true, paletteDom, backgroundDom, paletteRequestedJs: paletteJs, backgroundAndSettingsRequestedJs: requested, errors, foreign };
 assert.deepEqual(errors, []); assert.deepEqual(foreign, []); await context.close();
 for (const service of services) assert.deepEqual(service.unknown, [], service.label + ' unknown requests');
 const median = a => [...a].sort((a,b)=>a-b)[Math.floor(a.length/2)];
 report.summary = Object.fromEntries(services.map(service => [service.label, Object.fromEntries(['cold','warm'].map(cache => { const samples = report.samples.filter(s => s.label === service.label && s.cache === cache); return [cache, { n: samples.length, medianReadyMs: median(samples.map(s => s.readyMs)), medianRequestedJsDecodedBytes: median(samples.map(s => s.requestedJsDecodedBytes)), medianTransferredJsBytes: median(samples.map(s => s.transferredJsBytes)), requestedJsCount: samples[0].requestedJs.length, jsCacheHits: samples[0].jsCacheHits }]; }))]));
 console.log(JSON.stringify(report.summary, null, 2));
} finally {
 await fs.writeFile(path.join(outDir, 'browser-results.json'), JSON.stringify(report, null, 2));
 await browser.close(); for (const service of services) service.server.close();
}
