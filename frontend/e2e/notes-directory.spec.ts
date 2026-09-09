import { test, expect, chromium } from '@playwright/test';
import type { Browser, Page } from '@playwright/test';
let browser: Browser;
let page: Page;
let saved: any[];
const baseURL = process.env.STELLA_TEST_URL || 'http://127.0.0.1:5173';
const original = '# 正文标题\n\n保留的正文与 [[手写双链]]\n';
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
    if (p === '/documents/') return fulfill([{ ...doc, content: undefined },{...doc,id:'child-a',title:'模板',parent_id:'doc-a'}, {...doc,id:'grandchild',title:'事件记录模板',parent_id:'child-a'}, {...doc,id:'child-b',title:'README',parent_id:'doc-a'}]);
    if (p === '/documents/doc-a/backlinks') return fulfill([{...doc,id:'ref-a',title:'引用文章'}]);
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

test('directory sits before body, direct children only, folded backlinks and no content writes', async () => {
 const directory=page.locator('.auto-directory');
 await expect(directory).toBeVisible();
 await expect(directory.getByRole('button',{name:'模板',exact:true})).toBeVisible();
 await expect(directory.getByRole('button',{name:'事件记录模板',exact:true})).toHaveCount(0);
 expect(await directory.evaluate(el=>!!(el.compareDocumentPosition(document.querySelector('.panes')!)&Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
 await expect(page.locator('.children-strip')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'引用文章',exact:true})).not.toBeVisible();
 await page.getByRole('button',{name:'被 1 篇文章引用',exact:true}).click();
 await expect(page.getByRole('button',{name:'引用文章',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 await expect(directory).toBeVisible();
 await page.keyboard.press('Control+s');
 expect(saved).toEqual([]);
 await page.screenshot({path:'/tmp/stella-auto-directory-desktop.png',fullPage:true});
});
test('phone with body collapses directory, remembers expansion, no horizontal overflow', async () => {
 await page.setViewportSize({width:390,height:844});
 await page.reload();
 await expect(page.locator('.title-readonly')).toHaveText('编辑验收');
 await expect(page.locator('.auto-directory')).toBeVisible();
 await expect(page.locator('.auto-directory').getByRole('button',{name:'模板',exact:true})).not.toBeVisible();
 await page.screenshot({path:'/tmp/stella-auto-directory-mobile-collapsed.png',fullPage:true});
 await page.locator('.auto-directory button[aria-expanded]').first().click();
 await expect(page.locator('.auto-directory').getByRole('button',{name:'模板',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'/tmp/stella-auto-directory-mobile.png',fullPage:true});
});

test('directory child creation chooses body template and uses the current parent ID', async()=>{
 let payload:any=null;
 await page.route('**/documents/',route=>{
  if(route.request().method()!=='POST')return route.fallback();
  payload=route.request().postDataJSON();return route.fulfill({status:201,json:{...payload,id:'new-child',updated_at:'2026-09-09T09:00:00Z'}});
 });
 await page.route('**/documents/new-child',route=>route.fulfill({json:{...payload,id:'new-child',updated_at:'2026-09-09T09:00:00Z'}}));
 await page.locator('.auto-directory').getByRole('button',{name:'新建子页面',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'新建子页面'})).toBeVisible();
 await page.getByLabel('标题',{exact:true}).fill('新的记录');
 await page.getByRole('button',{name:'文章模板',exact:true}).click();
 await page.getByRole('button',{name:'创建',exact:true}).click();
 await expect.poll(()=>payload?.parent_id).toBe('doc-a');
 expect(payload.content).toContain('## 核心结论');expect(payload.title).toBe('新的记录');
 expect(saved).toEqual([]);
});
