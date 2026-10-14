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
  if(p==='/homebg/media'&&req.method()==='GET'){const value=url.searchParams.get('url');return send({url:value,status:'ready',poster:'/seed/showcase-image.svg',variants:{original:value,compressed1:'/assets/homebg/review-consumer-small.mp4'}});}
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

test('review: rejected logout is surfaced instead of stranding user in login',async({page})=>{
 const state=await fixture(page,{signed:true});let attempts=0;
 await page.route('**/auth/logout',route=>{attempts++;if(attempts===1)return route.fulfill({status:503,json:{detail:'fixture logout unavailable'}});state.signed=false;return route.fulfill({status:200,json:{ok:true}});});
 await page.goto('/settings');await page.locator('main.content .page').evaluate(el=>el.setAttribute('data-instance','kept'));await page.getByRole('button',{name:'退出登录',exact:true}).click();
 await page.waitForTimeout(300);
 expect(state.errors).toEqual([]);
 await expect(page.getByText('退出未成功，请检查网络后重试',{exact:false})).toBeVisible();
 await expect(page.locator('main.content .page')).toHaveAttribute('data-instance','kept');
 await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(0);
 await screenshot(page,'logout-503-retry');await page.getByRole('button',{name:'退出登录',exact:true}).click();await modal(page);
 expect(attempts).toBe(2);expect(state.errors).toEqual([]);
});
test('review: pending logout serializes cookie clearing before a new login',async({page})=>{
 const state=await fixture(page,{signed:true});let release!:(v?:unknown)=>void;let loginRequests=0;
 const gate=new Promise(resolve=>release=resolve);
 await page.context().addCookies([{name:'access_token',value:'fixture-old',url:'http://127.0.0.1:15274',httpOnly:true,sameSite:'Lax'}]);
 await page.route('**/auth/login',route=>{state.signed=true;state.expired=false;return route.fulfill({json:owner,headers:{'Set-Cookie':'access_token=fixture-new; Path=/; HttpOnly; SameSite=Lax'}});});
 page.on('request',r=>{if(new URL(r.url()).pathname==='/auth/login')loginRequests++;});
 await page.route('**/auth/logout',async route=>{await gate;state.signed=false;await route.fulfill({status:200,json:{ok:true},headers:{'Set-Cookie':'access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0'}});});
 await page.goto('/settings');await page.getByRole('button',{name:'退出登录',exact:true}).click();
 await page.waitForTimeout(300);
 await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(0);
 expect(loginRequests).toBe(0);await screenshot(page,'logout-pending-serialized');
 release();await login(page);await page.waitForTimeout(500);
 await expect(page.getByRole('dialog',{name:'Stella 登录'})).toBeHidden();
 expect(loginRequests).toBe(1);const cookie=(await page.context().cookies()).find(c=>c.name==='access_token');expect(cookie?.value).toBe('fixture-new');expect(cookie?.httpOnly).toBe(true);expect(state.errors).toEqual([]);
});
test('review: a delayed private image must not load after suspension',async({page})=>{
 const state=await fixture(page,{signed:true});const id='fedcba98-7654-3210-fedc-ba9876543210';let release!:(v?:unknown)=>void;
 const gate=new Promise(resolve=>release=resolve);let started=false;
 await page.route('**/documents/fixture-note',route=>route.fulfill({status:200,json:{...doc,content:'![Delayed private image](/attachments/'+id+')'}}));
 await page.route('**/attachments/'+id,async route=>{started=true;await gate;await route.fulfill({status:200,contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'});});
 await page.clock.install();await page.goto('/notes',{waitUntil:'domcontentloaded'});
 await expect.poll(()=>started).toBe(true);state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);
 const image=page.locator('.preview img');expect(await image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(0);
 release();await page.waitForTimeout(300);
 expect(await image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(0);
});
test('review control: native attachment images and markdown zip export work while signed in',async({page})=>{
 const state=await fixture(page,{signed:true});const id='01234567-89ab-cdef-0123-456789abcdef';
 await page.route('**/documents/fixture-note',route=>route.fulfill({status:200,json:{...doc,content:'![Fixture image](/attachments/'+id+')'}}));
 await page.route('**/attachments/*',route=>route.fulfill({status:200,contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'}));
 await page.goto('/notes');const image=page.locator('.preview img');await expect(image).toBeVisible();
 expect(await image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(10);
 await page.getByRole('button',{name:'导出',exact:true}).click();
 const receipt=page.waitForEvent('download');await page.getByRole('button',{name:'确定导出',exact:true}).click();
 const download=await receipt;expect(download.suggestedFilename()).toContain('含附件.zip');expect(await download.failure()).toBeNull();expect(state.errors).toEqual([]);
});

test('review: loaded attachment and unsaved markdown survive expiry while new private media is refused',async({page})=>{
 const state=await fixture(page,{signed:true});const id='01234567-89ab-cdef-0123-456789abcdef';let requests=0;
 await page.route('**/documents/fixture-note',route=>route.fulfill({json:{...doc,content:'![Loaded private image](/attachments/'+id+')\n\nDraft text'}}));
 await page.route('**/attachments/*',route=>{requests++;return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'});});
 await page.clock.install();await page.goto('/notes');const image=page.locator('.preview img');
 await expect.poll(()=>image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(10);
 await image.evaluate(el=>el.setAttribute('data-instance','kept'));
 await page.getByRole('button',{name:'编辑',exact:true}).click();const editor=page.locator('.cm-content');
 await editor.fill('![Loaded private image](/attachments/'+id+')\n\nUNSAVED media draft');
 await expect.poll(()=>image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(10);
 await image.evaluate(el=>el.setAttribute('data-instance','draft-kept'));state.expired=true;
 await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);
 await expect(image).toHaveAttribute('data-instance','draft-kept');expect(await image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(10);
 const count=requests;
 // Probe the real media consumer's admission boundary, without changing stored/editor Markdown.
 await page.locator('.preview').evaluate(el=>{const img=document.createElement('img');img.setAttribute('data-private-src','/attachments/refused-during-suspension');img.alt='refused';el.append(img);});
 await page.waitForTimeout(150);expect(requests).toBe(count);
 await expect(editor).toContainText('UNSAVED media draft');await screenshot(page,'media-loaded-draft-expired');
 await page.locator('img[alt="refused"]').evaluate(el=>el.remove());await login(page);
 await expect(image).toHaveAttribute('data-instance','draft-kept');await expect(editor).toContainText('UNSAVED media draft');expect(requests).toBe(count);expect(state.errors).toEqual([]);
});

test('review: rich attachment display keeps source URL and HTML zip export uses relative URLs',async({page})=>{
 const state=await fixture(page,{signed:true});const id='01234567-89ab-cdef-0123-456789abcdef';
 await page.route('**/documents/fixture-note',route=>route.fulfill({json:{...doc,content:'![Rich private image](/attachments/'+id+')\n\nOriginal rich text'}}));
 await page.route('**/attachments/*',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'}));
 await page.clock.install();await page.goto('/notes');await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'所见即所得',exact:true}).click();
 const image=page.locator('.rich-editor img[data-private-src]');await expect.poll(()=>image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(10);
 await image.evaluate(el=>el.setAttribute('data-instance','rich-kept'));
 const editor=page.locator('.rich-editor [contenteditable="true"]').first();await editor.click();await page.keyboard.press('Control+End');await page.keyboard.insertText(' UNSAVED rich media');
 state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);
 await expect(image).toHaveAttribute('data-instance','rich-kept');expect(await image.evaluate(el=>(el as HTMLImageElement).naturalWidth)).toBe(10);await screenshot(page,'rich-media-expired');
 await login(page);await expect(editor).toContainText('UNSAVED rich media');await expect(image).toHaveAttribute('data-instance','rich-kept');
 await page.getByRole('button',{name:'导出',exact:true}).click();await page.getByText('HTML 网页',{exact:true}).click();
 const receipt=page.waitForEvent('download');await page.getByRole('button',{name:'确定导出',exact:true}).click();const download=await receipt;
 const {readFile}=await import('node:fs/promises');const {default:JSZip}=await import('jszip');const zip=await JSZip.loadAsync(await readFile((await download.path())!));
 const file=Object.values(zip.files).find(f=>f.name.endsWith('.html'))!;const html=await file.async('string');
 expect(html).toContain('src="attachments/01234567.svg"');expect(html).not.toContain('blob:');expect(html).not.toContain('data-private-src');expect(html).toContain('UNSAVED rich media');expect(await download.failure()).toBeNull();expect(state.errors).toEqual([]);
});

test('review: guest background consumer selects compressed1 and poster from public metadata',async({page})=>{
 const state=await fixture(page);
 await page.route('**/config/site-background',route=>route.fulfill({json:{value:'/assets/homebg/review-consumer.mp4'}}));
 await page.route('**/assets/homebg/review-consumer-small.mp4',route=>route.fulfill({path:path.resolve('e2e/login-modal/fixture-video.mp4'),contentType:'video/mp4'}));
 await page.goto('/');const video=page.locator('.bg-layer video');
 await expect(video).toHaveAttribute('src','/assets/homebg/review-consumer-small.mp4');await expect(video).toHaveAttribute('poster','/seed/showcase-image.svg');
 await screenshot(page,'guest-compressed-poster');expect(state.privateRequests).toEqual([]);expect(state.errors).toEqual([]);
});
