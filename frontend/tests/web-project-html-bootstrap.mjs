// Real Chromium, synthetic HTTPS fulfillment only; no app server or DB.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const [specPath, output] = process.argv.slice(2);
const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
const prefix = `${spec.target}/p/${spec.cap}/`;
const browser = await chromium.launch({ executablePath: '/usr/sbin/google-chrome-stable', headless: true,
  args: ['--no-sandbox', '--disable-background-networking', '--host-resolver-rules=MAP * ~NOTFOUND'] });
const results = [];
try {
  for (const [entry, key] of Object.entries(spec.cases)) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [], requests = [], unexpected = [], consoleErrors = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
    await context.route('**/*', async route => {
      const url = route.request().url(); requests.push(url);
      if (url === spec.source + '/') {
        return route.fulfill({ contentType: 'text/html', body: `<!doctype html><script>window.messages=[];addEventListener('message',e=>messages.push({origin:e.origin,data:e.data}));</script><iframe id="p" sandbox="allow-scripts" src="${prefix}${entry}"></iframe>` });
      }
      const response = url.startsWith(prefix) && spec.responses[url.slice(prefix.length)];
      if (response) return route.fulfill({ status: 200, contentType: response.mime, headers: response.headers, body: Buffer.from(response.body, 'base64') });
      unexpected.push(url); return route.abort();
    });
    let snapshot, messages, failure;
    try {
      await page.goto(spec.source + '/');
      const frame = page.frames().find(f => f.url() === prefix + entry);
      assert.ok(frame, 'project frame loaded');
      snapshot = await frame.evaluate(() => {
        let nativeBlocked = false;
        try { void window.sessionStorage; } catch (e) { nativeBlocked = e.name === 'SecurityError'; }
        const box = document.querySelector('#box');
        const image = document.querySelector('#asset');
        return { observed: window.observed, mode: document.compatMode, doctype: document.doctype?.name,
          nativeBlocked, relativeValue: window.relativeValue, base: document.baseURI,
          cssColor: box && getComputedStyle(box).color, cssImage: box && getComputedStyle(box).backgroundImage,
          imageSize: image && [image.naturalWidth, image.naturalHeight],
          scripts: [...document.scripts].map(s => ({src:s.src, text:s.textContent})) };
      });
      // postMessage task delivery can trail the frame load event.
      await page.waitForFunction(() => messages.some(m => m.data.type === 'stella-project-storage'), undefined, { timeout: 1500 }).catch(() => {});
      messages = await page.evaluate(() => window.messages);
      assert.equal(snapshot.observed, key + ':restored');
      assert.equal(snapshot.mode, 'CSS1Compat');
      assert.equal(snapshot.doctype, 'html');
      assert.equal(snapshot.nativeBlocked, true, 'opaque sandbox remains enforced');
      assert.equal(snapshot.base, prefix + entry, 'entry URL base is unchanged');
      assert.equal(requests.filter(u => u === prefix + '__stella_storage.js').length, 1);
      assert.deepEqual(messages.map(m => m.data.type), ['stella-project-ready', 'stella-project-storage']);
      assert.ok(messages.every(m => m.origin === 'null' && m.data.capability === spec.cap));
      assert.equal(messages[1].data.data[key], 'restored');
      assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(unexpected, []);
      if (key === 'nested') {
        assert.equal(snapshot.relativeValue, 'relative-ok');
        assert.equal(snapshot.cssColor, 'rgb(12, 34, 56)');
        assert.equal(snapshot.cssImage, `url("${prefix}nested/assets/pixel.svg")`);
        assert.deepEqual(snapshot.imageSize, [2, 3]);
        for (const name of ['nested/scripts/app.mjs', 'nested/scripts/lib/value.mjs', 'nested/assets/site.css', 'nested/assets/pixel.svg']) assert.ok(requests.includes(prefix + name), name);
      }
    } catch (error) { failure = String(error); }
    results.push({ entry, pass: !failure, failure, snapshot, messages, errors, consoleErrors, requests, unexpected });
    await page.screenshot({ path: path.join(output, entry.replaceAll('/', '_') + '.png') });
    await context.close();
  }
} finally { await browser.close(); }
const report = { evidence: 'Real Chromium opaque sandbox/CSP/script/URL behavior; synthetic HTTPS route.fulfill, source-extracted runtime with stub grant/read_file. No PG, login, API, TLS backend or production acceptance.', runtime_sha256: spec.runtime_sha256, results };
fs.writeFileSync(path.join(output, 'browser-evidence.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (results.some(r => !r.pass)) process.exitCode = 1;
