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
test('external connection retains full subpath, token auth and actionable test feedback in central settings',async({page})=>{
 const m=await mock(page);m.state.elevated=true;
 await page.route('**/drive/connection',route=>route.fulfill({json:{service_url:'http://10.66.0.2:12544/drive/openlist',auth_mode:'token',has_token:true}}));
 await page.route('**/drive/connection/token',route=>route.fulfill({json:{token:'TEST_ONLY_SECRET'}}));
 await page.route('**/drive/connection/test',route=>route.fulfill({json:{ok:false,message:'认证被拒绝，检查登录方式/凭据',warning:''}}));
 await page.goto('/drive');await page.getByRole('button',{name:'连接设置',exact:true}).click();
 await expect(page).toHaveURL(/settings\?section=navigation&module=drive/);
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page.getByLabel('OpenList 服务地址',{exact:true})).toHaveValue('http://10.66.0.2:12544/drive/openlist');
 await expect(page.getByText('浏览器入口',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'查看已保存 Token',exact:true}).click();await expect(page.getByLabel('Token',{exact:true})).toHaveValue('TEST_ONLY_SECRET');
 await expect(page.locator('select')).toHaveCount(0);await page.getByRole('button',{name:'测试连接',exact:true}).click();
 await expect(page.locator('.connection-inline').getByRole('status')).toContainText('认证被拒绝');
 expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain('TEST_ONLY_SECRET');expect(m.unknown).toEqual([]);
});
test('reconnect same URL reloads iframe and restores visibility',async({page})=>{
 const m=await mock(page);let visits=0;
 await page.route('**/drive/openlist/',route=>{visits++;return route.fulfill({contentType:'text/html',body:'<h1>Reloaded files</h1>'});});
 await page.goto('/drive');await expect(page.locator('iframe')).toHaveClass(/ready/);
 const before=visits;await page.getByRole('button',{name:'重新连接',exact:true}).click();await expect.poll(()=>visits).toBeGreaterThan(before);
 await expect(page.locator('iframe')).toHaveClass(/ready/);await expect(page.frameLocator('iframe').getByText('Reloaded files')).toBeVisible();expect(m.unknown).toEqual([]);
});
test('gallery informational warning is absent on normal loading',async({page})=>{
 const m=await mock(page);await page.goto('/gallery');await expect(page.frameLocator('iframe').getByText('Mock service content')).toBeVisible();
 await expect(page.getByText('使用原 Immich 账号或已有 OIDC 登录。无法嵌入时请在新窗口打开。',{exact:true})).toHaveCount(0);expect(m.unknown).toEqual([]);
});
test('failed reconnect keeps previous files visible and shows actual error',async({page})=>{
 const m=await mock(page);await page.goto('/drive');await expect(page.locator('iframe')).toHaveClass(/ready/);
 await page.route('**/drive/login-url',route=>route.fulfill({status:502,json:{detail:'upstream unavailable'}}));
 await page.getByRole('button',{name:'重新连接',exact:true}).click();await expect(page.getByRole('alert')).toContainText('upstream unavailable');
 await expect(page.locator('iframe')).toHaveClass(/ready/);await expect(page.frameLocator('iframe').getByText('Mock service content')).toBeVisible();expect(m.unknown).toEqual([]);
});
test('gallery warning appears when connection retrieval fails',async({page})=>{
 const m=await mock(page);await page.route('**/gallery/status',route=>route.fulfill({status:502,json:{detail:'Immich 服务暂不可达'}}));
 await page.goto('/gallery');await expect(page.getByRole('alert')).toContainText('Immich 服务暂不可达');
 await expect(page.getByText('使用原 Immich 账号或已有 OIDC 登录。无法嵌入时请在新窗口打开。',{exact:true})).toBeVisible();expect(m.unknown).toEqual([]);
});
