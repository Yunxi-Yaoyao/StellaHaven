import { test, expect, chromium } from '@playwright/test';
import type { Browser, Page } from '@playwright/test';
let browser: Browser;
let page: Page;
let saved: any[];
const baseURL = process.env.STELLA_TEST_URL || 'http://127.0.0.1:5173';
const original = '---\ntitle: preserved\n---\n\n# 富文本验收\n\n你好 **Stella**\n\n[[目标页]]\n\n- [ ] 待办\n\n| 名称 | 值 |\n| --- | --- |\n| A | B |\n\n```mermaid\ngraph TD; A-->B\n```\n\n<div data-raw="keep">保留 HTML</div>\n';
test.beforeAll(async () => { browser = await chromium.launch({ executablePath: '/usr/sbin/google-chrome-stable', args: ['--no-sandbox'], headless: true }); });
test.afterAll(async () => { await browser?.close(); });
test.beforeEach(async () => {
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); saved = [];
  const doc: any = { id: 'doc-a', title: '编辑验收', file_path: '/test.md', workspace_id: 'ws-a', parent_id: null, content: original, updated_at: '2026-09-08T06:00:00Z', created_at: '2026-09-08T06:00:00Z', has_draft: false, status: 'published', is_folder: false, is_favorite: false, is_pinned: false };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); const p = url.pathname;
    if (url.hostname !== new URL(baseURL).hostname) return route.abort();
    const fulfill = (body: any) => route.fulfill({ json: body });
    if (p === '/auth/me' || p === '/auth/refresh') return fulfill({ id: 'user-a', username: 'test', display_name: '验收账号', role: 'admin', is_admin: true });
    if (p.startsWith('/workspaces/')) return fulfill(p === '/workspaces/' ? [{ id: 'ws-a', name: '验收工作区', user_id: 'user-a' }] : { id: 'ws-a', name: '验收工作区' });
    if (p === '/documents/doc-a') {
      if (route.request().method() === 'PUT') { const payload = route.request().postDataJSON(); saved.push(payload); Object.assign(doc, payload); }
      return fulfill(doc);
    }
    if (p === '/documents/') return fulfill([{ ...doc, content: undefined }]);
    if (p.startsWith('/documents/') || p.startsWith('/tags/') || p.startsWith('/doc-tags/') || p.startsWith('/attachments/') || p.startsWith('/document-links/')) return fulfill([]);
    if (p === '/auth/sessions') return fulfill([]);
    if (p.startsWith('/auth/') || p.startsWith('/api/')) return fulfill({});
    return route.continue();
  });
  await page.addInitScript(() => { localStorage.clear(); localStorage.setItem('stella_bootstrap', JSON.stringify({ userId:'user-a', workspaceId:'ws-a' })); });
  page.on('pageerror', e => console.log('PAGE_ERROR:', e.message));
  await page.goto(`${baseURL}/notes`);
  await expect(page.getByText('编辑验收', { exact: true }).first()).toBeVisible();
});
test.afterEach(async () => { await page?.close(); });
test('rich/source mode switching does not save or normalize untouched Markdown', async () => {
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByRole('button', { name: '所见即所得', exact: true })).toBeVisible();
  await expect(page.locator('.rich-editor .ProseMirror')).toBeVisible();
  await page.getByRole('button', { name: 'Markdown', exact: true }).click();
  await expect(page.locator('.input-wrap > .cm-host .cm-editor')).toBeVisible();
  await page.getByRole('button', { name: '所见即所得', exact: true }).click();
  await page.keyboard.press('Control+s');
  await page.waitForTimeout(250);
  expect(saved).toEqual([]);
});
test('rich edits save Markdown retaining opaque regions, wiki and code', async () => {
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const editor = page.locator('.rich-editor .ProseMirror');
  await expect(editor).toBeVisible();
  await editor.locator('h1').click();
  await page.keyboard.press('End'); await page.keyboard.type(' edited');
  await page.keyboard.press('Control+s');
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0].content).toContain('edited');
  expect(saved[0].content).toContain('title: preserved');
  expect(saved[0].content).toContain('[[目标页]]');
  expect(saved[0].content).toContain('graph TD; A-->B');
  expect(saved[0].content).toContain('<div data-raw="keep">保留 HTML</div>');
  await page.screenshot({ path: '/tmp/stella-rich-editor.png', fullPage: true });
});

test('leaving rich edit for reading saves once without losing text', async () => {
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const editor = page.locator('.rich-editor .ProseMirror');
  await editor.locator('h1').click(); await page.keyboard.press('End'); await page.keyboard.type(' boundary');
  await page.getByRole('button', { name: '阅览', exact: true }).click();
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0].content).toContain('boundary');
});

test('pasted image uploads to this note and inserts at the rich cursor', async () => {
  let uploads = 0;
  await page.route('**/attachments/doc-a', route => { uploads++; return route.fulfill({ json: { url: '/attachments/11111111-1111-1111-1111-111111111111', filename: 'paste.png' } }); });
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const editor = page.locator('.rich-editor .ProseMirror');
  await editor.locator('h1').click(); await page.keyboard.press('End');
  await editor.evaluate(el => {
    const dt = new DataTransfer(); dt.items.add(new File(['image'], 'paste.png', {type:'image/png'}));
    el.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dt }));
  });
  await expect.poll(() => uploads).toBe(1);
  await expect(editor.locator('img[src]')).toHaveAttribute('src', '/attachments/11111111-1111-1111-1111-111111111111');
  await page.keyboard.press('Control+s');
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0].content.indexOf('![paste.png]')).toBeGreaterThan(saved[0].content.indexOf('# 富文本验收'));
  expect(saved[0].content.indexOf('![paste.png]')).toBeLessThan(saved[0].content.indexOf('你好'));
});

async function recordImports() {
  const created: any[] = [], finalized: any[] = [];
  let attachments = 0;
  await page.route('**/documents/', route => {
    if (route.request().method() !== 'POST') return route.fallback();
    const payload = route.request().postDataJSON(); created.push(payload);
    return route.fulfill({ status: 201, json: { ...payload, id: `created-${created.length}` } });
  });
  await page.route('**/documents/import/finalize', route => {
    const body = route.request().postDataJSON(); finalized.push(body);
    return route.fulfill({ json: { synced: body.document_ids.length } });
  });
  await page.route('**/attachments/doc-a', route => { attachments++; return route.fulfill({ json: {} }); });
  return { created, finalized, get attachments() { return attachments; } };
}
test('picker imports md and txt as private separate notes without overwriting names', async () => {
  const calls = await recordImports();
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '导入 .md / .txt' }).click();
  await (await chooser).setFiles([
    { name: '编辑验收.md', mimeType: 'text/markdown', buffer: Buffer.from('# 保留标题\n\n**内容**\n') },
    { name: '文本.txt', mimeType: 'text/plain', buffer: Buffer.from('# 不是标题\n<script>alert(1)</script>') },
  ]);
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: '导入 2 篇', exact: true }).click();
  await expect.poll(() => calls.created.length).toBe(2);
  expect(calls.created[0].title).not.toBe('编辑验收');
  expect(calls.created[0].content).toBe('# 保留标题\n\n**内容**\n');
  expect(calls.created[1].content).toContain('\\# 不是标题');
  for (const item of calls.created) { expect(item.parent_id).toBeNull(); expect(item.workspace_id).toBe('ws-a'); expect(item.visibility).toBe('private'); }
  await expect.poll(() => calls.finalized.length).toBe(1);
  expect(calls.attachments).toBe(0); expect(saved).toEqual([]);
  await page.screenshot({ path: '/tmp/stella-note-import.png', fullPage: true });
});
test('dropping md into rich draft imports separately and does not upload or replace draft', async () => {
  const calls = await recordImports();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const editor = page.locator('.rich-editor .ProseMirror');
  await editor.locator('h1').click(); await page.keyboard.press('End'); await page.keyboard.type(' unsaved');
  await editor.evaluate(el => {
    const dt = new DataTransfer(); dt.items.add(new File(['# 独立新笔记'], '拖拽.md', { type: 'text/markdown' }));
    el.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
  });
  await page.getByRole('button', { name: '导入 1 篇', exact: true }).click();
  await expect.poll(() => calls.created.length).toBe(1);
  expect(calls.created[0].content).toBe('# 独立新笔记');
  expect(calls.attachments).toBe(0); expect(saved).toEqual([]);
  await expect(page.getByRole('button', { name: '完成', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '完成', exact: true }).click();
  await expect(editor.locator('h1')).toContainText('unsaved');
});
test('dropping md on a tree row selects it as parent', async () => {
  const calls = await recordImports();
  await page.locator('[data-import-parent="doc-a"]').evaluate(el => {
    const dt = new DataTransfer(); dt.items.add(new File(['child'], 'child.md', { type: 'text/markdown' }));
    el.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
  });
  await page.getByRole('button', { name: '导入 1 篇', exact: true }).click();
  await expect.poll(() => calls.created.length).toBe(1);
  expect(calls.created[0].parent_id).toBe('doc-a');
});

test('import button accepts OS drop with visible feedback and real item progress', async () => {
  const calls = await recordImports();
  let release!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/documents/', async route => {
    if (route.request().method() === 'POST') await hold;
    return route.fallback();
  });
  const button = page.locator('.import-btn');
  await button.evaluate(el => {
    const dt = new DataTransfer(); dt.items.add(new File(['# dropped'], 'button.md', { type: 'text/markdown' }));
    (window as any).__importDrop = dt;
    el.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt }));
    el.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
  });
  await expect(button).toContainText('松手');
  await button.evaluate(el => el.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: (window as any).__importDrop })));
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: '导入 1 篇', exact: true }).click();
  await expect(page.locator('.import-row[data-status="importing"]')).toBeVisible();
  const progress = page.getByRole('progressbar', { name: '文件导入进度' });
  await expect(progress).toHaveAttribute('value', '0');
  await expect(page.getByRole('dialog')).toContainText('正在导入：button.md');
  await page.screenshot({ path: '/tmp/stella-import-progress.png', fullPage: true });
  release();
  await expect.poll(() => calls.created.length).toBe(1);
  await expect(progress).toHaveAttribute('value', '1');
});

test('returning to notes restores the same editor before background requests finish', async () => {
  await page.setViewportSize({ width:1440, height:650 });
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const editor = page.locator('.rich-editor .ProseMirror');
  await editor.locator('h1').click(); await page.keyboard.press('End'); await page.keyboard.type(' persisted');
  await editor.evaluate(el => { (window as any).__cachedEditor = el; const scroller = el.closest('.rich-editor')!; scroller.scrollTop = 90; });
  expect(await editor.evaluate(el => el.closest('.rich-editor')!.scrollTop)).toBeGreaterThan(0);
  await page.locator('a[href="/settings"]').first().click();
  await expect(page).toHaveURL(/settings/);
  await expect.poll(() => saved.length).toBe(1);
  await page.route('**/documents/**', async route => { await new Promise(r => setTimeout(r, 1600)); return route.fallback(); });
  const start = Date.now();
  await page.locator('a[href="/notes"]').first().click();
  await expect(editor).toBeVisible({ timeout: 800 });
  await expect(editor.locator('h1')).toContainText('persisted');
  expect(await editor.evaluate(el => el === (window as any).__cachedEditor)).toBe(true);
  expect(await editor.evaluate(el => el.closest('.rich-editor')!.scrollTop)).toBeGreaterThan(0);
  console.log('NOTES_RETURN_MS', Date.now() - start);
  expect(Date.now() - start).toBeLessThan(1000);
  await expect(page.getByText('Stella 正在醒来…', { exact:true })).toHaveCount(0);
});
test('slow tags and recent activity do not block note contents on first visit', async () => {
  await page.route('**/tags/**', async route => { await new Promise(r => setTimeout(r, 2200)); return route.fallback(); });
  await page.route('**/documents/recent**', async route => { await new Promise(r => setTimeout(r, 2200)); return route.fallback(); });
  await page.reload();
  await expect(page.locator('.title-readonly')).toHaveText('编辑验收', { timeout: 1100 });
  await expect(page.getByText('Stella 正在醒来…', { exact:true })).toHaveCount(0);
});

test('account change evicts cached notes instead of showing previous user content', async () => {
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.locator('.rich-editor .ProseMirror')).toBeVisible();
  await page.locator('.rich-editor').evaluate(el => { (window as any).__cachedRichInstance = (el as any).__vueParentComponent; });
  await page.locator('a[href="/settings"]').first().click();
  await page.evaluate(async () => { const path = '/src/modules/home/auth.ts'; const { auth } = await import(path); auth.me = null; });
  await expect.poll(() => page.evaluate(() => (window as any).__cachedRichInstance.isUnmounted)).toBe(true);
  await expect(page.locator('.notes-page')).toHaveCount(0);
});
