import {test,expect,type Page} from '@playwright/test';
import {mock as settingsFixture} from '../settings-mocks';
import {createClientPreferencesFixture} from '../../tests/fixtures/clientPreferences';
import {createNotesStartupFixture} from '../../tests/fixtures/notesStartup.mjs';
import path from 'node:path';
import {mkdirSync,writeFileSync} from 'node:fs';
const evidence=process.env.STELLA_LOGIN_QA_OUTPUT||process.env.TMPDIR+'/stella-login-modal-evidence';
const consoleLogs=new WeakMap<Page,string[]>();
const fixtureStates=new WeakMap<Page,{unexpected:string[];errors:string[]}>();
test.afterEach(({page})=>{const state=fixtureStates.get(page);if(state){expect(state.unexpected).toEqual([]);expect(state.errors).toEqual([]);}});
test.beforeEach(async({page})=>{const errors:string[]=[];consoleLogs.set(page,errors);page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});});
// Keep injected network/media failures in the evidence; never suppress unrelated runtime errors.
function expectedFixtureError(message:string){return message.startsWith('Failed to load resource:') || message.startsWith('Kt: Network error.') && message.includes('/static/cubism4.es-') || message==='AbortError: 登录后继续';}
test.afterEach(async({page},info)=>{const errors=consoleLogs.get(page)||[];mkdirSync(evidence,{recursive:true});writeFileSync(path.join(evidence,info.title.replace(/[^a-zA-Z0-9_-]/g,'-')+'-console.json'),JSON.stringify({all:errors,knownFixtureErrors:errors.filter(expectedFixtureError),unexpected:errors.filter(message=>!expectedFixtureError(message))},null,2));expect(errors.filter(message=>!expectedFixtureError(message))).toEqual([]);});
const owner={id:'fixture-owner',username:'fixture',display_name:'Fixture owner',is_admin:false,avatar_url:'',home_bg:'/seed/showcase-image.svg',email:'',email_verified:false};
const doc={id:'fixture-note',title:'Fixture private note',file_path:'/fixture.md',workspace_id:'fixture-workspace',parent_id:null,content:'# Fixture private body',content_hash:'fixture',status:'active',is_folder:false,is_pinned:false,is_favorite:false,created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z',draft_updated_at:null,draft_device:null,has_draft:false};
async function fixture(page:Page,{signed=false,initialized=true,storage={}}:{signed?:boolean;initialized?:boolean;storage?:Record<string,string>}={}){
 const notesStartup=createNotesStartupFixture('fixture-workspace');
 const clientPreferences=createClientPreferencesFixture({storage:{stella_note_edit_mode:'markdown',stella_home_theme:'daybreak',...storage},allowWrite:true});
 const state={signed,expired:false,invalid:false,offline:false,privateRequests:[] as string[],unexpected:[] as string[],errors:[] as string[]};
 fixtureStates.set(page,state);
 page.on('pageerror',e=>state.errors.push(e.message));
 await page.addInitScript(()=>{localStorage.setItem('stella_note_edit_mode','markdown');localStorage.setItem('stella_home_theme','daybreak');});
 await page.routeWebSocket('**/*',ws=>{ws.onMessage(()=>{});});
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(req.method()==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(req.url()))return route.fulfill({json:{ip:'192.0.2.1',country:'Fixture'}});
  if(url.origin!=='http://127.0.0.1:15274'){state.unexpected.push(req.method()+' '+req.url());await route.abort();return;}
  const send=(body:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(p==='/operations/backups/client-preferences'&&!url.search&&['GET','PUT'].includes(req.method())&&(!state.signed||state.expired))return send({detail:'fixture unauthenticated'},401);
  const preference=clientPreferences.respond(req.method(),p+url.search,req.method()==='PUT'?req.postDataJSON():undefined);if(preference)return route.fulfill(preference);
  const startup=notesStartup.respond(req.method(),p+url.search,state.signed&&!state.expired);
  if(startup){state.privateRequests.push(req.method()+' '+p);return route.fulfill(startup);}
  if(p==='/auth/status')return send({has_users:initialized,initialized,email_enabled:true});
  if(p==='/attachments/'&&req.method()==='GET')return send(state.signed&&!state.expired?[]:{detail:'fixture unauthenticated'},state.signed&&!state.expired?200:401);
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
   if(req.method()==='GET'&&!url.search&&p==='/auth/provider/config')return send({issuer:'https://stella.test',discovery_url:'https://stella.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.test/auth/authorize',token_endpoint:'https://stella.test/auth/token',userinfo_endpoint:'https://stella.test/auth/userinfo',jwks_uri:'https://stella.test/auth/jwks',clients:[],capabilities:{}});
   if(req.method()==='GET'&&!url.search&&p==='/config/access-entries')return send({settings:{revision:1,enabled:false,public_origin:'',private_origin:null},issuer:null,deployed:{public:'https://stella.test'},websites:[]});
   if(p==='/auth/security')return send({enabled:true,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
   if(p==='/auth/activity')return send({ok:true});
   if(p==='/external-modules')return send([]);
   if(p==='/navigation')return send({revision:1,mutation_id:null,legacy_routes:{},modules:[],entries:[{id:'home',title:'主页',icon:'home',visible:true},{id:'notes',title:'笔记',icon:'book',visible:true},{id:'settings',title:'设置',icon:'settings',visible:true}]});
   if(p.startsWith('/workspaces'))return send(p.endsWith('/fixture-workspace')?{id:'fixture-workspace',name:'Fixture workspace',user_id:owner.id}:[{id:'fixture-workspace',name:'Fixture workspace',user_id:owner.id}]);
   if(p==='/documents/')return send([doc]);
   if(p==='/documents/fixture-note')return send(doc);
   if(p==='/documents/fixture-note/draft')return send({detail:'no draft'},404);
   if(p==='/documents/recent')return send([doc]);
   if(p==='/documents/fixture-note/backlinks'||p==='/notifications')return send([]);
   if(p==='/notifications/unread-count')return send({count:0});
   if(p==='/config/public-host')return send({value:''});
   if(p==='/auth/sessions')return send([]);
   if(p==='/auth/email-service'&&req.method()==='GET'&&!url.search)return send({ready:false});
   if(p==='/auth/avatars'||p.startsWith('/tags')||p.startsWith('/doc-tags')||p.startsWith('/document-links')||p.startsWith('/homebg')||p==='/documents/trash')return send([]);
   state.unexpected.push(req.method()+' '+p);return send({detail:'unhandled fixture'},501);
  }
  if(req.method()==='GET'&&!url.search&&['/operations/backups','/nodes/'].includes(p)){
   state.privateRequests.push(req.method()+' '+p);if(!state.signed||state.expired)return send({detail:'fixture unauthenticated'},401);
   return send(p==='/nodes/'?[]:{config:{revision:1,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0},records:[],job:null,storage:{node:'fixture',available:false,free_bytes:null,error:null},next_run:null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}});
  }
  if(req.method()==='GET'&&(req.isNavigationRequest()||/^\/(static|seed|assets)\//.test(p)||['/favicon.ico','/favicon.svg','/avatar.png','/live2dcubismcore.min.js'].includes(p)))return route.continue();
  state.unexpected.push(req.method()+' '+p+url.search);await route.abort();
 });
 return state;
}
// Exercise the installed route, not the preference helper in isolation.
for(const method of ['GET','PUT'])test(`peer preference route rejects unknown query for ${method}`,async({page},info)=>{
 const state=await fixture(page,{signed:true});await page.goto('/notes');await expect(page.locator('.preview h1')).toBeVisible();expect(state.unexpected).toEqual([]);
 const endpoint='/operations/backups/client-preferences',target=endpoint+'?review_unknown=1';
 const rows=[];
 for(const session of ['owner','expired','guest']){
  state.signed=session!=='guest';state.expired=session==='expired';
  // Read the saved DTO as owner before/after even for denied sessions.
  state.signed=true;state.expired=false;
  const before=await page.evaluate(async p=>await (await fetch(p)).json(),endpoint);
  state.signed=session!=='guest';state.expired=session==='expired';
  const response=await page.evaluate(async({target,method,before})=>{
   const {revision,...content}=before;
   try{const r=await fetch(target,{method,...(method==='PUT'?{headers:{'Content-Type':'application/json'},body:JSON.stringify({...content,ui:{...content.ui,listFold:!content.ui.listFold},expected_revision:revision})}:{})});return {status:r.status,dto:await r.json()};}
   catch{return {status:'aborted',dto:null};}
  },{target,method,before});
  state.signed=true;state.expired=false;
  const after=await page.evaluate(async p=>await (await fetch(p)).json(),endpoint);
  rows.push({session,response,before,after});
 }
 await info.attach('preference-query-boundary.json',{body:JSON.stringify({method,target,rows,unexpected:state.unexpected}),contentType:'application/json'});
 expect.soft(rows.map(row=>row.response)).toEqual(rows.map(()=>({status:'aborted',dto:null})));
 for(const row of rows)expect.soft(row.after,'query never mutates saved owner DTO or revision').toEqual(row.before);
 expect(state.unexpected).toEqual(rows.map(()=>method+' '+target));
 expect(()=>expect(state.unexpected).toEqual([])).toThrow();
 // Consume only the exact, asserted negative controls; afterEach stays strict.
 state.unexpected.splice(0,rows.length);
});

test('peer preference route retains exact DTO, CAS, authentication and Notes query contracts',async({page},info)=>{
 const state=await fixture(page,{signed:true});await page.goto('/notes');await expect(page.locator('.preview h1')).toBeVisible();
 const paths=['/notes-preferences','/notes-tools/templates/fixture-workspace','/web-projects/workspace/fixture-workspace','/detached-sources?workspace_id=fixture-workspace','/operations/backups/client-preferences'];
 const readAll=()=>page.evaluate(async paths=>{const rows=[];for(const path of paths){const r=await fetch(path);rows.push({path,status:r.status,dto:await r.json()});}return rows;},paths);
 const ownerReads=await readAll();expect(ownerReads.map(r=>r.status)).toEqual(paths.map(()=>200));
 const writes=await page.evaluate(async()=>{
  const p='/operations/backups/client-preferences',before=await (await fetch(p)).json(),{revision,...content}=before;
  const put=async(body:unknown)=>{const r=await fetch(p,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,dto:await r.json()};};
  const body={...content,expected_revision:revision,ui:{...content.ui,listFold:!content.ui.listFold}};
  const valid=await put(body),readback=await (await fetch(p)).json();
  const stale=await put(body),invalid=await put({...body,expected_revision:valid.dto.revision,review_unknown:true});
  return {before,valid,readback,stale,invalid,after:await (await fetch(p)).json()};
 });
 expect(writes.valid.status).toBe(200);expect(writes.valid.dto.revision).toBe(writes.before.revision+1);expect(writes.valid.dto.ui.listFold).toBe(!writes.before.ui.listFold);expect(writes.readback).toEqual(writes.valid.dto);expect(writes.stale.status).toBe(409);expect(writes.invalid.status).toBe(422);expect(writes.after).toEqual(writes.readback);
 const denied=[];
 for(const session of ['expired','guest']){
  state.signed=session!=='guest';state.expired=session==='expired';
  const reads=await readAll();expect(reads.map(r=>r.status)).toEqual(paths.map(()=>401));
  const put=await page.evaluate(async dto=>{const {revision,...content}=dto;const r=await fetch('/operations/backups/client-preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...content,expected_revision:revision})});return {status:r.status,dto:await r.json()};},writes.after);
  expect(put).toEqual({status:401,dto:{detail:'fixture unauthenticated'}});denied.push({session,reads,put});
 }
 state.signed=true;state.expired=false;expect(await page.evaluate(async()=>await (await fetch('/operations/backups/client-preferences')).json())).toEqual(writes.after);
 await info.attach('preference-exact-boundary.json',{body:JSON.stringify({ownerReads,writes,denied,unexpected:state.unexpected}),contentType:'application/json'});expect(state.unexpected).toEqual([]);
});
async function modal(page:Page){const dialog=page.getByRole('dialog',{name:'Stella 登录'});await expect(dialog).toBeVisible();await expect(page.getByText('欢迎回港',{exact:true})).toBeVisible();await dialog.evaluate(el=>Promise.all(el.getAnimations().map(a=>a.finished)));return dialog;}
async function login(page:Page){const dialog=await modal(page);await dialog.locator('input[autocomplete="username"]').fill('fixture');await dialog.locator('input[type="password"]').fill('FIXTURE_ONLY_NOT_A_SECRET');await dialog.getByRole('button',{name:'回港',exact:true}).click();await expect(dialog).toBeHidden();}
async function screenshot(page:Page,name:string){await page.screenshot({path:path.join(evidence,name+'.png')});}

for(const width of [360,393,430,1440])test(`polish cold first-open, animation and reopen at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:width===1440?900:852});const state=await fixture(page);
 const scripts:string[]=[];page.on('request',r=>{if(r.resourceType()==='script')scripts.push(r.url());});
 await page.goto('/');if(width<769)await page.locator('.hamburger').click();await page.locator('.account').waitFor({state:'visible'});
 const before=scripts.length;
 const first=await page.locator('.account').evaluate(el=>new Promise<any>(resolve=>{
  const frames:any[]=[];const start=performance.now();(el as HTMLElement).click();
  function sample(){
   const root=document.querySelector('.auth'),card=root?.querySelector('.card');
   if(!root||!card)throw new Error('Login missing on first animation frame');
   const mask=getComputedStyle(root),panel=getComputedStyle(card);
   frames.push({ms:performance.now()-start,text:card.textContent,inputs:card.querySelectorAll('input').length,opacity:+mask.opacity,cardOpacity:+panel.opacity,transform:panel.transform,maskDuration:mask.transitionDuration,cardDuration:panel.transitionDuration,active:root.classList.contains('login-modal-enter-active')});
   if((!frames.at(-1).active&&+mask.opacity===1&&+panel.opacity===1&&panel.transform==='none')||performance.now()-start>1000)resolve({...frames[0],frames});else requestAnimationFrame(sample);
  }
  requestAnimationFrame(sample);
 }));
 expect(first.text).toContain('欢迎回港');expect(first.inputs).toBe(3);expect(first.text).not.toContain('看港口');
 const timing={mask:first.maskDuration,card:first.cardDuration};
 expect(timing.mask).toBe('0.26s');expect(timing.card).toBe('0.26s, 0.26s');
 expect(first.opacity).toBe(0);expect(first.cardOpacity).toBe(0);expect(first.transform).not.toBe('none');
 expect(first.frames.some((f:any)=>f.opacity>0&&f.opacity<1)).toBe(true);
 for(const frame of first.frames){expect(Math.abs(frame.opacity-frame.cardOpacity)).toBeLessThan(0.01);expect(frame.text).toContain('欢迎回港');expect(frame.inputs).toBe(3);}
 expect(first.frames.at(-1).active).toBe(false);expect(first.frames.at(-1).opacity).toBe(1);expect(first.frames.at(-1).cardOpacity).toBe(1);expect(first.frames.at(-1).transform).toBe('none');
 const dialog=page.getByRole('dialog',{name:'Stella 登录'});await expect(dialog).toBeVisible();
 await screenshot(page,`polish-${width}-steady`);
 const rect=await dialog.boundingBox();expect(rect!.x).toBeGreaterThanOrEqual(0);expect(rect!.x+rect!.width).toBeLessThanOrEqual(width);expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
 await page.keyboard.press('Escape');const exit=await page.locator('.auth').evaluate(el=>({duration:getComputedStyle(el).transitionDuration,opacity:getComputedStyle(el).opacity}));expect(exit.duration).toBe('0.18s');
 await expect(dialog).toHaveCount(0);await expect(page.locator(width<769?'.hamburger':'.account')).toBeFocused();
 if(width<769)await page.locator('.hamburger').click();await page.locator('.account').click();await modal(page);
 expect(scripts.slice(before).filter(url=>url.includes('LoginPage'))).toEqual([]);
 mkdirSync(evidence,{recursive:true});writeFileSync(path.join(evidence,`polish-${width}-timings.json`),JSON.stringify({first,timing,exit,scriptsAfterClick:scripts.slice(before)},null,2));expect(state.errors).toEqual([]);
});

test('polish slow status cannot replace typed fields; explicit initialization remains available',async({page})=>{
 const state=await fixture(page);await page.route('**/auth/status',async route=>{await new Promise(r=>setTimeout(r,1200));await route.fulfill({json:{initialized:false,email_enabled:true}});});
 await page.goto('/');await page.locator('.account').click();const input=page.locator('.auth input[autocomplete="username"]');await expect(input).toBeVisible();await input.fill('typed-before-status');const handle=await input.elementHandle();
 await expect(page.locator('.auth .init-link')).toBeVisible();expect(await input.evaluate((el,original)=>el===original,handle)).toBe(true);await expect(input).toHaveValue('typed-before-status');
 await page.locator('.auth .init-link').click();await expect(page.getByText('创建唯一账号',{exact:true})).toBeVisible();await expect(input).toHaveValue('typed-before-status');expect(state.errors).toEqual([]);
});

for(const status of [503,200])test(`polish unknown status (${status}) keeps login usable and never assumes initialization needed`,async({page})=>{
 const state=await fixture(page);await page.route('**/auth/status',route=>route.fulfill({status,json:{detail:'fixture unavailable or missing fields'}}));
 await page.goto('/notes');await modal(page);await expect(page.getByRole('button',{name:'开始初始化'})).toHaveCount(0);await login(page);await expect(page.getByText('Fixture private note',{exact:true}).first()).toBeVisible();expect(state.errors).toEqual([]);
});

test('polish fast close/open during pending status has one focused modal',async({page})=>{
 const state=await fixture(page);await page.route('**/auth/status',async route=>{await new Promise(r=>setTimeout(r,1200));await route.fulfill({json:{initialized:true,email_enabled:true}});});
 await page.goto('/');await page.locator('.account').click();await expect(page.locator('.auth input[autocomplete="username"]')).toBeVisible();await page.keyboard.press('Escape');await expect(page.locator('.shell')).not.toHaveAttribute('inert');await page.locator('.account').dispatchEvent('click');
 await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(1);await page.waitForTimeout(220);await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(1);await expect(page.locator('.auth input[autocomplete="username"]')).toBeFocused();
 await page.getByRole('button',{name:'忘记密码？'}).click();await expect(page.getByText('忘记密码',{exact:true})).toBeVisible();await page.waitForTimeout(200);await expect(page.getByText('忘记密码',{exact:true})).toBeVisible();expect(state.errors).toEqual([]);
});

test('polish reduced-motion removes visual movement',async({page})=>{
 await page.emulateMedia({reducedMotion:'reduce'});await fixture(page);await page.goto('/');await page.locator('.account').click();await modal(page);
 expect(await page.locator('.auth').evaluate(el=>getComputedStyle(el).transitionDuration)).toBe('0s');expect(await page.locator('.card').evaluate(el=>getComputedStyle(el).transform)).toBe('none');await screenshot(page,'polish-reduced-motion');
});

test('polish records synchronized real enter/leave frames',async({page})=>{
 await fixture(page);await page.goto('/');await page.locator('.account').click();await modal(page);await page.keyboard.press('Escape');await expect(page.locator('.auth')).toHaveCount(0);
 const samples=await page.locator('.account').evaluate(el=>new Promise(resolve=>{
  (el as HTMLElement).click();
  // Sample the real CSS timelines deterministically. A busy headless host may
  // paint only the endpoints of a 260ms transition; that is not a CSS failure.
  function sample(){
   const root=document.querySelector('.auth'),card=root?.querySelector('.card');
   if(!root||!card){requestAnimationFrame(sample);return;}
   getComputedStyle(root).opacity;getComputedStyle(card).opacity;
   const animations=root.getAnimations({subtree:true}).filter(a=>{const target=(a.effect as KeyframeEffect)?.target;return target===root||target===card;});
   if(animations.length<3){requestAnimationFrame(sample);return;}
   animations.forEach(a=>a.pause());
   const values=[0,90,180,260].map(ms=>{
    animations.forEach(a=>{a.currentTime=ms;});
    return {sampling:'controlled CSS timeline',ms,mask:+getComputedStyle(root).opacity,card:+getComputedStyle(card).opacity,transform:getComputedStyle(card).transform,text:card.textContent};
   });
   animations.forEach(a=>a.play());resolve(values);
  }requestAnimationFrame(sample);
 }));
 console.log('CONTROLLED_ANIMATION',JSON.stringify(samples));
 expect((samples as any[]).every(v=>v.text.includes('欢迎回港')&&!v.text.includes('看港口'))).toBe(true);expect((samples as any[]).some(v=>v.mask>0&&v.mask<1&&v.card>0&&v.card<1)).toBe(true);
 for(const value of samples as any[])expect(Math.abs(value.mask-value.card)).toBeLessThan(0.01);
 expect((samples as any[])[0].mask).toBe(0);expect((samples as any[]).at(-1).mask).toBe(1);
 await page.keyboard.press('Escape');await expect(page.locator('.auth')).toHaveCount(0);await page.locator('.account').evaluate(el=>(el as HTMLElement).click());await page.waitForTimeout(40);
 await page.evaluate(()=>document.querySelector('.auth')!.getAnimations({subtree:true}).forEach(a=>{a.pause();a.currentTime=90;}));await screenshot(page,'polish-enter-090ms');await page.evaluate(()=>document.querySelector('.auth')!.getAnimations({subtree:true}).forEach(a=>a.finish()));await page.waitForTimeout(280);
 await page.keyboard.press('Escape');await page.evaluate(()=>document.querySelector('.auth')!.getAnimations({subtree:true}).forEach(a=>{a.pause();a.currentTime=90;}));await screenshot(page,'polish-leave-090ms');
 writeFileSync(path.join(evidence,'polish-animation-frames.json'),JSON.stringify(samples,null,2));
});

test('preference error stays visible in reserved layout with retry and mobile navigation reachable',async({page})=>{
 await page.setViewportSize({width:320,height:740});const state=await fixture(page,{signed:true});let reads=0;
 await page.route('**/operations/backups/client-preferences',async route=>{
  if(route.request().method()==='GET' && ++reads===1)return route.fulfill({status:503,json:{detail:'fixture preference failure'}});
  return route.fallback();
 });
 await page.goto('/notes');await expect(page.locator('.preview h1')).toContainText('Fixture private body');
 const status=page.locator('.preference-status.compact');await expect(status).toHaveAttribute('role','alert');await expect(status).toContainText('本机输入已保留');
 const content=(await page.locator('main.content').boundingBox())!,notice=(await status.boundingBox())!;
 expect(content.y+content.height).toBeLessThanOrEqual(notice.y+1);expect(notice.y+notice.height).toBeLessThanOrEqual(740);
 await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.getByRole('button',{name:'收起导航',exact:true}).click();
 await screenshot(page,'preference-error-reserved-mobile');
 await page.getByRole('button',{name:'重试偏好同步',exact:true}).click();await expect.poll(()=>reads).toBe(2);await expect(page.locator('.preference-status.compact[role="alert"]')).toHaveCount(0);
 await screenshot(page,'preference-retry-reserved-mobile');expect(state.unexpected).toEqual([]);expect(state.errors).toEqual([]);
});

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
 await page.setViewportSize({width:393,height:852});await fixture(page);
 await page.goto('/');await page.locator('.hamburger').click();await expect(page.locator('.bell-btn')).toHaveCount(0);await page.locator('.account').click();const dialog=await modal(page);await screenshot(page,'mobile-public-modal');await page.keyboard.press('Escape');await expect(dialog).toBeHidden();await expect(page.locator('.hamburger')).toBeFocused();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test.describe('notes edge navigation touch',()=>{
 test.use({hasTouch:true});
 test('single handle ignores old preference across reload and routes; expiry returns focus to visible handle',async({page})=>{
  await page.setViewportSize({width:393,height:852});const state=await fixture(page,{signed:true,storage:{stella_list_fold:'1'}});
  await page.addInitScript(()=>{localStorage.setItem('stella_list_fold','1');localStorage.setItem('stella_notes_nav_hidden','1');});
  await page.clock.install();
  await page.goto('/notes');await expect(page.locator('.title-readonly')).toBeVisible();await page.reload();
  const handle=page.getByRole('button',{name:'打开导航',exact:true});await expect(handle).toBeVisible();
  await page.goto('/');await handle.tap();
  await page.locator('.nav-item').filter({hasText:'笔记'}).tap();await expect(page.locator('.mobile-mask')).toHaveCount(0);
  await expect(handle).toBeVisible();await handle.tap();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);
  await page.locator('.nav-item').filter({hasText:'笔记'}).tap();await expect(page.locator('.mobile-mask')).toHaveCount(0);
  await expect(handle).toBeFocused();
  state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);await login(page);await expect(handle).toBeFocused();
  expect(state.unexpected).toEqual([]);expect(state.errors).toEqual([]);await screenshot(page,'notes-touch-handle-restored');
 });
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
 await dialog.locator('input[autocomplete="username"]').fill('fixture');await dialog.locator('input[type="password"]').fill('FIXTURE_ONLY_NOT_A_SECRET');await dialog.getByRole('button',{name:'点亮港口'}).click();await expect(dialog).toBeHidden();await expect(page).toHaveURL('http://127.0.0.1:15274/settings?section=first-use');await expect(page.getByRole('heading',{name:'首次使用清单',exact:true})).toBeVisible();expect(state.errors).toEqual([]);
});
test('expired protected close returns public with no retained private content visible',async({page})=>{
 const state=await fixture(page,{signed:true});await page.clock.install();await page.goto('/notes');await expect(page.getByText('Fixture private note',{exact:true}).first()).toBeVisible();state.expired=true;await page.clock.fastForward(31000);await page.clock.runFor(650);await modal(page);await page.getByRole('button',{name:'关闭登录'}).click();await expect(page).toHaveURL('http://127.0.0.1:15274/');await expect(page.getByRole('dialog')).toBeHidden();await expect(page.getByText('Fixture private note',{exact:true})).toHaveCount(0);expect(state.errors).toEqual([]);
});
test('existing management-password dialog stays distinct; rejected management password never opens login',async({page})=>{
 const m=await settingsFixture(page,true,'http://127.0.0.1:15274');await page.route('**/static/**',route=>route.continue());await page.routeWebSocket('**/*',ws=>ws.onMessage(()=>{}));
 // Supply the current closed read DTO so save reaches the original legacy-403
 // PUT handler. A malformed GET must not turn the one-write oracle into zero.
 await page.route('http://127.0.0.1:15274/navigation',route=>route.request().method()==='GET'
  ? route.fulfill({json:{entries:[],modules:[],legacy_routes:{},revision:1,mutation_id:null}})
  : route.fallback());
 let unlockAttempts=0;await page.route('**/auth/admin/unlock',route=>{unlockAttempts++;return route.fulfill({status:401,json:{detail:'Fixture wrong management password'}});});
 await page.goto('/settings?section=navigation');await page.getByRole('button',{name:'编辑 笔记',exact:true}).click();await page.getByLabel('显示名称',{exact:true}).fill('Fixture notes');await page.locator('.inline-editor').getByRole('button',{name:'保存',exact:true}).click();
 // Management-password elevation is retired: a legacy 403 must remain a failed save, never trigger either authentication dialog or replay.
 await expect(page.getByLabel('导航与网站',{exact:true}).getByRole('status').filter({hasText:'导航未保存，保留修改，请重试'})).toBeVisible();await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('Fixture notes');await expect(page.getByRole('dialog',{name:'解锁管理权限'})).toHaveCount(0);await expect(page.getByRole('dialog',{name:'Stella 登录'})).toHaveCount(0);await screenshot(page,'management-modal-distinct');expect(m.requests.filter(r=>r.path==='/navigation'&&r.method==='PUT')).toHaveLength(1);expect(m.requests.filter(r=>r.path==='/auth/refresh')).toHaveLength(0);expect(unlockAttempts).toBe(0);expect(m.unknown).toEqual([]);
});
test('route cache keeps distinct Home and Notes instances and destroys private state on logout',async({page})=>{
 const state=await fixture(page,{signed:true});const sockets=new Set<unknown>();
 await page.routeWebSocket('**/ws/**',ws=>{ws.onMessage(()=>{});if(new URL(ws.url()).pathname==='/ws/fixture-note'){sockets.add(ws);ws.onClose(()=>sockets.delete(ws));}});
 await page.goto('/');await expect(page.locator('.home-page')).toBeVisible();
 const home=await page.locator('.home-page').elementHandle();
 await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.preview h1')).toBeVisible();
 await page.getByRole('button',{name:'编辑',exact:true}).click();const editor=page.locator('.cm-content');await editor.fill('Private unsaved route cache draft\n'+Array.from({length:100},(_,i)=>`Retained line ${i}`).join('\n'));const original=await editor.elementHandle();
 const scroller=page.locator('.cm-scroller');await scroller.evaluate(el=>el.scrollTop=180);const scroll=await scroller.evaluate(el=>el.scrollTop);expect(scroll).toBeGreaterThan(0);await expect.poll(()=>sockets.size).toBe(1);
 await page.locator('.sidebar a[href="/"]').click();await expect(page.locator('.home-page')).toBeVisible();await expect.poll(()=>sockets.size).toBe(0);
 expect(await page.locator('.home-page').evaluate((el,previous)=>el===previous,home)).toBe(true);
 await page.locator('.sidebar a[href="/notes"]').click();await expect(editor).toContainText('Private unsaved route cache draft');
 expect(await editor.evaluate((el,previous)=>el===previous,original)).toBe(true);expect(await scroller.evaluate(el=>el.scrollTop)).toBe(scroll);await expect.poll(()=>sockets.size).toBe(1);
 await page.locator('.sidebar a.nav-item[href="/settings"]').click();await page.getByRole('button',{name:'退出登录',exact:true}).click();await modal(page);
 expect(await original!.evaluate(el=>el.isConnected)).toBe(false);await expect(page.locator('.cm-content')).toHaveCount(0);
 await login(page);await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.preview h1')).toBeVisible();
 await expect(page.locator('.notes-page')).not.toContainText('Private unsaved route cache draft');expect(state.errors).toEqual([]);
});
test('logout removes private content before returning to public modal',async({page})=>{
 const state=await fixture(page,{signed:true});await page.goto('/settings');await expect(page.getByRole('button',{name:'退出登录',exact:true})).toBeVisible();await page.getByRole('button',{name:'退出登录',exact:true}).click();await modal(page);await expect(page.getByText('Fixture owner',{exact:true})).toHaveCount(0);await expect(page.locator('.settings-page')).toHaveCount(0);expect(state.errors).toEqual([]);
});
