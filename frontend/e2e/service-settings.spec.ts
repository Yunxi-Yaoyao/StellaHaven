// Legacy service regression scenarios, migrated to the isolated mock-only harness.
import {test,expect} from '@playwright/test';
import {mock} from './settings-mocks';
test('session history stays folded and pagination is visible only after expansion',async({page})=>{
 const m=await mock(page);let calls=0;
 await page.route('**/auth/sessions/history?*',route=>{calls++;return route.fulfill({json:{items:[{id:'old',device:'Old session',state:'expired',created_at:'2026-08-01T00:00:00Z',last_seen:'2026-08-01T00:00:00Z'}],total:21,page:1,page_size:20}});});
 await page.goto('/settings');await expect(page.getByText('当前会话',{exact:true})).toBeVisible();expect(calls).toBe(0);
 await page.locator('details summary').click();await expect(page.getByText('Old session',{exact:false})).toBeVisible();expect(calls).toBe(1);
 await expect(page.getByText('邀请新用户',{exact:true})).toHaveCount(0);expect(m.unknown).toEqual([]);
});
test('service connection preserves full subpath and redacted token; detection checks the unsaved draft',async({page})=>{
 const m=await mock(page);m.services.drive.connection={service_url:'http://owned.test:12544/drive/openlist',auth_mode:'token',has_token:true};
 await page.route('**/service-settings/drive/check',route=>{m.requests.push({path:'/service-settings/drive/check',method:'POST',body:route.request().postDataJSON()});return route.fulfill({json:{ok:false,message:'认证被拒绝，检查登录方式/凭据'}});});
 await page.goto('/settings?section=navigation&module=drive');await expect(page.getByLabel('OpenList 服务地址',{exact:true})).toHaveValue('http://owned.test:12544/drive/openlist');await expect(page.getByLabel('Token',{exact:true})).toHaveValue('');await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.getByLabel('OpenList 服务地址',{exact:true}).fill('http://owned.test/current-draft');await page.getByRole('button',{name:'检测连接',exact:true}).click();await expect(page.locator('.service-editor').getByRole('status')).toContainText('认证被拒绝');expect(m.requests.at(-1)?.body.connection.service_url).toBe('http://owned.test/current-draft');expect(m.requests.filter(x=>x.path.includes('/token'))).toEqual([]);await expect(page.locator('select')).toHaveCount(0);expect(m.unknown).toEqual([]);
});
test('reconnect same URL reloads iframe and restores visibility',async({page})=>{
 const m=await mock(page);let visits=0;
 await page.route('**/drive/openlist/',route=>{visits++;return route.fulfill({contentType:'text/html',body:'<h1>Reloaded files</h1>'});});
 await page.goto('/drive');await expect(page.locator('iframe')).toHaveClass(/ready/);
 // Inject a browser error signal so recovery is exposed; normal UI has no toolbar.
 await page.locator('iframe').dispatchEvent('error',{bubbles:false});
 const before=visits;await page.getByRole('button',{name:'重新连接',exact:true}).click();await expect.poll(()=>visits).toBeGreaterThan(before);
 await expect(page.locator('iframe')).toHaveClass(/ready/);await expect(page.frameLocator('iframe').getByText('Reloaded files')).toBeVisible();expect(m.unknown).toEqual([]);
});
test('gallery informational warning is absent on normal loading',async({page})=>{
 const m=await mock(page);await page.goto('/gallery');await expect(page.frameLocator('iframe').getByText('Mock service content')).toBeVisible();
 await expect(page.getByText('使用原 Immich 账号或已有 OIDC 登录。无法嵌入时请在新窗口打开。',{exact:true})).toHaveCount(0);expect(m.unknown).toEqual([]);
});
test('failed reconnect keeps previous files visible and shows actual error',async({page})=>{
 const m=await mock(page);await page.goto('/drive');await expect(page.locator('iframe')).toHaveClass(/ready/);
 await page.locator('iframe').dispatchEvent('error',{bubbles:false});
 await page.route('**/drive/login-url',route=>route.fulfill({status:502,json:{detail:'upstream unavailable'}}));
 await page.getByRole('button',{name:'重新连接',exact:true}).click();await expect(page.getByRole('alert')).toContainText('upstream unavailable');
 await expect(page.locator('iframe')).toHaveClass(/ready/);await expect(page.frameLocator('iframe').getByText('Mock service content')).toBeVisible();expect(m.unknown).toEqual([]);
});
test('gallery warning appears when connection retrieval fails',async({page})=>{
 const m=await mock(page);await page.route('**/gallery/status',route=>route.fulfill({status:502,json:{detail:'Immich 服务暂不可达'}}));
 await page.goto('/gallery');await expect(page.getByRole('alert')).toContainText('Immich 服务暂不可达');
 await expect(page.getByRole('link',{name:'新窗口打开',exact:true})).toHaveAttribute('href','/gallery/connect');expect(m.unknown).toEqual([]);
});
