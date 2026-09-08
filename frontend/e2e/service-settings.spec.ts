import {test,expect,chromium} from '@playwright/test';
let browser:any,page:any;
const base='http://192.168.1.5:5173';
test.beforeAll(async()=>{browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox'],headless:true});});
test.afterAll(async()=>browser.close());
test.beforeEach(async()=>{
 page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.route('**/*',async(route:any)=>{
  const p=new URL(route.request().url()).pathname;
  const ok=(json:any)=>route.fulfill({json});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'u',username:'test',display_name:'Test',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false});
  if(p==='/auth/sessions')return ok([{id:'s',device:'This browser',current:true,mine:true,created_at:'2026-09-08T10:00:00Z',last_seen:'2026-09-08T10:05:00Z',remember:true}]);
  if(p==='/auth/sessions/history')return ok({items:[{id:'old',device:'Old session',state:'expired',mine:true,owner:'Test',created_at:'2026-08-01T00:00:00Z',last_seen:'2026-08-01T00:00:00Z'}],total:21,page:1,page_size:20});
  if(p==='/drive/status')return ok({configured:true,use_proxy:true,auth_mode:'manual',browser_url:'https://example.test/files'});
  if(p==='/drive/login-url')return ok({url:'/drive/openlist/'});
  if(p.startsWith('/drive/openlist/'))return route.fulfill({contentType:'text/html',body:'<h1>Existing files</h1>'});
  if(p==='/drive/connection')return ok({service_url:'http://10.66.0.2:12544/drive/openlist',auth_mode:'token',has_token:true});
  if(p==='/drive/connection/token')return ok({token:'TEST_ONLY_SECRET'});
  if(p==='/drive/connection/test')return ok({ok:false,message:'认证被拒绝，检查登录方式/凭据',warning:''});
  if(p.startsWith('/auth/')||p.startsWith('/admin/')||p==='/users/'||p.startsWith('/config/'))return ok([]);
  return route.continue();
 });
});
test.afterEach(async()=>page.close());
test('session history stays folded and pagination is visible only after expansion',async()=>{
 let historyCalls=0;page.on('request',(r:any)=>{if(r.url().includes('/auth/sessions/history'))historyCalls++;});
 await page.goto(base+'/settings');
 await expect(page.getByText('当前会话',{exact:true})).toBeVisible();
 expect(historyCalls).toBe(0);
 await page.locator('details summary').click();
 await expect(page.getByText('Old session',{exact:false})).toBeVisible();
 expect(historyCalls).toBe(1);
 await expect(page.getByText('邀请新用户',{exact:true})).toHaveCount(0); // other admin tab is not removed, just inactive
});
test('external connection fields retain full URL, subpath, auth and actionable test feedback',async()=>{
 await page.goto(base+'/drive');
 await expect(page.frameLocator('iframe').getByText('Existing files')).toBeVisible();
 await expect(page.getByText('未检测到 Docker',{exact:false})).toHaveCount(0);
 await page.getByRole('button',{name:'连接设置',exact:true}).click();
 await expect(page.getByRole('dialog')).toBeVisible();
 await expect(page.getByLabel('OpenList 服务地址',{exact:true})).toHaveValue('http://10.66.0.2:12544/drive/openlist');
  await expect(page.getByText('浏览器入口',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('link',{name:'新窗口打开'})).toHaveCount(0);
  await page.getByRole('button',{name:'查看已保存 Token',exact:true}).click();
  await expect(page.getByLabel('Token',{exact:true})).toHaveValue('TEST_ONLY_SECRET');
 await expect(page.locator('select')).toHaveCount(0);
 await page.getByRole('button',{name:'测试连接',exact:true}).click();
 await expect(page.getByRole('dialog').getByRole('status')).toContainText('认证被拒绝');
});

test('reconnect same URL reloads iframe and restores visibility',async()=>{
 let visits=0;
 await page.route('**/drive/openlist/',(route:any)=>{visits++;return route.fulfill({contentType:'text/html',body:'<h1>Reloaded files</h1>'});});
 await page.goto(base+'/drive');await expect(page.locator('iframe')).toHaveClass(/ready/);
 const before=visits;await page.getByRole('button',{name:'重新连接',exact:true}).click();
 await expect.poll(()=>visits).toBeGreaterThan(before);
 await expect(page.locator('iframe')).toHaveClass(/ready/);
 await expect(page.frameLocator('iframe').getByText('Reloaded files')).toBeVisible();
});
test('gallery informational warning is absent on normal loading',async()=>{
 await page.route('**/gallery/status',(route:any)=>route.fulfill({json:{configured:true}}));
 await page.route('**/gallery/connect',(route:any)=>route.fulfill({contentType:'text/html',body:'<h1>Gallery content</h1>'}));
 await page.goto(base+'/gallery');await expect(page.frameLocator('iframe').getByText('Gallery content')).toBeVisible();
 await expect(page.getByText('使用原 Immich 账号或已有 OIDC 登录。无法嵌入时请在新窗口打开。',{exact:true})).toHaveCount(0);
});

test('failed reconnect keeps previous files visible and shows actual error',async()=>{
 await page.goto(base+'/drive');await expect(page.locator('iframe')).toHaveClass(/ready/);
 await page.route('**/drive/login-url',(route:any)=>route.fulfill({status:502,json:{detail:'upstream unavailable'}}));
 await page.getByRole('button',{name:'重新连接',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('upstream unavailable');
 await expect(page.locator('iframe')).toHaveClass(/ready/);
 await expect(page.frameLocator('iframe').getByText('Existing files')).toBeVisible();
});
test('gallery warning appears when connection retrieval fails',async()=>{
 await page.route('**/gallery/status',(route:any)=>route.fulfill({status:502,json:{detail:'Immich 服务暂不可达'}}));
 await page.goto(base+'/gallery');await expect(page.getByRole('alert')).toContainText('Immich 服务暂不可达');
 await expect(page.getByText('使用原 Immich 账号或已有 OIDC 登录。无法嵌入时请在新窗口打开。',{exact:true})).toBeVisible();
});
