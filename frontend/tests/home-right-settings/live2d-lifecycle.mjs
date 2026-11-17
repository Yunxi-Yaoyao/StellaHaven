// Real Cubism/Pixi acceptance. Only fixture HTTP data is synthetic; models are never stubbed.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import { chromium } from '@playwright/test';

const root = process.cwd(), port = 15585, MAIN = `http://127.0.0.1:${port}`;
const out = process.env.HOME_SETTINGS_EVIDENCE, modelDir = process.env.HOME_LIVE2D_MODEL_DIR;
assert(out && modelDir, 'Explicit evidence and read-only model paths required');
fs.mkdirSync(out, { recursive: true });
const refs = JSON.parse(fs.readFileSync(path.join(modelDir, 'miku.model3.json'))).FileReferences;
const files = [...new Set(['miku.model3.json', refs.Moc, refs.Physics, refs.DisplayInfo, ...refs.Textures,
  ...refs.Expressions.map(e => e.File), ...Object.values(refs.Motions).flat().map(e => e.File)].filter(Boolean))];
assert(files.every(f => !f.includes('..') && !path.isAbsolute(f)));
const resources = files.map(file => {
  const full = fs.realpathSync(path.join(modelDir, file));
  assert(full.startsWith(fs.realpathSync(modelDir) + path.sep));
  const body = fs.readFileSync(full);
  return { file, bytes: body.length, sha256: createHash('sha256').update(body).digest('hex') };
});
const harness = path.join(root, 'node_modules/.tmp/live2d-lifecycle-harness.mjs');
fs.writeFileSync(harness, ts.transpileModule(fs.readFileSync(root + '/e2e/experience-independent-harness.ts', 'utf8')
  .replaceAll('127.0.0.1:15487', `127.0.0.1:${port}`), { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText);
const { setup } = await import(harness);
const report = { commit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), resources, cases: [], failures: [] };
const server = await createServer({ root, configFile: false, plugins: [vue()], cacheDir: out + '/vite', server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, hmr: false } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ executablePath: '/usr/sbin/google-chrome-stable', headless: true, args: ['--no-sandbox', '--enable-unsafe-swiftshader'] });
  for (const width of [1440, 393]) {
    const context = await browser.newContext({ viewport: { width, height: width === 1440 ? 1000 : 852 } });
    const page = await context.newPage();
    const h = await setup(page, { storage: { stella_home_theme: 'nightfall' } });
    const lifecycleWarnings = [];
    page.on('console', m => { if (m.type() === 'warning' && /Live2D (initialization|cleanup) failed|Unhandled error/.test(m.text())) lifecycleWarnings.push(m.text()); });
    const fetched = [];
    let holdMoc = false, mocGate, releaseMoc, mocRequested;
    let releaseRuntime, runtimeRequested = false;
    const runtimeGate = new Promise(resolve => { releaseRuntime = resolve; });
    await context.addInitScript(() => {
      // Observe only callbacks registered from this component/helper, without changing their behavior.
      // Attribute to the immediate source caller, not a parent toast scheduled by emit('poke').
      const owned = () => /Live2dWidget|live2dLifetime/.test((new Error().stack || '').split('\n').find(line => line.includes('http://')) || '');
      const resources = window.__resources = { timeout: new Set(), interval: new Set(), raf: new Set(), listeners: [] };
      for (const [start, stop, kind, once] of [['setTimeout', 'clearTimeout', 'timeout', true], ['setInterval', 'clearInterval', 'interval', false], ['requestAnimationFrame', 'cancelAnimationFrame', 'raf', true]]) {
        const original = window[start].bind(window), cancel = window[stop].bind(window);
        window[start] = (fn, ...args) => {
          if (!owned()) return original(fn, ...args);
          let id;
          id = original((...values) => { if (once) resources[kind].delete(id); return fn(...values); }, ...args);
          resources[kind].add(id); return id;
        };
        window[stop] = id => { resources[kind].delete(id); return cancel(id); };
      }
      const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
      EventTarget.prototype.addEventListener = function(type, fn, opts) {
        if (owned()) resources.listeners.push({ target: this, type, fn, active: true });
        return add.call(this, type, fn, opts);
      };
      EventTarget.prototype.removeEventListener = function(type, fn, opts) {
        resources.listeners.filter(r => r.target === this && r.type === type && r.fn === fn).forEach(r => r.active = false);
        return remove.call(this, type, fn, opts);
      };
    });
    await context.route(MAIN + '/live2dcubismcore.min.js', async r => {
      runtimeRequested = true; await runtimeGate;
      return r.fulfill({ path: root + '/public/live2dcubismcore.min.js', contentType: 'application/javascript' });
    });
    await context.route(MAIN + '/assets/miku-l2d/**', async r => {
      const file = decodeURIComponent(new URL(r.request().url()).pathname.slice('/assets/miku-l2d/'.length));
      if (r.request().method() !== 'GET' || !files.includes(file)) { h.unknown.push(r.request().url()); return r.abort(); }
      fetched.push(file);
      if (file === refs.Moc && holdMoc) { holdMoc = false; mocRequested = true; await mocGate; }
      return r.fulfill({ path: path.join(modelDir, file), contentType: file.endsWith('.png') ? 'image/png' : file.endsWith('.json') ? 'application/json' : 'application/octet-stream' });
    });
    await context.route(MAIN + '/avatar.png', r => r.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>' }));
    const toggle = async () => { await page.getByRole('button', { name: '主页设置', exact: true }).click(); await page.getByRole('switch', { name: 'Live2D 挂件（Miku）' }).click(); await page.keyboard.press('Escape'); };
    const ready = () => page.waitForFunction(() => window.__miku?.internalModel?.coreModel && window.__mikuApp?.stage?.children.length === 1);
    const run = async (name, test) => {
      try { const evidence = await test(); report.cases.push({ name: `${name} ${width}`, status: 'pass', evidence }); }
      catch (e) { report.failures.push({ name: `${name} ${width}`, error: e.stack }); }
    };
    try {
      await page.goto(MAIN + '/#zones');
      await page.getByRole('button', { name: '主页设置', exact: true }).waitFor();
      await run('unmount while runtime script is pending', async () => {
        await toggle();
        for (let i = 0; i < 100 && !runtimeRequested; i++) await page.waitForTimeout(20);
        assert(runtimeRequested); await toggle(); releaseRuntime(); await page.waitForTimeout(500);
        const e = await page.evaluate(() => ({ canvases: document.querySelectorAll('.live2d-host canvas').length, model: !!window.__miku,
          ownedScripts: [...document.scripts].filter(s => s.src.endsWith('/live2dcubismcore.min.js')).length }));
        assert.equal(e.canvases, 0); assert(!e.model); assert.equal(e.ownedScripts, 0); return e;
      });
      releaseRuntime();
      // Import exactly Vite's modules used by the component. Wrap from() only to observe real results
      // and gate delivery; the original factory, requests, textures and Cubism model all run normally.
      await page.evaluate(async () => {
        if (window.Live2DCubismCore) return;
        await new Promise((resolve, reject) => { const s = document.createElement('script'); s.src = '/live2dcubismcore.min.js'; s.onload = resolve; s.onerror = reject; document.head.append(s); });
      });
      const transformed = await server.transformRequest('/src/modules/home/Live2dWidget.vue');
      const pixiURL = transformed.code.match(/from\s+["']([^"']*pixi[^"']*)["']/)?.[1];
      assert(pixiURL, 'transformed Pixi import');
      await page.evaluate(async url => { const { Ticker } = await import(url); window.__ticker = Ticker.shared; }, pixiURL);
      const modelURL = transformed.code.match(/import\(["']([^"']*cubism4[^"']*)["']\)/)?.[1];
      assert(modelURL, 'transformed Cubism import');
      await page.evaluate(async url => {
        const { Live2DModel } = await import(url), from = Live2DModel.from;
        window.__models = []; window.__gates = [];
        Live2DModel.from = async function(...args) {
          const row = { delivered: false, destroyCalls: 0 }; window.__models.push(row);
          const gate = window.__holdNext ? new Promise(resolve => window.__gates.push(resolve)) : null;
          window.__holdNext = false;
          row.model = await from.apply(this, args);
          row.internal = row.model.internalModel;
          const destroy = row.model.destroy;
          row.model.destroy = function(...opts) { row.destroyCalls++; return destroy.apply(this, opts); };
          if (gate) await gate;
          row.delivered = true; return row.model;
        };
        window.__tickerRows = () => { const rows = []; let n = window.__ticker._head.next; while (n) { rows.push({ fn: n.fn, context: n.context }); n = n.next; } return rows; };
        window.__sentinelTicks = 0;
        window.__sentinel = () => window.__sentinelTicks++;
        window.__ticker.add(window.__sentinel);
        window.__baseline = window.__tickerRows();
        window.__capture = () => {
          window.__old = { model: window.__miku, app: window.__mikuApp,
            callbacks: window.__tickerRows().filter(r => !window.__baseline.some(b => b.fn === r.fn && b.context === r.context)) };
        };
        window.__cleanupEvidence = () => ({
          destroyed: !!window.__old.model.destroyed, renderer: !!window.__old.app.renderer,
          internalDestroyed: !!window.__old.model.internalModel.destroyed,
          coreReleased: !window.__old.model.internalModel.coreModel,
          oldCallbacks: window.__old.callbacks.filter(r => window.__tickerRows().some(b => b.fn === r.fn && b.context === r.context)).length,
          debugKeys: ['__miku', '__mikuApp', '__mikuState', '__mikuForm'].filter(k => k in window),
          timeouts: window.__resources.timeout.size, intervals: window.__resources.interval.size, rafs: window.__resources.raf.size,
          listeners: window.__resources.listeners.filter(r => r.active).map(r => r.type), sharedStarted: window.__ticker.started,
          destroyCalls: window.__models.find(r => r.model === window.__old.model).destroyCalls,
        });
      }, modelURL);
      await toggle(); await ready(); await page.waitForTimeout(1300);
      await run('real pixels and persistent interactions', async () => {
        const rendered = await page.evaluate(() => {
          const app = window.__mikuApp, gl = app.renderer.gl; app.renderer.render(app.stage);
          const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
          gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
          return { textures: window.__miku.textures.length, parameters: window.__miku.internalModel.coreModel.getParameterCount(), opaque: pixels.filter((v, i) => i % 4 === 3 && v > 60).length };
        });
        assert.equal(rendered.textures, 6); assert.equal(rendered.parameters, 141); assert(rendered.opaque > 1000);
        const clickZone = async label => {
          const z = page.locator('.zone-debug').filter({ hasText: label }).first();
          await z.waitFor(); const b = await z.boundingBox();
          const point = await page.evaluate(box => {
            const app = window.__mikuApp, gl = app.renderer.gl, r = app.view.getBoundingClientRect(), res = app.renderer.resolution;
            app.renderer.render(app.stage); const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, pixels = new Uint8Array(w*h*4);
            gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
            const candidates=[];
            for(let y=Math.max(box.y+2,2);y<Math.min(box.y+box.height-2,innerHeight-2);y+=2)for(let x=Math.max(box.x+2,2);x<Math.min(box.x+box.width-2,innerWidth-2);x+=2){
              const px=Math.floor((x-r.x)*res),py=Math.floor((y-r.y)*res);
              if(pixels[((h-1-py)*w+px)*4+3]>200&&document.elementFromPoint(x,y)?.closest('.live2d-host')) candidates.push({x,y});
            }
            return candidates.sort((a,b)=>Math.hypot(a.x-box.x-box.width/2,a.y-box.y-box.height/2)-Math.hypot(b.x-box.x-box.width/2,b.y-box.y-box.height/2))[0];
          },b);
          assert(point, `visible alpha in ${label}`); await page.mouse.click(point.x,point.y);
        };
        await clickZone('手臂'); assert.equal(await page.evaluate(() => window.__mikuState().faceExpr), '比心');
        await page.locator('.live2d-host canvas').dispatchEvent('pointerleave');
        assert.equal(await page.evaluate(() => window.__mikuState().faceExpr), '比心');
        await clickZone('头'); await page.waitForFunction(() => window.__mikuForm() === 1);
        assert.equal(await page.evaluate(() => window.__mikuState().faceExpr), '比心');
        await page.screenshot({ path: out + `/chibi-${width}.png` });
        await clickZone('头'); await page.waitForFunction(() => window.__mikuForm() === 0);
        await page.screenshot({ path: out + `/nightfall-${width}.png` }); return rendered;
      });
      await run('theme replacement destroys old owner', async () => {
        await page.evaluate(() => window.__capture());
        await page.getByRole('button', { name: '主页设置', exact: true }).click();
        await page.getByRole('button', { name: /经典.*夜色星空/ }).click(); await page.keyboard.press('Escape');
        await page.waitForFunction(() => window.__miku && window.__miku !== window.__old.model);
        await page.waitForTimeout(1300); await page.screenshot({ path: out + `/classic-${width}.png` });
        const e = await page.evaluate(() => window.__cleanupEvidence());
        assert(e.destroyed && e.internalDestroyed && e.coreReleased, JSON.stringify(e)); assert.equal(e.oldCallbacks, 0); assert.equal(e.destroyCalls, 1); assert(!e.renderer); return e;
      });
      await run('off releases model callbacks timers listeners debug', async () => {
        await page.evaluate(() => window.__capture());
        await page.getByRole('button', { name: '主页设置', exact: true }).click();
        // Exercise the actual idle interval, then unmount with both the five-second hover
        // recovery and half-second long press still queued (no delayed UI click race).
        await page.evaluate(() => {
          document.querySelector('.live2d-host canvas').dispatchEvent(new PointerEvent('pointerleave'));
          window.__dateNow = Date.now; Date.now = () => window.__dateNow() + 31000;
        });
        await page.waitForFunction(() => window.__mikuState().idleActive);
        await page.evaluate(() => { Date.now = window.__dateNow; });
        await page.keyboard.press('Escape');
        const pendingBeforeOff = await page.evaluate(async () => {
          const {homeSettings} = await import('/src/modules/home/settings.ts');
          const app=window.__mikuApp, gl=app.renderer.gl, r=app.view.getBoundingClientRect(), res=app.renderer.resolution;
          app.renderer.render(app.stage);const w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,pixels=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
          let point;for(let y=2;y<h-2&&!point;y+=2)for(let x=2;x<w-2;x+=2)if(pixels[((h-1-y)*w+x)*4+3]>200){point={clientX:r.x+x/res,clientY:r.y+y/res};break;}
          // Deliberate lifecycle probe: synchronously queue both timers then unmount.
          // Native UI interaction is covered above and in live2d-layer.mjs.
          const host=document.querySelector('.live2d-host');host.dispatchEvent(new PointerEvent('pointermove',point));host.dispatchEvent(new PointerEvent('pointerdown',point));
          const pending=window.__resources.timeout.size;homeSettings.live2d=false;return pending;
        });
        assert.equal(pendingBeforeOff, 2, 'hover and long-press timers really pending');
        await page.keyboard.press('Escape'); await page.waitForTimeout(1200);
        const e = await page.evaluate(() => window.__cleanupEvidence());
        e.pendingBeforeOff = pendingBeforeOff;
        assert(e.destroyed && e.internalDestroyed && e.coreReleased, JSON.stringify(e)); assert(!e.renderer); assert.equal(e.oldCallbacks, 0); assert.equal(e.destroyCalls, 1);
        assert.deepEqual(e.debugKeys, []); assert.equal(e.timeouts + e.intervals + e.rafs, 0, JSON.stringify(e)); assert.deepEqual(e.listeners, []); assert(e.sharedStarted);
        return e;
      });
      await run('repeated toggle leaves shared ticker intact', async () => {
        const evidence = [];
        for (let i = 0; i < 3; i++) {
          await toggle(); await ready(); await page.evaluate(() => window.__capture());
          await toggle(); await page.waitForTimeout(950);
          const e = await page.evaluate(() => window.__cleanupEvidence()); evidence.push(e);
          assert(e.destroyed, JSON.stringify(e)); assert.equal(e.oldCallbacks, 0); assert.equal(e.destroyCalls, 1);
          assert.deepEqual(e.debugKeys, []); assert.equal(e.timeouts + e.intervals + e.rafs, 0);
        }
        const before = await page.evaluate(() => window.__sentinelTicks); await page.waitForTimeout(200);
        assert(await page.evaluate(() => window.__sentinelTicks) > before); return evidence;
      });
      await run('pending real model resolves after new owner mounts', async () => {
        await page.evaluate(() => { window.__holdNext = true; window.__pendingIndex = window.__models.length; });
        await toggle();
        await page.waitForFunction(() => window.__models[window.__pendingIndex]?.model);
        await toggle(); await toggle(); await ready();
        const newer = await page.evaluate(() => { window.__newOwner = window.__miku; window.__gates.shift()(); return window.__models.length; });
        await page.waitForFunction(() => window.__models[window.__pendingIndex]?.delivered); await page.waitForTimeout(1000);
        const e = await page.evaluate(() => ({ destroyed: window.__models[window.__pendingIndex].model.destroyed,
          destroyCalls: window.__models[window.__pendingIndex].destroyCalls,
          ownerPreserved: window.__miku === window.__newOwner, currentAlive: !window.__newOwner.destroyed,
          canvases: document.querySelectorAll('.live2d-host canvas').length, models: window.__models.length }));
        assert(e.destroyed, JSON.stringify(e)); assert.equal(e.destroyCalls, 1); assert(e.ownerPreserved && e.currentAlive); assert.equal(e.canvases, 1); assert.equal(e.models, newer);
        return e;
      });
      await run('route departure clears all owners', async () => {
        await page.evaluate(() => window.__capture());
        // Router link is a real App navigation, not page destruction.
        await page.locator('.sidebar a[href="/apps/qa-drive"]').evaluate(el => el.click());
        await page.waitForURL(MAIN + '/apps/qa-drive'); await page.waitForTimeout(1100);
        const e = await page.evaluate(() => ({ ...window.__cleanupEvidence(), allDestroyed: window.__models.every(r => r.model?.destroyed) }));
        assert(e.destroyed && e.allDestroyed, JSON.stringify(e)); assert.deepEqual(e.debugKeys, []);
        assert.equal(e.oldCallbacks, 0); assert.equal(e.timeouts + e.intervals + e.rafs, 0); assert.deepEqual(e.listeners, []); return e;
      });
      await run('network load completes only after route unmount', async () => {
        holdMoc = true; mocRequested = false; mocGate = new Promise(resolve => { releaseMoc = resolve; });
        await page.evaluate(() => { window.__pendingIndex = window.__models.length; });
        await page.locator('.sidebar a[href="/"]').evaluate(el => el.click());
        await page.waitForURL(MAIN + '/');
        await page.waitForFunction(() => window.__models.length > window.__pendingIndex);
        for (let i = 0; i < 100 && !mocRequested; i++) await page.waitForTimeout(20);
        assert(mocRequested, 'real moc3 HTTP request held');
        assert.equal(await page.evaluate(() => !!window.__models[window.__pendingIndex].model), false);
        await page.locator('.sidebar a[href="/apps/qa-drive"]').evaluate(el => el.click());
        await page.waitForURL(MAIN + '/apps/qa-drive'); await page.waitForTimeout(100);
        releaseMoc();
        await page.waitForFunction(() => window.__models[window.__pendingIndex]?.delivered);
        await page.waitForTimeout(1000);
        const e = await page.evaluate(() => ({ allDestroyed: window.__models.every(r => r.model?.destroyed),
          lateDestroyCalls: window.__models[window.__pendingIndex].destroyCalls,
          debugKeys: ['__miku', '__mikuApp', '__mikuState', '__mikuForm'].filter(k => k in window),
          extraTickerCallbacks: window.__tickerRows().filter(r => !window.__baseline.some(b => b.fn === r.fn && b.context === r.context)).length,
          timers: window.__resources.timeout.size + window.__resources.interval.size + window.__resources.raf.size,
          canvases: document.querySelectorAll('.live2d-host canvas').length }));
        assert(e.allDestroyed, JSON.stringify(e)); assert.equal(e.lateDestroyCalls, 1); assert.deepEqual(e.debugKeys, []);
        assert.equal(e.extraTickerCallbacks, 0); assert.equal(e.timers, 0); assert.equal(e.canvases, 0); return e;
      });
      await run('old mounted owner cannot clear newer debug handles or textures', async () => {
        const vueURL = transformed.code.match(/from\s+["']([^"']*\/vue[^"']*)["']/)?.[1];
        assert(vueURL);
        await page.evaluate(async url => {
          const { createApp } = await import(url), { default: Widget } = await import('/src/modules/home/Live2dWidget.vue');
          window.__mountWidget = () => {
            const el = document.createElement('div'); el.style.cssText = 'width:360px;height:600px;position:fixed;left:0;top:0'; document.body.append(el);
            const app = createApp(Widget); app.mount(el); return () => { app.unmount(); el.remove(); };
          };
          window.__unmountFirst = window.__mountWidget();
        }, vueURL);
        await ready(); await page.evaluate(() => { window.__firstOwner = window.__miku; window.__unmountSecond = window.__mountWidget(); });
        await page.waitForFunction(() => window.__miku && window.__miku !== window.__firstOwner);
        const e = await page.evaluate(() => {
          const keys = ['__miku', '__mikuApp', '__mikuState', '__mikuForm'];
          const handles = keys.map(k => window[k]); window.__unmountFirst(); window.__unmountFirst();
          const app = window.__mikuApp; app.renderer.render(app.stage);
          const gl = app.renderer.gl, pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
          gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
          const evidence = { oldDestroyed: window.__firstOwner.destroyed, handlesPreserved: keys.every((k, i) => window[k] === handles[i]),
            newerAlive: !window.__miku.destroyed, texturesValid: window.__miku.textures.every(t => t.valid),
            opaque: pixels.filter((v, i) => i % 4 === 3 && v > 60).length };
          window.__unmountSecond(); window.__unmountSecond();
          evidence.allDestroyedOnce = window.__models.every(r => r.model.destroyed && r.destroyCalls === 1);
          evidence.debugKeys = keys.filter(k => k in window); return evidence;
        });
        assert(e.oldDestroyed && e.handlesPreserved && e.newerAlive && e.texturesValid && e.allDestroyedOnce, JSON.stringify(e));
        assert(e.opaque > 1000); assert.deepEqual(e.debugKeys, []); return e;
      });
    } catch (e) { report.failures.push({ name: `setup ${width}`, error: e.stack }); }
    releaseRuntime(); releaseMoc?.();
    report.cases.push({ width, fetched, unknown: h.unknown, errors: h.errors, consoleErrors: h.consoleErrors, lifecycleWarnings });
    if (h.unknown.length || h.errors.length || h.consoleErrors.length || lifecycleWarnings.length) report.failures.push({ name: `diagnostics ${width}`, unknown: h.unknown, errors: h.errors, consoleErrors: h.consoleErrors, lifecycleWarnings });
    await context.close();
  }
} finally {
  await browser?.close(); await server.close(); fs.rmSync(harness, { force: true });
  fs.writeFileSync(out + '/report.json', JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
if (report.failures.length) process.exitCode = 1;
