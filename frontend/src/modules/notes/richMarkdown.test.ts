/// <reference types="node" />
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { RichMarkdownSession } from './richMarkdown.ts';
import { chromium } from '@playwright/test';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';

// Real browser and Vue SFC transformed by Vite, never a cached optimizer URL.
async function browserHarness(t: import('node:test').TestContext) {
  const server = await createServer({ configFile: false, appType: 'custom', plugins: [vue()], server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  t.after(() => server.close());
  server.middlewares.use('/__rich_test', async (_req, res, next) => {
    try {
      const html = await server.transformIndexHtml('/__rich_test', `<div id="app"></div><script type="module">
        import { createApp, h, ref, nextTick } from 'vue';
        import RichEditor from '/src/modules/notes/RichEditor.vue';
        const source = ref('# Original\\n\\n[[页面]]\\n'), id = ref('a'), visible = ref(true), editor = ref();
        const events = [], ready = [];
        createApp({ setup: () => () => h(RichEditor, { ref: editor, modelValue: source.value, docId: id.value,
          style: { display: visible.value ? '' : 'none' },
          'onUpdate:modelValue': v => { events.push(v); source.value = v; }, onReady: () => ready.push(true) }) }).mount('#app');
        window.richTest = { source, id, visible, editor, events, ready, nextTick };
      </script>`);
      res.setHeader('Content-Type', 'text/html'); res.end(html);
    } catch (error) { next(error); }
  });
  await server.listen();
  const address = server.httpServer!.address() as { port: number };
  const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/usr/sbin/google-chrome-stable', args: ['--no-sandbox'] });
  t.after(() => browser.close());
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${address.port}/__rich_test`);
  const evaluate = (expression: string) => page.evaluate<any>(expression);
  const wait = async (expression: string) => {
    try { await page.waitForFunction(expression, undefined, { timeout: 25000 }); }
    catch (error) { throw new Error(`${error}; browser errors: ${errors.join('; ')}; DOM: ${await page.locator('body').innerText()}`); }
  };
  return { evaluate, wait, page, close: () => browser.close() };
}

test('real Vue editor preserves untouched source, hides without reset, emits only edits', { timeout: 90000 }, async t => {
  const browser = await browserHarness(t);
  try {
    await browser.wait('window.richTest?.ready.length === 1');
    assert.equal(await browser.evaluate('richTest.editor.value.flush()'), '# Original\n\n[[页面]]\n');
    assert.equal(await browser.evaluate('richTest.events.length'), 0);
    assert.equal(await browser.evaluate('!!document.querySelector(".ProseMirror h1")'), true);
    await browser.evaluate('richTest.visible.value = false; richTest.nextTick()');
    await browser.evaluate('richTest.visible.value = true; richTest.nextTick()');
    assert.equal(await browser.evaluate('richTest.events.length'), 0);
    await browser.evaluate('richTest.editor.value.insertText("**added** ")');
    assert.equal(await browser.evaluate('richTest.events.length'), 1);
    assert.match(await browser.evaluate('richTest.editor.value.flush()'), /\*\*added\*\*/);
    assert.match(await browser.evaluate('richTest.editor.value.flush()'), /\[\[页面\]\]/);
  } finally { await browser.close(); }
});

test('untouched source is returned byte-for-byte and external updates are silent', () => {
  const session = new RichMarkdownSession('a', '# A\r\n\r\n[[page]]\r\n');
  assert.equal(session.flush(), '# A\r\n\r\n[[page]]\r\n');
  const revision = session.revision;
  assert.equal(session.accept('a', 'new source'), true);
  assert.equal(session.flush(), 'new source');
  assert.equal(session.userEdit(revision, 'stale'), undefined);
  assert.equal(session.flush(), 'new source');
  assert.equal(session.userEdit(session.revision, 'edited'), 'edited');
  assert.equal(session.accept('a', 'edited'), false);
  assert.equal(session.userEdit(session.revision, 'edited'), undefined);
  assert.equal(session.accept('b', 'edited'), true);
});

test('real Crepe preservation and safety regressions', { timeout: 90000 }, async t => {
  const b = await browserHarness(t);
  await b.wait('window.richTest?.ready.length === 1');
  const load = async (source: string) => {
    await b.evaluate(`richTest.source.value = ${JSON.stringify(source)}; richTest.nextTick()`);
    assert.equal(await b.evaluate('richTest.editor.value.flush()'), source);
  };
  await t.test('frontmatter, references, HTML, mermaid, code metadata survive unrelated edits', async () => {
    const preserved = ['---\ntitle: test\n---', '[[页面|标签]]', '```mermaid\ngraph TD; A-->B\n```',
      '<img src=x onerror="window.__executed = true">', '[ref]: https://example.com',
      '```js title="sample"\nconst x = 1\n```', '> quote\n> second', '- [x] done',
      '| a | b |\n| - | - |\n| c | d |', '[^note]: footnote text'];
    const source = '# Editable\n\n' + preserved.slice(1).join('\n\n');
    await load(preserved[0] + '\n\n' + source);
    await b.page.locator('.ProseMirror h1').click();
    await b.page.keyboard.press('End'); await b.page.keyboard.insertText(' changed');
    const output = await b.evaluate('richTest.editor.value.flush()');
    for (const raw of preserved) assert.ok(output.includes(raw), raw);
    assert.equal(await b.evaluate('window.__executed'), undefined);
    assert.equal(await b.page.locator('.ProseMirror img[onerror]').count(), 0);
  });
  await t.test('equal-looking untouched blocks retain their own source spelling', async () => {
    await load('# Editable\n\n# Same\n\nSame\n====');
    await b.page.locator('.ProseMirror h1').first().click();
    await b.page.keyboard.press('End'); await b.page.keyboard.insertText(' changed');
    const output = await b.evaluate('richTest.editor.value.flush()');
    assert.ok(output.includes('Same\n===='), output);
  });
  await t.test('heading navigation selects the visible rich heading', async () => {
    await load('# First\n\n## Destination');
    assert.equal(await b.evaluate('richTest.editor.value.scrollToHeading?.("Destination")'), true);
    assert.equal(await b.page.evaluate(() => window.getSelection()?.anchorNode?.parentElement?.closest('h2')?.textContent), 'Destination');
  });
  await t.test('newly typed wiki link remains literal', async () => {
    await load('# Wiki'); await b.page.locator('.ProseMirror h1').click();
    await b.page.keyboard.press('End'); await b.page.keyboard.insertText(' [[new page]]');
    assert.match(await b.evaluate('richTest.editor.value.flush()'), /\[\[new page\]\]/);
  });
  await t.test('soft newlines render as visible breaks', async () => {
    await load('first line\nsecond line');
    assert.ok(await b.page.locator('.ProseMirror p br').count() >= 1);
  });
  await t.test('external replacement is silent and a doc switch replaces the real DOM', async () => {
    const count = await b.evaluate('richTest.events.length');
    await load('# External');
    await b.evaluate('richTest.id.value = "other"; richTest.source.value = "# Other document"; richTest.nextTick()');
    assert.equal(await b.page.locator('.ProseMirror h1').innerText(), 'Other document');
    assert.equal(await b.evaluate('richTest.events.length'), count);
  });
  await t.test('unsafe links are never executable DOM URLs', async () => {
    await load('[bad](javascript:alert%281%29)\n\n[bad](data:text/html,test)\n\n[good](https://example.com)');
    const urls = await b.page.locator('.ProseMirror a').evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
    assert.ok(urls.includes('https://example.com'));
    assert.ok(urls.every(url => !/^(javascript|data|vbscript):/i.test(url ?? '')));
  });
  await t.test('TOML frontmatter without a blank line does not swallow following paragraph', async () => {
    await load('+++\ntitle = "test"\n+++\nBody text\n\n# Heading');
    assert.ok((await b.page.locator('.ProseMirror').innerText()).includes('Body text'));
  });
});
