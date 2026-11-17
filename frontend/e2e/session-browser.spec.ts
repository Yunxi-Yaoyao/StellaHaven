import {test,expect,type Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
import {mkdirSync,writeFileSync} from 'node:fs';
const out=process.env.STELLA_SESSION_QA_OUTPUT||'node_modules/.cache/browser-sessions';
async function fixture(page:Page,signed=true){
 const clientPreferences=createClientPreferencesFixture({storage:{stella_home_theme:'daybreak'}});
 const unknown:string[]=[],errors:string[]=[],writes:any[]=[],locations:string[]=[];let authenticated=signed;
 const me={id:'fixture-owner',username:'fixture',display_name:'Fixture owner',is_admin:true,avatar_url:'',home_bg:'/seed/showcase-image.svg',email:'',email_verified:false};
 const base={remember:false,created_at:'2026-10-16T00:00:00Z',last_seen:'2026-10-16T00:00:00Z',mine:true,owner:'fixture',ip:'203.0.113.8'};
 const sessions=[{...base,id:'legacy',device:'旧设备',current:false},{...base,id:'current',device:'Linux',current:true,browser_name:'Chrome',os_name:'Windows',login_origin:'https://stella.test',ip_location:null},{...base,id:'other',device:'Android',current:false,browser_name:'Firefox',os_name:'Android',login_origin:'https://mobile.stella.test',ip_location:'测试地区'}];
 const clients=[{client_id:'photos',name:'私人相册',enabled:true,redirect_uris:['https://photos.test/callback'],has_secret:true,scopes:['openid','profile','email']}];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});await page.routeWebSocket('**/*',ws=>ws.onMessage(()=>{}));
 await page.addInitScript(()=>localStorage.setItem('stella_home_theme','daybreak'));
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname,method=req.method();const ok=(json:any,status=200)=>route.fulfill({status,json});
  if(u.origin!=='http://127.0.0.1:15274'){unknown.push(method+' '+req.url());return route.abort();}
  if(method!=='GET')writes.push({path:p,method,body:req.postDataJSON()});
  if(p==='/operations/backups/client-preferences'&&!u.search&&method==='GET'&&!authenticated)return ok({detail:'fixture guest'},401);
  const preference=clientPreferences.respond(method,p+u.search);if(preference)return route.fulfill(preference);
  if(p==='/auth/email-service'&&method==='GET'&&!u.search)return ok({ready:true});
  if(p==='/auth/status')return ok({initialized:true,email_enabled:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok(authenticated?me:{detail:'fixture guest'},authenticated?200:401);
  if(p==='/auth/login'||p==='/auth/login-code'){authenticated=true;return ok(me);}
  if(p==='/auth/login-code/send')return ok({ok:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:true,expires_at:null,single_user:true,setup_required:false});
  if(p==='/auth/sessions')return ok(sessions);
  if(p==='/auth/sessions/history')return ok({items:[{...base,id:'historic',device:'旧设备',current:false,state:'revoked'}],total:1,page:1,page_size:20});
  if(/^\/auth\/sessions\/[^/]+\/location$/.test(p)){locations.push(p);return ok({ip:'203.0.113.8',ip_location:'测试归属地'});}
  if(p==='/auth/provider/config')return ok({issuer:'https://stella.test',discovery_url:'https://stella.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.test/auth/authorize',token_endpoint:'https://stella.test/auth/token',userinfo_endpoint:'https://stella.test/auth/userinfo',jwks_uri:'https://stella.test/auth/jwks',clients,capabilities:{}});
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/navigation')return ok({entries:[],settings_route:'/settings'});
  if(['/external-modules','/notifications','/notifications/','/auth/avatars'].includes(p))return ok([]);
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/config/site-background')return ok({value:'/seed/showcase-image.svg'});
  if(p==='/config/public-host')return ok({value:''});
  if(p==='/homebg/media')return ok({url:'/seed/showcase-image.svg',status:'ready',poster:null,variants:{original:'/seed/showcase-image.svg'}});
  if(method==='GET'&&(req.isNavigationRequest()||/^\/(static|seed|assets)\//.test(p)||['/favicon.ico','/favicon.svg','/avatar.png','/live2dcubismcore.min.js'].includes(p)))return route.continue();
  unknown.push(method+' '+p);return ok({detail:'unhandled fixture'},501);
 });return {unknown,errors,writes,locations,expire:()=>{authenticated=false;}};
}
test('owner preference seed matches storage and expires with the fixture session',async({page},info)=>{
 const state=await fixture(page);const reads:any[]=[];page.on('response',async response=>{if(new URL(response.url()).pathname==='/operations/backups/client-preferences')reads.push({status:response.status(),method:response.request().method(),dto:await response.json()});});
 await page.goto('/settings?section=authentication');await expect(page.locator('.sess-device').first()).toBeVisible();
 await expect.poll(()=>page.evaluate(()=>localStorage.getItem('stella_client_preferences_owner'))).toBe('fixture-owner');
 const storage=await page.evaluate(()=>Object.fromEntries(['stella_home_theme','stella_live2d','stella_home_particles','stella_home_bg_quality','stella_note_edit_mode','stella_list_fold'].map(key=>[key,localStorage.getItem(key)])));
 expect(storage).toEqual({stella_home_theme:'daybreak',stella_live2d:'on',stella_home_particles:'stars',stella_home_bg_quality:'compressed1',stella_note_edit_mode:'rich',stella_list_fold:'0'});
 expect(reads).toHaveLength(1);expect(reads[0]).toMatchObject({status:200,method:'GET',dto:{revision:1,home:{theme:'daybreak',live2d:true,particles:'stars'},ui:{backgroundQuality:'compressed1',noteEditMode:'rich',listFold:false}}});
 state.expire();const expired=await page.evaluate(async()=>{const r=await fetch('/operations/backups/client-preferences');return {status:r.status,dto:await r.json()};});expect(expired).toEqual({status:401,dto:{detail:'fixture guest'}});
 expect(state.unknown).toEqual([]);expect(state.writes.filter(w=>w.path!=='/auth/activity')).toEqual([]);await info.attach('owner-preference-session.json',{body:JSON.stringify({reads,storage,expired}),contentType:'application/json'});
});
test('guest cannot read persisted owner preferences',async({page},info)=>{
 const state=await fixture(page,false);
 // Probe the fixture's HTTP denial independently of the real App's native-fetch
 // session fence, then assert that the public page fetch is fenced as well.
 await page.addInitScript(()=>{(window as any).__sessionFixtureFetch=window.fetch.bind(window);});
 await page.goto('/settings?section=authentication');const guest=await page.evaluate(async()=>{const r=await (window as any).__sessionFixtureFetch('/operations/backups/client-preferences');return {status:r.status,dto:await r.json()};});
 expect(await page.evaluate(()=>fetch('/operations/backups/client-preferences').then(()=>null,error=>error.name))).toBe('AbortError');
 expect(guest).toEqual({status:401,dto:{detail:'fixture guest'}});expect(state.unknown).toEqual([]);expect(await page.evaluate(()=>localStorage.getItem('stella_client_preferences_owner'))).toBeNull();await info.attach('guest-preference-denied.json',{body:JSON.stringify(guest),contentType:'application/json'});
});
for(const method of ['GET','POST'])test('peer negative control preserves unknown rejection for '+method,async({page},info)=>{
 const state=await fixture(page);await page.goto('/settings?section=authentication');await expect(page.locator('.sess-device').first()).toBeVisible();expect(state.unknown).toEqual([]);
 const target='/operations/backups/client-preferences'+(method==='GET'?'/unknown':'');const status=await page.evaluate(async({target,method})=>(await fetch(target,{method})).status,{target,method});expect(status).toBe(501);expect(state.unknown).toEqual([method+' '+target]);expect(()=>expect(state.unknown).toEqual([])).toThrow();await info.attach('peer-denied-unknown.json',{body:JSON.stringify({method,target,status,unknown:state.unknown}),contentType:'application/json'});
});
for(const width of [320,393,1440])test(`real App session display and folded providers at ${width}px`,async({page})=>{
 const state=await fixture(page);await page.setViewportSize({width,height:width===1440?1100:852});await page.goto('/settings?section=authentication');await expect(page.locator('.sess-device').first()).toHaveText('Chrome · Windows');const current=page.locator('[data-session-id="current"]');await expect(current.locator('.session-origin')).toBeHidden();await current.getByRole('button',{name:'展开当前会话详情',exact:true}).click();await expect(current.locator('.session-origin')).toHaveText('https://stella.test');
 await expect(page.locator('[data-other-sessions]')).toBeVisible();await expect(page.locator('[data-other-sessions] .sess-row')).toHaveCount(2);await expect(page.locator('[data-connected-apps]')).not.toHaveAttribute('open');await expect(page.locator('[data-connected-apps] > summary')).toHaveText('已连接应用（1）');
 const disclosure=page.locator('[data-session-location-notice]');await expect(disclosure).toHaveCount(1);await expect(disclosure).toHaveText('查询归属地会将该会话的 IP 发送给 IPinfo；地点可能是代理出口，并非实际位置。');await expect(disclosure).toBeVisible();await page.getByRole('button',{name:'登录记录说明',exact:true}).click();await expect(page.getByRole('tooltip')).toContainText('当前会话独立读取，换页仍保留；其他有效会话按页展示。');await page.keyboard.press('Escape');expect(state.locations).toEqual([]);
 await disclosure.scrollIntoViewIfNeeded();await expect(disclosure).toBeInViewport();await expect(page.getByRole('dialog')).toHaveCount(0);mkdirSync(out,{recursive:true});await page.screenshot({path:`${out}/app-${width}-before-lookup.png`});
 await page.getByRole('button',{name:'查询归属地',exact:true}).first().click();await expect(page.locator('[data-session-id="current"] .session-network')).toContainText('测试归属地');await expect(page.locator('[data-session-id="current"] .session-ip')).toHaveText('203.0.113.8');expect(state.locations).toEqual(['/auth/sessions/current/location']);await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.locator('.sess-device').first().scrollIntoViewIfNeeded();mkdirSync(out,{recursive:true});await page.screenshot({path:`${out}/app-${width}-folded.png`});
 const legacy=page.locator('[data-session-id="legacy"]');await expect(legacy.locator('.sess-device')).toHaveText('旧设备 · 系统未知');await legacy.getByRole('button',{name:'展开会话详情',exact:true}).click();await expect(legacy.locator('.session-origin')).toHaveText('入口未知');await expect(page.locator('[data-other-sessions] .sess-group')).toHaveText('其他有效会话');
 await page.locator('[data-connected-apps] > summary').click();await expect(page.getByText('私人相册',{exact:true})).toBeVisible();await expect(page.locator('[data-client-details]')).not.toHaveAttribute('open');await page.locator('[data-client-details] > summary').click();await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByLabel('应用名称',{exact:true}).fill('未保存的草稿');await page.locator('[data-connected-apps] > summary').click();await expect(page.getByLabel('应用名称',{exact:true})).toHaveValue('未保存的草稿');await expect(page.getByRole('button',{name:'预览变更',exact:true})).toBeVisible();
 await page.getByLabel('应用地址 1',{exact:true}).scrollIntoViewIfNeeded();await expect(page.getByLabel('应用地址 1',{exact:true})).toHaveValue('https://photos.test');await expect(page.getByLabel('回调用途路径 1',{exact:true})).toHaveValue('/callback');await page.screenshot({path:`${out}/app-${width}-draft.png`});
 const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,fields:[...document.querySelectorAll('.provider-card input,.provider-card textarea,.sess-row')].filter(e=>e.getBoundingClientRect().width).map(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,scroll:e.scrollWidth,width:e.clientWidth}))}));expect(layout.scroll).toBeLessThanOrEqual(width);for(const field of layout.fields){expect(field.left).toBeGreaterThanOrEqual(0);expect(field.right).toBeLessThanOrEqual(width);expect(field.scroll).toBeLessThanOrEqual(field.width+1);}
 expect(state.locations).toEqual(['/auth/sessions/current/location']);await expect(page.locator('[data-session-location-notice]')).toHaveCount(1);await expect(page.locator('.provider-card')).not.toContainText('client_secret');expect(state.unknown).toEqual([]);expect(state.errors).toEqual([]);expect(state.writes.filter(w=>w.path!=='/auth/activity')).toEqual([]);writeFileSync(`${out}/app-${width}-report.json`,JSON.stringify({...state,layout},null,2));
});
test('real App password and code login share a persisted UUID after reload',async({page})=>{
 const state=await fixture(page,false);await page.goto('/settings?section=authentication');const dialog=page.getByRole('dialog',{name:'Stella 登录'});await dialog.locator('input[autocomplete="username"]').fill('fixture');await dialog.locator('input[type="password"]').fill('FIXTURE_NOT_SECRET');await dialog.getByRole('button',{name:'回港',exact:true}).click();await expect(dialog).toBeHidden();const id=state.writes.find(w=>w.path==='/auth/login').body.browser_id;expect(id).toMatch(/^[0-9a-f-]{36}$/);await page.reload();expect(await page.evaluate(()=>localStorage.getItem('stella_browser_id'))).toBe(id);expect(state.unknown).toEqual([]);state.expire();await page.reload();await dialog.getByRole('button',{name:'验证码登录',exact:true}).click();await dialog.locator('input[placeholder="你验证过的邮箱"]').fill('fixture@example.test');await dialog.getByRole('button',{name:'发送登录码',exact:true}).click();await dialog.locator('input[placeholder="6 位数字"]').fill('123456');await dialog.getByRole('button',{name:'进港',exact:true}).click();await expect(dialog).toBeHidden();expect(state.writes.find(w=>w.path==='/auth/login-code').body.browser_id).toBe(id);expect(state.unknown).toEqual([]);const guest401='Failed to load resource: the server responded with a status of 401 (Unauthorized)';expect(state.errors.every(message=>message===guest401)).toBe(true);writeFileSync(`${out}/login-identity-report.json`,JSON.stringify({...state,expectedGuest401:state.errors.length},null,2));
});