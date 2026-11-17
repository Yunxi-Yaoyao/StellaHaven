// Actual built App, isolated HTTP/WS responses; never connects to the backend.
import {test,expect,chromium,type Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../../tests/fixtures/clientPreferences';
import {layoutNodes} from '../../tests/fixtures/layoutNodes';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const base='http://127.0.0.1:15207';
const output=process.env.STELLA_LAYOUT_OUTPUT||path.join(tmpdir(),'stella-outline-app-evidence');
async function setup(page:Page,folded=false,nonemptyNodes=false){
 await mkdir(output,{recursive:true});
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_servers_fold:folded?'1':'0'},allowWrite:true});
 const unknown:string[]=[],errors:string[]=[],writes:string[]=[],preferenceWrites:any[]=[];
 let failPreferences=false,holdProfile=false,releaseProfile=()=>{};
 const profile={id:'fixture-owner',username:'yunxi',display_name:'云曦',is_admin:true,email:'long-address-for-layout-check@example.test',email_verified:false,avatar_url:'/avatar.png'};
 page.on('pageerror',e=>errors.push(e.message));
 await page.routeWebSocket('**/*',ws=>{if(new URL(ws.url()).pathname!='/ws/notifications')unknown.push(ws.url());});
 await page.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url()),p=u.pathname,m=request.method();
  if(u.origin!==base){unknown.push(m+' '+u.href);return route.abort();}
  if(m==='GET'&&(['/','/settings','/status','/avatar.png','/favicon.svg'].includes(p)||p.startsWith('/static/')))return route.continue();
  const ok=(json:any)=>route.fulfill({json});
  const allowedQueries:Record<string,string[]>={'/auth/sessions':['?page=1&page_size=20&exclude_current=true','?current_only=true'],'/auth/sessions/history':['?page=1&page_size=20'],'/mtr-tasks':['?trigger=manual']};
  if(u.search && !(allowedQueries[p]||[]).includes(u.search)){unknown.push(m+' '+p+u.search);return route.fulfill({status:500,json:{detail:'Unknown query'}});}
  if(m==='PUT'&&p==='/operations/backups/client-preferences'){preferenceWrites.push(request.postDataJSON());if(failPreferences)return route.fulfill({status:503,json:{detail:'隔离同步失败，输入保留'}});}
  const preference=preferences.respond(m,p+u.search,m==='PUT'?request.postDataJSON():undefined);if(preference)return route.fulfill(preference);
  if(m==='POST'&&p==='/auth/activity')return ok({ok:true});
  if(m==='PATCH'&&p==='/auth/me'){writes.push(p);if(holdProfile)await new Promise<void>(resolve=>{releaseProfile=resolve;});return route.fulfill({status:400,json:{detail:'保存失败，网络连接未确认。当前输入保留，请稍后重试；这段错误用于验证多行布局，不会改动账号。'}});}
  if(m!=='GET'&&!(p==='/auth/refresh'&&m==='POST')){unknown.push(m+' '+p);return route.abort();}
  if(p==='/auth/status')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok(profile);
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:true,single_user:true});
  if(p==='/navigation')return ok({entries:[],legacy_routes:{}});
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(p==='/nodes/')return ok(nonemptyNodes?layoutNodes:[]);
  if(['/auth/sessions','/auth/avatars','/external-modules','/notifications','/homebg/','/component-installs','/iperf-tasks','/commands','/mtr-tasks'].includes(p))return ok([]);
  if(p==='/nodes/host')return ok({local_install_supported:false,os:'fixture',installed:false,node_id:null,node_status:null});
  if(p==='/auth/provider/config')return ok({issuer:'https://stella.example.test',discovery_url:'https://stella.example.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.test/oauth/authorize',token_endpoint:'https://stella.example.test/oauth/token',userinfo_endpoint:'https://stella.example.test/oauth/userinfo',jwks_uri:'https://stella.example.test/oauth/jwks',capabilities:{},clients:[{client_id:'fixture-client',name:'样板应用',enabled:true,has_secret:true,scopes:['openid','profile'],redirect_uris:['https://app.example.test/auth/login']}]});
  if(p==='/auth/email-service')return ok({ready:false});
  if(['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(p==='/homebg/media')return ok({source:'',poster:''});
  if(p==='/admin/email/config')return ok({host:'smtp.example.test',port:465,username:'fixture@example.test',has_password:true,enabled:false,from_name:'Stella'});
  unknown.push(m+' '+p);return route.fulfill({status:500,json:{detail:'Unknown isolated fixture request'}});
 });
 await page.addInitScript(folded=>{localStorage.setItem('stella_live2d','off');if(localStorage.getItem('stella_servers_fold')===null)localStorage.setItem('stella_servers_fold',folded?'1':'0');},folded);
 return {unknown,errors,writes,preferenceWrites,failPreferences:(value:boolean)=>{failPreferences=value;},holdProfile:()=>{holdProfile=true;},releaseProfile:()=>{holdProfile=false;releaseProfile();}};
}
for(const width of [320,390,1365])test(`built App nonempty node cards ${width}`,async({page})=>{
 const f=await setup(page,false,true);await page.setViewportSize({width,height:960});await page.goto('/status');
 const cards=page.locator('.nodes-view .grid > .card');await expect(cards).toHaveCount(2);
 await page.mouse.move(0,0);await page.evaluate(async()=>{await Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
 const pane=await page.locator('.servers-page > .view-body').boundingBox();
 expect(pane).not.toBeNull();
 const geometry=[];
 for(const card of await cards.all()){
  const box=(await card.boundingBox())!;expect(box.x).toBeGreaterThanOrEqual(pane!.x);expect(box.x+box.width).toBeLessThanOrEqual(pane!.x+pane!.width);
  for(const selector of ['.card-top','.name','.machine-badge','.plat','.pub-badge','.actions','.actions button','.card-meta .v']){
   for(const item of await card.locator(selector).all()){
    await expect(item).toBeVisible();const b=(await item.boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(box.x);expect(b.x+b.width).toBeLessThanOrEqual(box.x+box.width);
   }
  }
  expect(await card.locator('.name').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
  await expect(card.locator('[title="agent"]')).toBeInViewport();await expect(card.locator('[title="移除"]')).toBeInViewport();geometry.push(box);
 }
 if(width===1365)expect(geometry[0]!.y).toBe(geometry[1]!.y);
 else{await page.locator('.servers-mobile-nav .dd-btn').click();const last=page.getByRole('option',{name:/记录/});await last.scrollIntoViewIfNeeded();await expect(last).toBeInViewport();await page.keyboard.press('Escape');await expect(page.locator('.servers-mobile-nav .dd-menu')).toBeHidden();}
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.writes).toEqual([]);expect(f.preferenceWrites).toEqual([]);
 await page.screenshot({path:path.join(output,`app-nonempty-nodes-${width}.png`)});
 await writeFile(path.join(output,`nodes-${width}.json`),JSON.stringify({width,pane,cards:geometry,unknown:f.unknown,errors:f.errors,businessWrites:f.writes,preferenceWrites:f.preferenceWrites},null,2));
});
for(const width of [1365,1920,390,320])test(`built App layout ${width}`,async({page})=>{
 const fixture=await setup(page);await page.setViewportSize({width,height:960});await page.goto('/settings');await expect(page.locator('#profile-name')).toBeVisible();
 const name=page.locator('#profile-name'),before=await name.boundingBox();
 await name.fill('很长的中文名称与继续编辑的草稿');const action=page.locator('.profile-settings button.is-primary').first();await expect(action).toBeVisible();expect((await name.boundingBox())!.width).toBe(before!.width);
 fixture.holdProfile();const normal=await action.boundingBox();await action.click();await expect(action).toHaveAttribute('aria-busy','true');await expect(action).toBeDisabled();expect((await action.boundingBox())!.width).toBe(normal!.width);expect((await name.boundingBox())!.x).toBe(before!.x);fixture.releaseProfile();await expect(page.locator('#profile-name-error')).toBeVisible();await expect(name).toHaveValue('很长的中文名称与继续编辑的草稿');await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await expect(page.locator('#profile-email-error')).toBeVisible();await page.waitForFunction(()=>!document.querySelector('.profile-email-editor')?.className.includes('profile-disclosure-enter'));await expect(page.getByRole('button',{name:'发送验证码',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:path.join(output,`app-profile-${width}.png`),fullPage:true});
 await page.goto('/settings?section=services');await expect(page.getByLabel('SMTP 服务地址',{exact:true})).toBeVisible();await page.screenshot({path:path.join(output,`app-smtp-${width}.png`),fullPage:true});await page.getByRole('button',{name:'应用 SMTP 配置',exact:true}).scrollIntoViewIfNeeded();await expect(page.getByRole('button',{name:'应用 SMTP 配置',exact:true})).toBeInViewport();await page.getByRole('button',{name:'发送测试邮件',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,`app-smtp-bottom-${width}.png`)});
 await page.goto('/status');await expect(page.locator('.servers-bar')).toBeAttached();
 if(width>768){const server=await page.locator('.servers-bar').boundingBox();expect(server!.width).toBe(208);expect(server!.x).toBe(264);const savedFold=page.waitForResponse(r=>r.url()===base+'/operations/backups/client-preferences'&&r.request().method()==='PUT'&&r.request().postDataJSON().ui.serversFold===true);await page.getByRole('button',{name:'收起列表',exact:true}).click();await savedFold;await page.screenshot({path:path.join(output,`app-servers-folded-${width}.png`)});await page.reload();await expect(page.getByRole('button',{name:'展开列表',exact:true})).toBeVisible();await page.getByRole('button',{name:'展开列表',exact:true}).click();await page.getByRole('button',{name:'工具',exact:true}).click();await expect(page.getByRole('button',{name:'MTR',exact:true})).toBeVisible();}
 else {await expect(page.locator('.servers-mobile-nav .dd-btn')).toBeVisible();await page.locator('.servers-mobile-nav .dd-btn').click();await expect(page.getByRole('option',{name:/打流/})).toBeVisible();await expect(page.getByRole('option',{name:/MTR/})).toBeVisible();await expect(page.getByRole('option',{name:/记录/})).toBeVisible();await page.keyboard.press('Escape');}
 await page.screenshot({path:path.join(output,`app-servers-${width}.png`),fullPage:true});expect(fixture.unknown).toEqual([]);expect(fixture.errors).toEqual([]);expect(fixture.writes).toEqual(['/auth/me']);
});
// Real App/store/controller and the merged controls.css, not the standalone fixture CSS.
for(const width of [1365,1920,390,320])test(`built App combined appearance ${width}`,async({page})=>{
 const f=await setup(page);await page.setViewportSize({width,height:900});
 await page.goto('/settings?section=appearance');
 const synced=()=>expect(page.locator('.appearance-sync')).toHaveText('账号已同步');
 const mode=page.getByRole('switch',{name:'调色模式',exact:true});
 const part=(id:string)=>page.locator(`[data-theme-part="${id}"]`);
 const color=page.getByLabel('颜色值',{exact:true});
 const palette=()=>page.evaluate(()=>document.documentElement.getAttribute('style'));
 const style=async(selector:string,property:string,pseudo:string|null=null)=>page.locator(selector).first().evaluate((e,{property,pseudo})=>getComputedStyle(e,pseudo).getPropertyValue(property),{property,pseudo});
 const paint=async(id:string,value:string,property?:string)=>{await part(id).click();if(property)await page.getByRole('button',{name:property,exact:true}).click();await color.fill(value);await page.getByRole('button',{name:'完成调色',exact:true}).click();await synced();};
 await synced();expect(f.preferenceWrites).toHaveLength(0);
 const initial=await palette();await mode.click();await mode.click();expect(await palette()).toBe(initial);expect(f.preferenceWrites).toHaveLength(0);
 await part('primary').focus();await page.keyboard.press('Enter');await expect(color).toBeFocused();expect(await palette()).toBe(initial);await color.fill('#123456');await page.keyboard.press('Escape');await expect(part('primary')).toBeFocused();expect(await palette()).toBe(initial);
 const profile=async()=>{if(width>768)await page.getByRole('link',{name:'我的资料',exact:true}).click();else{await page.locator('.settings-mobile-nav .dd-btn').click();await page.getByRole('option',{name:/我的资料/}).click();}};
 const presets:Record<string,any>={};
 for(const [label,key] of [['A · 暮紫 × 桃粉','A'],['B · 鸢尾蓝 × 珊瑚','B']]){
  await page.getByRole('button',{name:label,exact:true}).click();await synced();
  presets[key]={input:await style('[aria-label="样板名称"]','background-color'),primary:await style('.sample-actions .is-primary','background-image',width<=768?'::before':null)};
  await profile();await expect(page.locator('#profile-name')).toBeVisible();await page.locator('#profile-name').fill('颜色接线草稿');
  expect(await style('#profile-name','background-color')).toBe(presets[key].input);
  expect(await style('.profile-settings .is-primary','background-image',width<=768?'::before':null)).toBe(presets[key].primary);
  await page.goto('/settings?section=appearance');await synced();
 }
 await paint('primary','#123456');await paint('input','#234567');await paint('nav','#345678');await paint('nav','#182938','侧栏底色');await paint('overlay','#303142');await paint('cpu','#C0FFEE');
 expect(await part('cpu').locator('path').nth(1).getAttribute('stroke')).toBe('#C0FFEE');
 await page.getByRole('button',{name:'A · 暮紫 × 桃粉',exact:true}).click();await synced();await page.getByRole('button',{name:'自定义',exact:true}).click();await synced();await page.reload();await synced();
 expect(f.preferenceWrites.at(-1).customAppearance.overrides['control-bg']).toBe('#234567');
 const sampleInput=await style('[aria-label="样板名称"]','background-color'),sampleButton=await style('.sample-actions .is-primary','background-image',width<=768?'::before':null);
 await page.screenshot({path:path.join(output,`app-appearance-${width}.png`),fullPage:true});await part('cpu').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,`app-appearance-metrics-${width}.png`)});
 if(width>768)expect(await style('.sidebar','background-color')).toBe('rgb(24, 41, 56)');
 // Selecting, switching modes and trial interactions must not write preferences/business.
 const writes=f.preferenceWrites.length,beforeMode=await palette();await mode.click();expect(await palette()).toBe(beforeMode);
 await page.getByRole('button',{name:'每日摘要',exact:true}).focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'仅重要提醒',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'样板帮助',exact:true}).click();await expect(page.locator('.sample-portal [role=tooltip]')).toBeVisible();expect(await style('.sample-portal [role=tooltip]','background-color')).toBe('rgb(48, 49, 66)');await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'仅重要提醒',exact:true}).click();expect(await style('.appearance-sandbox .dd-menu','background-color')).toBe('rgb(48, 49, 66)');await page.keyboard.press('Escape');
 const trigger=page.getByRole('button',{name:'删除示例',exact:true});await trigger.click();await expect(page.locator('.sample-portal dialog')).toBeVisible();expect(await style('.sample-portal dialog','background-color')).toBe('rgb(48, 49, 66)');await page.keyboard.press('Escape');await expect(trigger).toBeFocused();expect(f.preferenceWrites).toHaveLength(writes);
 await profile();await expect(page.locator('#profile-name')).toBeVisible();await page.locator('#profile-name').fill('颜色接线草稿');
 expect(await style('#profile-name','background-color')).toBe(sampleInput);expect(await style('.profile-settings .is-primary','background-image',width<=768?'::before':null)).toBe(sampleButton);
 if(width>768){await expect.poll(()=>style('.settings-side [aria-current=page]','background-color')).toBe('rgb(52, 86, 120)');}
 await page.screenshot({path:path.join(output,`app-custom-profile-${width}.png`),fullPage:true});
 await page.goto('/settings?section=appearance');await synced();await mode.click();await paint('input','#456789');
 // A failed committed color survives a full reload and explicit local conflict resolution.
 f.failPreferences(true);await part('cpu').click();await color.fill('#FEDCBA');await page.getByRole('button',{name:'完成调色',exact:true}).click();await expect(page.getByRole('button',{name:'重试同步',exact:true})).toBeVisible();
 f.failPreferences(false);await page.reload();await expect(page.getByRole('button',{name:'保留本机',exact:true})).toBeVisible();expect(await part('cpu').locator('path').nth(1).getAttribute('stroke')).toBe('#FEDCBA');await page.getByRole('button',{name:'保留本机',exact:true}).click();await synced();
 await part('primary').click();await color.fill('#AABBCC');const panel=await page.locator('.color-panel').boundingBox();expect(panel!.x).toBeGreaterThanOrEqual(0);await expect.poll(async()=>{const r=await page.locator('.color-panel').boundingBox();return r!.y+r!.height;}).toBeLessThanOrEqual(900);
 for(const name of ['单项重置','取消本次','完成调色']){const button=page.getByRole('button',{name,exact:true});await button.scrollIntoViewIfNeeded();await expect(button).toBeInViewport();}
 await page.screenshot({path:path.join(output,`app-editor-${width}.png`)});await page.keyboard.press('Escape');await expect(part('primary')).toBeFocused();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.writes).toEqual([]);
 await writeFile(path.join(output,`combined-${width}.json`),JSON.stringify({width,presets,preferenceWrites:f.preferenceWrites,unknown:f.unknown,errors:f.errors,businessWrites:f.writes},null,2));
});
test('actual App HTTP boundary rejects unknown paths, queries and methods',async({page})=>{
 const f=await setup(page);await page.goto('/settings?section=appearance');await expect(page.locator('.appearance-sync')).toHaveText('账号已同步');
 const statuses=await page.evaluate(async()=>{const call=async(url:string,method='GET')=>{try{return (await fetch(url,{method})).status;}catch{return 'blocked';}};return Promise.all([call('/operations/backups/client-preferences?unexpected=1'),call('/unknown-fixture-route'),call('/navigation','DELETE')]);});
 expect(statuses).toEqual([500,500,'blocked']);expect(f.unknown).toEqual(['GET /operations/backups/client-preferences?unexpected=1','GET /unknown-fixture-route','DELETE /navigation']);expect(f.errors).toEqual([]);
});
for(const width of [1365,320])test(`built App callback dirty-navigation seam ${width}`,async({page})=>{
 const f=await setup(page);await page.setViewportSize({width,height:900});await page.goto('/settings?section=authentication');
 await page.getByText('已连接应用（1）',{exact:true}).click();await page.locator('[data-client-details]>summary').click();await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByLabel('应用名称',{exact:true}).fill('尚未提交的应用草稿');
 const navigate=async()=>{if(width>768)await page.getByRole('link',{name:'外观',exact:true}).click();else{await page.locator('.settings-mobile-nav .dd-btn').click();await page.getByRole('option',{name:/外观/}).click();}};
 await navigate();await expect(page.getByRole('alertdialog',{name:'尚有未保存的应用配置'})).toBeVisible();await page.getByRole('button',{name:'继续编辑',exact:true}).click();await expect(page.getByLabel('应用名称',{exact:true})).toHaveValue('尚未提交的应用草稿');expect(page.url()).toContain('section=authentication');
 await navigate();await page.getByRole('button',{name:'放弃草稿并离开',exact:true}).click();await expect(page.locator('.appearance-sync')).toHaveText('账号已同步');expect(page.url()).toContain('section=appearance');expect(f.writes).toEqual([]);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
 await page.screenshot({path:path.join(output,`app-callback-return-${width}.png`)});
});
test('native browser zoom 200%, short viewport and folded mobile entry',async()=>{
 const scratch=await mkdtemp(path.join(tmpdir(),'stella-native-zoom-')),extension=path.join(scratch,'extension');await mkdir(extension);
 await writeFile(path.join(extension,'manifest.json'),JSON.stringify({manifest_version:3,name:'Isolated native zoom acceptance',version:'1.0',permissions:['tabs'],background:{service_worker:'worker.js'}}));await writeFile(path.join(extension,'worker.js'),'chrome.runtime.onInstalled.addListener(()=>{});');
 const context=await chromium.launchPersistentContext(path.join(scratch,'profile'),{headless:true,executablePath:chromium.executablePath(),args:['--no-sandbox',`--disable-extensions-except=${extension}`,`--load-extension=${extension}`],viewport:{width:1365,height:700},reducedMotion:'reduce'});
 try{
  const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker');const page=await context.newPage(),fixture=await setup(page,true);await page.goto(base+'/settings');await expect(page.locator('#profile-name')).toBeVisible();
  const zoom=await worker.evaluate(async base=>{const chrome=(globalThis as any).chrome;const tabs=await chrome.tabs.query({});const tab=tabs.find((t:any)=>t.url.startsWith(base));await chrome.tabs.setZoom(tab.id,2);return chrome.tabs.getZoom(tab.id);},base);expect(zoom).toBe(2);await expect.poll(()=>page.evaluate(()=>innerWidth)).toBe(682);
  await expect(page.locator('.settings-mobile-nav .dd-btn')).toBeVisible();await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await expect(page.locator('#profile-email-draft')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:path.join(output,'app-profile-native-200.png'),fullPage:true});
  await page.goto(base+'/status');await expect(page.locator('.servers-mobile-nav .dd-btn')).toBeVisible();await page.locator('.servers-mobile-nav .dd-btn').click();await expect(page.getByRole('option',{name:/MTR/})).toBeVisible();const menu=await page.locator('.servers-mobile-nav .dd-menu').boundingBox();expect(menu!.y+menu!.height).toBeLessThanOrEqual(await page.evaluate(()=>innerHeight));const records=page.getByRole('option',{name:/记录/});await records.scrollIntoViewIfNeeded();await expect(records).toBeInViewport();await page.screenshot({path:path.join(output,'app-servers-native-200-short.png')});await page.keyboard.press('Escape');expect(fixture.unknown).toEqual([]);expect(fixture.errors).toEqual([]);
  await page.goto(base+'/settings?section=appearance');await expect(page.locator('.appearance-sync')).toHaveText('账号已同步');await page.locator('[data-theme-part="primary"]').click();await page.getByLabel('颜色值',{exact:true}).fill('#AABBCC');
  await expect.poll(async()=>{const r=await page.locator('.color-panel').boundingBox();return r!.y+r!.height;}).toBeLessThanOrEqual(350);
  for(const name of ['单项重置','取消本次','完成调色']){await page.keyboard.press('Tab');const button=page.getByRole('button',{name,exact:true});await expect(button).toBeFocused();await expect(button).toBeInViewport();}
  await page.screenshot({path:path.join(output,'app-appearance-native-200-short.png')});await page.keyboard.press('Escape');await expect(page.locator('[data-theme-part="primary"]')).toBeFocused();expect(fixture.unknown).toEqual([]);expect(fixture.errors).toEqual([]);
  await writeFile(path.join(output,'native-zoom.json'),JSON.stringify({zoom,viewport:{width:1365,height:700},effective:await page.evaluate(()=>({width:innerWidth,height:innerHeight,devicePixelRatio})),unknown:fixture.unknown,errors:fixture.errors},null,2));
 }finally{await context.close();await rm(scratch,{recursive:true,force:true});}
});
