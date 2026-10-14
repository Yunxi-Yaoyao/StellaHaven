import {test,expect,type Page} from '@playwright/test';
import {mock as settingsFixture} from '../settings-mocks';
import path from 'node:path';
const evidence=process.env.STELLA_LOGIN_QA_OUTPUT||process.env.TMPDIR+'/stella-login-modal-evidence';
const owner={id:'fixture-owner',username:'fixture',display_name:'Fixture owner',is_admin:false,avatar_url:'',home_bg:'/seed/showcase-image.svg',email:'',email_verified:false};
const doc={id:'fixture-note',title:'Fixture private note',file_path:'/fixture.md',workspace_id:'fixture-workspace',parent_id:null,content:'# Fixture private body',content_hash:'fixture',status:'active',is_folder:false,is_pinned:false,is_favorite:false,created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z',draft_updated_at:null,draft_device:null,has_draft:false};
async function fixture(page:Page,{signed=false,initialized=true}={}){
 const state={signed,expired:false,invalid:false,offline:false,privateRequests:[] as string[],unexpected:[] as string[],errors:[] as string[]};
 page.on('pageerror',e=>state.errors.push(e.message));
 await page.addInitScript(()=>{localStorage.setItem('stella_note_edit_mode','markdown');localStorage.setItem('stella_home_theme','daybreak');});
 await page.routeWebSocket('**/*',ws=>{ws.onMessage(()=>{});});
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(url.origin!=='http://127.0.0.1:15274'){await route.abort();return;}
  const send=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(p==='/auth/status')return send({has_users:initialized,initialized,email_enabled:true});
  if(p==='/config/site-background')return send({value:'/seed/showcase-image.svg'});
  // Match the real router's public metadata GET; lists and writes remain protected below.
  if(p==='/homebg/media'&&req.method()==='GET'){const value=url.searchParams.get('url');return send({url:value,status:'ready',poster:null,variants:{original:value}});}
  if(p==='/auth/me'||p==='/auth/refresh')return send(state.signed&&!state.expired?owner:{detail:'fixture unauthenticated'},state.signed&&!state.expired?200:401);
  if(['/auth/login','/auth/register','/auth/login-code'].includes(p)){
   if(state.offline)return route.abort('failed');
   if(state.invalid)return send({detail:'Fixture: 账号或密码不正确'},401);
   state.signed=true;state.expired=false;return send(owner);
  }
  if(p==='/auth/logout'){state.signed=false;return send({ok:true});}
  if(p.startsWith('/auth/')||/^\/(navigation|external-modules|workspaces|documents|tags|doc-tags|document-links|homebg|notifications|config)/.test(p)){
   state.privateRequests.push(req.method()+' '+p);
   if(!state.signed||state.expired)return send({detail:'fixture unauthenticated'},401);
   if(p==='/auth/security')return send({enabled:true,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
   if(p==='/auth/activity')return send({ok:true});
   if(p==='/external-modules')return send([]);
   if(p==='/navigation')return send({modules:[],entries:[{id:'home',kind:'builtin',label:'主页',icon:'home',order:0,visible:true},{id:'notes',kind:'builtin',label:'笔记',icon:'book',order:1,visible:true},{id:'settings',kind:'builtin',label:'设置',icon:'settings',order:2,visible:true}]});
   if(p.startsWith('/workspaces'))return send(p.endsWith('/fixture-workspace')?{id:'fixture-workspace',name:'Fixture workspace',user_id:owner.id}:[{id:'fixture-workspace',name:'Fixture workspace',user_id:owner.id}]);
   if(p==='/documents/')return send([doc]);
   if(p==='/documents/fixture-note')return send(doc);
   if(p==='/documents/fixture-note/draft')return send({detail:'no draft'},404);
   if(p==='/documents/recent')return send([doc]);
   if(p==='/documents/fixture-note/backlinks'||p==='/notifications')return send([]);
   if(p==='/notifications/unread-count')return send({count:0});
   if(p==='/config/public-host')return send({value:''});
   if(p==='/auth/sessions')return send([]);
   if(p==='/auth/email-service')return send({enabled:false});
   if(p==='/auth/avatars'||p.startsWith('/tags')||p.startsWith('/doc-tags')||p.startsWith('/document-links')||p.startsWith('/homebg')||p==='/documents/trash')return send([]);
   state.unexpected.push(req.method()+' '+p);return send({detail:'unhandled fixture'},501);
  }
  await route.continue();
 });
 return state;
}
async function modal(page:Page){const dialog=page.getByRole('dialog',{name:'Stella 登录'});await expect(dialog).toBeVisible();await expect(page.getByText('欢迎回港',{exact:true})).toBeVisible();await dialog.evaluate(el=>Promise.all(el.getAnimations().map(a=>a.finished)));return dialog;}
async function login(page:Page){const dialog=await modal(page);await dialog.locator('input[autocomplete="username"]').fill('fixture');await dialog.locator('input[type="password"]').fill('FIXTURE_ONLY_NOT_A_SECRET');await dialog.getByRole('button',{name:'回港',exact:true}).click();await expect(dialog).toBeHidden();}
async function screenshot(page:Page,name:string){await page.screenshot({path:path.join(evidence,name+'.png')});}

test('public login stays on page, preserves background, restores focus, and traps keyboard',async({page})=>{
 const state=await fixture(page);await page.goto('/');const account=page.locator('.account');await account.click();const dialog=await modal(page);
 expect(new URL(page.url()).pathname).toBe('/');await expect(page.locator('.shell')).toHaveAttribute('inert','');
 expect(await page.locator('.auth').evaluate(el=>getComputedStyle(el).backdropFilter)).toContain('blur');
 const rect=await dialog.boundingBox();expect(Math.abs(rect!.x+rect!.width/2-720)).toBeLessThan(2);expect(Math.abs(rect!.y+rect!.height/2-450)).toBeLessThan(2);
 await screenshot(page,'desktop-public-modal');
 for(let i=0;i<14;i++){await page.keyboard.press('Tab');expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);}
 await page.keyboard.press('Escape');await expect(dialog).toBeHidden();await expect(account).toBeFocused();expect(state.privateRequests).toEqual([]);expect(state.errors).toEqual([]);
});
test('mobile public login closes drawer and restores focus to visible hamburger',async({page})=>{
 await page.setViewportSize({width:393,height:852});await fixture(page);await page.goto('/');await page.locator('.hamburger').click();await page.locator('.account').click();const dialog=await modal(page);await screenshot(page,'mobile-public-modal');await page.keyboard.press('Escape');await expect(dialog).toBeHidden();await expect(page.locator('.hamburger')).toBeFocused();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('authenticated legacy login link needs no new login prompt',async({page})=>{
 await fixture(page,{signed:true});await page.goto('/login?next=%2Fnotes');await expect(page).toHaveURL('http://127.0.0.1:15274/notes');await expect(page.getByText('Fixture private note',{exact:true}).first()).toBeVisible();await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(0);
});
test('direct notes keeps URL, mounts no private content or private API, closes safely',async({page})=>{
 const state=await fixture(page);await page.goto('/notes?doc=fixture-note');await modal(page);
 expect(new URL(page.url()).pathname).toBe('/notes');await expect(page.locator('.notes-page,.editor')).toHaveCount(0);expect(state.privateRequests).toEqual([]);
 await screenshot(page,'desktop-direct-notes-modal');await page.getByRole('button',{name:'关闭登录'}).click();await expect(page).toHaveURL('http://127.0.0.1:15274/');await expect(page.getByRole('dialog')).toBeHidden();expect(state.errors).toEqual([]);
});
test('all protected guest entry points retain URL without private business calls',async({page})=>{
 const state=await fixture(page);
 for(const target of ['/settings','/status/19','/apps/fixture-module']){await page.goto(target);await modal(page);await expect(page).toHaveURL('http://127.0.0.1:15274'+target);expect(state.privateRequests).toEqual([]);}
 expect(state.errors).toEqual([]);
});
test('successful login renders real NotesPage at original target, expiry preserves unsaved editor and stops private updates',async({page})=>{
 const state=await fixture(page);await page.clock.install();await page.goto('/notes');await login(page);
 await expect(page.getByText('Fixture private note',{exact:true}).first()).toBeVisible();await page.getByRole('button',{name:'编辑',exact:true}).click();
 const editor=page.locator('.cm-content');await expect(editor).toBeVisible();await editor.fill('Fixture unsaved editor retained');
 await screenshot(page,'notes-before-expiry');state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);
 await expect(editor).toContainText('Fixture unsaved editor retained');await expect(page.locator('.shell')).toHaveAttribute('inert','');expect(new URL(page.url()).pathname).toBe('/notes');
 const count=state.privateRequests.length;await page.clock.fastForward(35000);expect(state.privateRequests.length).toBe(count);
 await screenshot(page,'notes-expired-modal');await login(page);await expect(editor).toContainText('Fixture unsaved editor retained');expect(new URL(page.url()).pathname).toBe('/notes');expect(state.unexpected).toEqual([]);expect(state.errors).toEqual([]);
});
test('rich editor retains its unsaved contents across expiry and same-owner reauthentication',async({page})=>{
 const state=await fixture(page,{signed:true});await page.clock.install();await page.goto('/notes');await expect(page.getByText('Fixture private note',{exact:true}).first()).toBeVisible();await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'所见即所得',exact:true}).click();
 const editor=page.locator('.rich-editor [contenteditable="true"]').first();await expect(editor).toBeVisible();await editor.click();await page.keyboard.press('Control+A');await page.keyboard.insertText('Fixture rich unsaved retained');await expect(editor).toContainText('Fixture rich unsaved retained');
 state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);await expect(editor).toContainText('Fixture rich unsaved retained');await screenshot(page,'rich-expired-modal');await login(page);await expect(editor).toContainText('Fixture rich unsaved retained');expect(state.errors).toEqual([]);
});
test('legacy login next links open modal at safe target rather than a separate page',async({page})=>{
 const state=await fixture(page);await page.goto('/login?next=%2Fnotes');await modal(page);await expect(page).toHaveURL('http://127.0.0.1:15274/notes');expect(state.privateRequests).toEqual([]);
 await page.goto('/login?next=%2F%2Fevil.example');await modal(page);await expect(page).toHaveURL('http://127.0.0.1:15274/');
});
test('narrow viewport supports errors, keyboard email phases, and retry',async({page})=>{
 await page.setViewportSize({width:393,height:852});const state=await fixture(page);await page.goto('/notes');const dialog=await modal(page);state.invalid=true;await dialog.getByRole('button',{name:'回港',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('Fixture:');
 state.invalid=false;state.offline=true;await dialog.getByRole('button',{name:'回港',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('连接失败');await expect(dialog.getByRole('button',{name:'回港',exact:true})).toBeEnabled();
 await screenshot(page,'mobile-error-modal');const rect=await dialog.boundingBox();expect(rect!.x).toBeGreaterThanOrEqual(0);expect(rect!.x+rect!.width).toBeLessThanOrEqual(393);expect(rect!.y+rect!.height).toBeLessThanOrEqual(852);
 await dialog.getByRole('button',{name:'忘记密码？'}).focus();await page.keyboard.press('Enter');await expect(dialog.getByText('忘记密码',{exact:true})).toBeVisible();await page.keyboard.press('Escape');await expect(dialog).toBeHidden();expect(state.errors).toEqual([]);
});
test('initialization uses existing guide and form within centered modal',async({page})=>{
 const state=await fixture(page,{initialized:false});await page.goto('/login');const dialog=page.getByRole('dialog',{name:'Stella 登录'});await expect(dialog.getByRole('button',{name:'开始初始化'})).toBeVisible();await dialog.getByRole('button',{name:'开始初始化'}).click();await expect(dialog.getByText('创建唯一账号',{exact:true})).toBeVisible();await screenshot(page,'initialization-modal');
 await dialog.locator('input[autocomplete="username"]').fill('fixture');await dialog.locator('input[type="password"]').fill('FIXTURE_ONLY_NOT_A_SECRET');await dialog.getByRole('button',{name:'点亮港口'}).click();await expect(dialog).toBeHidden();expect(new URL(page.url()).pathname).toBe('/');expect(state.errors).toEqual([]);
});
test('expired protected close returns public with no retained private content visible',async({page})=>{
 const state=await fixture(page,{signed:true});await page.clock.install();await page.goto('/notes');await expect(page.getByText('Fixture private note',{exact:true}).first()).toBeVisible();state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);await page.getByRole('button',{name:'关闭登录'}).click();await expect(page).toHaveURL('http://127.0.0.1:15274/');await expect(page.getByRole('dialog')).toBeHidden();await expect(page.getByText('Fixture private note',{exact:true})).toHaveCount(0);expect(state.errors).toEqual([]);
});
test('existing management-password dialog stays distinct; rejected management password never opens login',async({page})=>{
 const m=await settingsFixture(page,true,'http://127.0.0.1:15274');await page.route('**/static/**',route=>route.continue());await page.routeWebSocket('**/*',ws=>ws.onMessage(()=>{}));
 await page.route('**/auth/admin/unlock',route=>route.fulfill({status:401,json:{detail:'Fixture wrong management password'}}));
 await page.goto('/settings?section=navigation');await page.getByRole('button',{name:'编辑 笔记',exact:true}).click();await page.getByLabel('显示名称',{exact:true}).fill('Fixture notes');await page.locator('.inline-editor').getByRole('button',{name:'保存',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'解锁管理权限'});await expect(dialog).toBeVisible();await dialog.getByLabel('管理密码',{exact:true}).fill('FIXTURE_ONLY_MANAGEMENT');await dialog.getByRole('button',{name:'验证管理权限',exact:true}).click();await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(0);await expect(dialog).toBeVisible();await screenshot(page,'management-modal-distinct');expect(m.requests.filter(r=>r.path==='/auth/refresh')).toHaveLength(0);
});
test('logout removes private content before returning to public modal',async({page})=>{
 const state=await fixture(page,{signed:true});await page.goto('/settings');await expect(page.getByRole('button',{name:'退出登录',exact:true})).toBeVisible();await page.getByRole('button',{name:'退出登录',exact:true}).click();await modal(page);await expect(page.getByText('Fixture owner',{exact:true})).toHaveCount(0);await expect(page.locator('.settings-page')).toHaveCount(0);expect(state.errors).toEqual([]);
});
