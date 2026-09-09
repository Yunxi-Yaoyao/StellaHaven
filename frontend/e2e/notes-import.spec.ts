import { test, expect, chromium, type Browser, type Page } from '@playwright/test';
let browser: Browser;
let page: Page;
let creates: any[];
let finalizes: any[];
let mutations: string[];
let lists: number;
let failSecond: boolean;
let failFinalize = false;
const existing = { id: 'existing', title: 'same', file_path: '/same.md', workspace_id: 'ws-a', parent_id: null, content: '# Untouched', updated_at: '2026-09-08T06:00:00Z', created_at: '2026-09-08T06:00:00Z', has_draft: false, status: 'published', is_folder: false, is_favorite: false, is_pinned: false };
test.beforeAll(async () => { browser = await chromium.launch({ executablePath: '/usr/sbin/google-chrome-stable', args: ['--no-sandbox'], headless: true }); });
test.afterAll(async () => { await browser.close(); });
test.beforeEach(async () => {
  creates = []; finalizes = []; mutations = []; lists = 0; failSecond = false; failFinalize = false;
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const docs: any[] = [{ ...existing }];
  await page.route('**/*', async route => {
    const request = route.request(); const url = new URL(request.url()); const p = url.pathname;
    if (url.hostname !== '127.0.0.1') return route.abort();
    const ok = (json: any) => route.fulfill({ json });
    if (p === '/auth/me') return ok({ id: 'user-a', username: 'test', role: 'admin', is_admin: true });
    if (p.startsWith('/workspaces/')) return ok(p === '/workspaces/' ? [{ id: 'ws-a', name: 'Test workspace' }] : { id: 'ws-a' });
    if (p === '/documents/import/finalize') {
      finalizes.push(request.postDataJSON());
      if (failFinalize) { failFinalize = false; return route.fulfill({ status: 500, json: { detail: 'sync failed' } }); }
      return ok({ synced: finalizes.at(-1).document_ids.length });
    }
    if (p === '/documents/') {
      if (request.method() === 'POST') {
        const payload = request.postDataJSON(); creates.push(payload);
        if (payload.content === 'second' && failSecond) { failSecond = false; return route.fulfill({ status: 500, json: { detail: 'test failure' } }); }
        const doc = { ...existing, ...payload, id: `new-${creates.length}` }; docs.push(doc); return ok(doc);
      }
      lists++; return ok(docs);
    }
    if (p === '/documents/existing') { if (request.method() !== 'GET') mutations.push(request.method()); return ok(existing); }
    if (p.startsWith('/documents/') || p.startsWith('/tags/') || p.startsWith('/doc-tags/') || p.startsWith('/attachments/') || p.startsWith('/document-links/')) return ok([]);
    if (p.startsWith('/auth/') || p.startsWith('/api/')) return ok({});
    return route.continue();
  });
  await page.addInitScript(() => { localStorage.clear(); localStorage.setItem('stella_bootstrap', JSON.stringify({ userId:'user-a', workspaceId:'ws-a' })); });
  await page.goto('http://127.0.0.1:5173/notes');
  await expect(page.locator('.doc-list')).toBeVisible();
});
test.afterEach(async () => { await page.close(); });

test('sync failure is separate and retry does not recreate successful notes', async () => {
  failFinalize = true;
  await page.locator('.notes-page input[type=file]').setInputFiles({ name: 'new.md', mimeType: 'text/markdown', buffer: Buffer.from('[[same]]') });
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: '导入 1 篇' }).click();
  await expect(dialog.getByRole('alert')).toContainText('双链同步失败');
  await dialog.getByRole('button', { name: '重试双链同步' }).click();
  await expect(dialog).toContainText('双链已同步 1 篇');
  expect(creates).toHaveLength(1);
  expect(finalizes).toHaveLength(2);
  expect(finalizes[0]).toEqual(finalizes[1]);
});

test('image and PDF-only editor drops pass through without import dialog', async () => {
  await expect(page.locator('.editor')).toBeVisible();
  const reached = await page.locator('.editor').evaluate(element => {
    let reached = false;
    element.addEventListener('drop', () => { reached = true; }, { once: true });
    const transfer = new DataTransfer();
    transfer.items.add(new File(['image'], 'image.png', { type: 'image/png' }));
    transfer.items.add(new File(['pdf'], 'document.pdf', { type: 'application/pdf' }));
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }));
    return reached;
  });
  expect(reached).toBe(true);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(creates).toHaveLength(0);
});

test('picker imports with suffixes; retry finalizes prior successes without overwriting editor', async () => {
  failSecond = true;
  await page.locator('.notes-page input[type=file]').setInputFiles([
    { name: 'same.md', mimeType: 'text/markdown', buffer: Buffer.from('# Kept') },
    { name: 'same.txt', mimeType: 'text/plain', buffer: Buffer.from('second') },
    { name: 'empty.md', mimeType: 'text/markdown', buffer: Buffer.from('') },
  ]);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: '导入 3 篇' })).toBeEnabled();
  const before = lists;
  await dialog.getByRole('button', { name: '导入 3 篇' }).click();
  await expect(dialog.locator('[data-status=success]')).toHaveCount(2);
  await expect(dialog.getByRole('button', { name: '重试未成功文件' })).toBeEnabled();
  expect(lists - before).toBe(2); // one full preflight fetch + one list refresh
  expect(creates.map(p => p.title)).toEqual(['same (2)', 'same (3)', 'empty']);
  expect(creates.every(p => p.parent_id === null && p.visibility === 'private' && p.status === 'published')).toBe(true);
  expect(finalizes[0].document_ids).toEqual(['new-1', 'new-3']);
  await dialog.getByRole('button', { name: '重试未成功文件' }).click();
  await expect(dialog.locator('[data-status=success]')).toHaveCount(3);
  expect(creates).toHaveLength(4);
  expect(finalizes[1].document_ids).toEqual(['new-1', 'new-4', 'new-3']);
  expect(mutations).toEqual([]);
  await dialog.getByRole('button', { name: '完成', exact: true }).click();
  await expect(page.locator('.editor')).toContainText('Untouched');
});

for (const [selector, parent] of [['.doc-list .row', 'existing'], ['.doc-list .items', null], ['.editor', null]] as const) {
  test(`drop on ${selector} selects explicit ${parent ?? 'root'} target and rejects mixed unsupported`, async () => {
    await page.locator(selector).first().evaluate(element => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(['# New'], 'new.md', { type: 'text/markdown' }));
      transfer.items.add(new File(['binary'], 'bad.pdf'));
      element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }));
    });
    const dialog = page.getByRole('dialog');
    await expect(dialog.locator('[data-status=rejected]')).toHaveCount(1);
    await expect(dialog.getByRole('button', { name: '导入 1 篇' })).toBeEnabled();
    await dialog.getByRole('button', { name: '导入 1 篇' }).click();
    await expect(dialog.locator('[data-status=success]')).toHaveCount(1);
    expect(creates[0].parent_id).toBe(parent);
    expect(mutations).toEqual([]);
  });
}
