import { test, expect, chromium, type Browser, type Page } from '@playwright/test';
let browser: Browser, page: Page;
let previews: string[], commits: string[], flat: any[], mutations: string[];
let fail = false, missing = false;
const base = { id: 'parent', title: 'Parent', file_path: '/parent.md', workspace_id: 'ws-a', parent_id: null, content: '# Untouched', updated_at: '2026-09-08T06:00:00Z', created_at: '2026-09-08T06:00:00Z', has_draft: false, status: 'published', is_folder: false, is_favorite: false, is_pinned: false };
const zip = (name = 'notes.zip') => ({ name, mimeType: 'application/zip', buffer: Buffer.from('mock zip bytes') });
const field = (body: string, name: string) => body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]+)`))?.[1];
test.beforeAll(async () => { browser = await chromium.launch({ executablePath: '/usr/sbin/google-chrome-stable', args: ['--no-sandbox'], headless: true }); });
test.afterAll(async () => { await browser.close(); });
test.beforeEach(async () => {
  previews = []; commits = []; flat = []; mutations = []; fail = false; missing = false;
  page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    if (url.hostname !== '127.0.0.1') return route.abort();
    const ok = (json: any) => route.fulfill({ json });
    if (p === '/auth/me') return ok({ id: 'user', username: 'test', role: 'admin', is_admin: true });
    if (p.startsWith('/workspaces/')) return ok(p === '/workspaces/' ? [{ id: 'ws-a', name: 'Workspace' }] : { id: 'ws-a' });
    if (p.startsWith('/documents/import/zip')) {
      expect(req.headers()['content-type']).toContain('multipart/form-data; boundary=');
      const body = req.postDataBuffer()!.toString();
      if (p.endsWith('/preview')) {
        previews.push(body);
        if (body.includes('bad.zip')) return route.fulfill({ status: 400, json: { detail: 'Invalid ZIP archive' } });
        return ok({ entries: [{path:'Folder',title:'Folder',kind:'directory',parent_path:null},{path:'Folder/Note.md',title:'Note',kind:'document',parent_path:'Folder'},{path:'Folder/a.png',title:'a.png',kind:'attachment',parent_path:'Folder'}], warnings: ['同名笔记会添加后缀'], counts: { documents: 1, attachments: 1 } });
      }
      commits.push(body);
      if (missing) return route.fulfill({ status: 404, json: { detail: '目标笔记已不存在' } });
      if (fail) { fail = false; return route.fulfill({ status: 500, json: { detail: 'Temporary failure' } }); }
      return ok({ documents: [{ id: 'new', title: 'Note (2)', path: 'Folder/Note.md', parent_id: 'child' }], attachments: 1, warnings: [], reused: commits.length > 1 });
    }
    if (p === '/documents/import/finalize') return ok({ synced: 1 });
    if (p === '/documents/') { if (req.method() === 'POST') { flat.push(req.postDataJSON()); return ok({ ...base, id: 'flat' }); } return ok([base, {...base,id:'child',title:'Child',parent_id:'parent'}]); }
    if (p === '/documents/parent') { if (req.method() !== 'GET') mutations.push(req.method()); return ok(base); }
    if (p.startsWith('/documents/') || p.startsWith('/tags/') || p.startsWith('/doc-tags/') || p.startsWith('/attachments/') || p.startsWith('/document-links/')) return ok([]);
    if (p.startsWith('/auth/') || p.startsWith('/api/')) return ok({});
    return route.continue();
  });
  await page.addInitScript(() => { localStorage.clear(); localStorage.setItem('stella_bootstrap', JSON.stringify({userId:'user',workspaceId:'ws-a'})); });
  await page.goto('http://127.0.0.1:5173/notes');
  await expect(page.locator('.doc-list')).toBeAttached();
});
test.afterEach(async () => { await page.close(); });

test('read-only preview, hierarchy, GB18030, frozen target and idempotent retry on mobile', async () => {
  fail = true;
  await page.evaluate(() => Object.defineProperty(crypto, 'randomUUID', {value: undefined})); // LAN HTTP
  await page.locator('.notes-page input[type=file]').setInputFiles(zip());
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('treeitem', { name: 'Child', exact: true }).click();
  await dialog.getByRole('button', { name: '预览 ZIP', exact: true }).click();
  await expect(dialog.getByLabel('ZIP 只读预览')).toContainText('Note');
  expect(commits).toHaveLength(0); expect(flat).toHaveLength(0); expect(mutations).toEqual([]);
  expect(field(previews[0]!, 'workspace_id')).toBe('ws-a'); expect(field(previews[0]!, 'parent_id')).toBe('child'); expect(field(previews[0]!, 'encoding')).toBe('auto');
  await dialog.getByRole('button', { name: 'GB18030', exact: true }).click();
  await expect.poll(() => previews.length).toBe(2);
  expect(field(previews[1]!, 'encoding')).toBe('gb18030');
  await page.screenshot({ path: '/tmp/stella-zip-mobile.png', fullPage: true });
  expect(await dialog.evaluate(el => el.getBoundingClientRect().right)).toBeLessThanOrEqual(390);
  await dialog.getByRole('button', { name: '导入此 ZIP', exact: true }).click();
  await expect(dialog).toContainText('Temporary failure');
  await expect(dialog.getByRole('treeitem', {name:'工作区根目录'})).toBeDisabled();
  await dialog.getByRole('button', { name: '重试此 ZIP', exact: true }).click();
  await expect(dialog).toContainText('Note (2)');
  expect(commits).toHaveLength(2);
  expect(field(commits[0]!, 'import_id')).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  for (const key of ['workspace_id','parent_id','encoding','import_id']) expect(field(commits[1]!,key)).toBe(field(commits[0]!,key));
  expect(commits[0]).toContain('filename="notes.zip"'); expect(mutations).toEqual([]);
});

test('mixed flat and multiple ZIP files remain explicit; root omits parent; invalid ZIP and missing target errors', async () => {
  await page.locator('.notes-page input[type=file]').setInputFiles([zip(),zip('bad.zip'),{name:'plain.md',mimeType:'text/markdown',buffer:Buffer.from('# New')}]);
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('.zip-import')).toHaveCount(2);
  await dialog.getByRole('treeitem', {name:'工作区根目录'}).click();
  const good = dialog.locator('.zip-import').filter({hasText:'notes.zip'}), bad = dialog.locator('.zip-import').filter({hasText:'bad.zip'});
  await bad.getByRole('button', {name:'预览 ZIP',exact:true}).click();
  await expect(bad).toContainText('Invalid ZIP archive');
  await good.getByRole('button', {name:'预览 ZIP',exact:true}).click();
  await expect(good.getByLabel('ZIP 只读预览')).toBeVisible();
  expect(field(previews.at(-1)!, 'parent_id')).toBeUndefined();
  missing = true;
  await good.getByRole('button', {name:'导入此 ZIP',exact:true}).click();
  await expect(good).toContainText('目标笔记已不存在');
  await dialog.getByRole('button', {name:'导入 1 篇',exact:true}).click();
  await expect(dialog.locator('.import-row[data-status=success]')).toHaveCount(1);
  expect(flat).toHaveLength(1); expect(commits).toHaveLength(1); expect(mutations).toEqual([]);
});
