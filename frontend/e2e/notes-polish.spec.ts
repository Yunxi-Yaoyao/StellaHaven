import { test, expect } from '@playwright/test';
import {createHash} from 'node:crypto';
import {scopeFixture} from './notes-delete-scope-fixture';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
import {createNotesStartupFixture} from '../tests/fixtures/notesStartup.mjs';
const ROOT='http://127.0.0.1:15185';
const ws='11111111-1111-4111-8111-111111111111', id='22222222-2222-4222-8222-222222222222';
const out=process.env.NOTES_ARTIFACTS!;
async function fixture(page:any,title='随手记',options:{empty?:boolean;content?:string;ancestor?:boolean}={}) {
 const notesStartup=createNotesStartupFixture(ws);
 const clientPreferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_list_fold:'1',stella_note_edit_mode:'markdown'},allowWrite:true});
 const doc:any={id,title,workspace_id:ws,parent_id:null,content:'# 清爽阅读\n\n第一段正文，保持舒适字号。\n\n## 第二节\n\n'+('这是实际组件渲染的长文。\n\n'.repeat(60)),updated_at:'2026-10-15T00:00:00Z',created_at:'2026-10-14T00:00:00Z',has_draft:false,is_favorite:false,status:'published'};
 if(options.content)doc.content=options.content;
 const parent={...doc,id:'33333333-3333-4333-8333-333333333333',title:'祖先路径',content:''};if(options.ancestor)doc.parent_id=parent.id;
 const clientPreferenceRequests:any[]=[];
 const calls:any[]=[];const errors:string[]=[];const state={failure:0,empty:!!options.empty};
 const trash:any[]=[];const drafts:any[]=[];const deletedReads:string[]=[];const deletedReadConsole:string[]=[];
 const scopes=scopeFixture(()=>state.empty?[]:[doc],()=>trash);
 page.on('pageerror',(e:any)=>errors.push(e.message));page.on('console',(m:any)=>{
  if(m.type()!=='error')return;
  // The deletion contract verifies absence with one GET -> 404. Keep this
  // expected, exact-target browser diagnostic separate; all others still fail.
  if(deletedReads.length&&m.location().url===ROOT+`/documents/${id}`&&m.text()==='Failed to load resource: the server responded with a status of 404 (Not Found)')deletedReadConsole.push(m.text());
  else errors.push(m.text());
 });
 await page.routeWebSocket('**/*',(socket:any)=>{
  const u=new URL(socket.url());
  if(u.origin!==ROOT.replace('http:','ws:')||![`/ws/${id}`,`/ws/list/${ws}`,'/ws/notifications',...(options.ancestor?[`/ws/${parent.id}`]:[])].includes(u.pathname))throw new Error('Unknown fixture socket '+socket.url());
  socket.onMessage((raw:string)=>{
   const message=JSON.parse(raw);
   if(u.pathname!==`/ws/${id}`||message.type!=='draft')return;
   if(typeof message.request_id!=='string'||!message.request_id||typeof message.content!=='string')throw new Error('Malformed draft request');
   if(state.failure){socket.close({code:1011});return;}
   const receipt={type:'draft_ack',request_id:message.request_id,draft_updated_at:new Date().toISOString(),content_hash:createHash('sha256').update(message.content,'utf8').digest('hex'),base_updated_at:doc.updated_at};
   drafts.push({message,receipt});socket.send(JSON.stringify(receipt));
  });
 });
 await page.route('**/*',async(r:any)=>{
  const q=r.request(),u=new URL(q.url()),p=u.pathname;
  if(u.origin===ROOT&&(p==='/notes'||p==='/'||['/settings','/status','/drive','/gallery','/apps/fixture-external'].includes(p)||p.startsWith('/src/')||p.startsWith('/static/')||p.startsWith('/@')||p.startsWith('/node_modules/')||/\.(svg|woff2|png)$/.test(p)))return r.continue();
  if(q.method()==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.href))return r.fulfill({json:{ip:'192.0.2.1',region:'Fixture',country:'ZZ'}});
  // Account preference traffic is infrastructure, not a document save.
  if(u.origin===ROOT){const preference=clientPreferences.respond(q.method(),p+u.search,q.method()==='PUT'?q.postDataJSON():undefined);if(preference){clientPreferenceRequests.push({method:q.method(),body:q.postDataJSON(),...preference});return r.fulfill(preference);}}
  calls.push({p,method:q.method(),body:q.postData()});const ok=(json:any)=>r.fulfill({json});
  if(u.origin!==ROOT)throw new Error('Unexpected external request '+q.url());
  if(p==='/auth/status'&&q.method()==='GET')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'fixture-owner',username:'fixture',is_admin:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/navigation')return ok({revision:1,mutation_id:null,entries:[],modules:['drive','gallery','external'].map(name=>({id:'fixture-'+name,name,icon:'globe',mode:'iframe',adapter:'generic',browser_url:ROOT+'/fixture-frame/'+name,enabled:true})),legacy_routes:{drive:'fixture-drive',gallery:'fixture-gallery'}});
  if(p==='/external-modules')return ok(['drive','gallery','external'].map(name=>({id:'fixture-'+name,name,icon:'globe',mode:'iframe',adapter:'generic',browser_url:ROOT+'/fixture-frame/'+name,enabled:true})));
  if(q.method()==='GET'&&['drive','gallery','external'].some(name=>p==='/external-modules/fixture-'+name)){const name=p.split('/')[2]!.slice('fixture-'.length);return ok({id:'fixture-'+name,name,icon:'globe',mode:'iframe',adapter:'generic',browser_url:ROOT+'/fixture-frame/'+name,enabled:true,background:'solid',injection:{active:null,draft:null,previous:null}});}
  if(p.startsWith('/fixture-frame/'))return r.fulfill({contentType:'text/html',body:'<!doctype html><html><body style="margin:0;background:#14171f;color:white"><h1>Explicit offline website fixture</h1><p>'+p+'</p><div style="height:1800px"></div><button>Frame bottom</button></body></html>'});
  if(/^\/external-modules\/fixture-[a-z]+\/launch$/.test(p))return ok({url:ROOT+'/fixture-frame/'+p.split('/')[2],method:'GET'});
  if(p==='/website-settings/check')return ok({embedding:{status:'allowed'}});
  if(p==='/component-installs')return ok([]);
  if(p==='/nodes/')return ok([]);
  if(p==='/nodes/host')return ok({installed:true});
  if(p==='/nodes/map-topology')return ok({nodes:[],links:[]});
  if(p==='/assets/homebg/default-bg-kimono-1920.webp')return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#243344"/></svg>'});
  if(p==='/homebg/media')return ok({source:'',poster:''});
  if(p==='/workspaces/')return ok([{id:ws,name:'笔记本',user_id:'fixture-owner'}]);
  if(p==='/documents/'&&q.method()==='GET')return ok(state.empty?[]:options.ancestor?[parent,{...doc,content:undefined}]:[{...doc,content:undefined}]);
  if(p==='/documents/'&&q.method()==='POST'){Object.assign(doc,q.postDataJSON());state.empty=false;return ok(doc);}
  if(p==='/documents/trash'&&q.method()==='GET')return ok(trash);
  if(p==='/documents/delete-preview'&&q.method()==='POST')return ok(scopes.preview(q.postDataJSON()));
  if(options.ancestor&&p===`/documents/${parent.id}`)return ok(parent);
  if(options.ancestor&&p===`/documents/${parent.id}/backlinks`)return ok([]);
  if([`/documents/${id}`,`/documents/${id}/permanent`].includes(p)&&q.method()==='DELETE'){
   const permanent=p.endsWith('/permanent');
   if(!scopes.valid(u.searchParams.get('scope_token'),{workspace_id:ws,doc_id:id,mode:permanent?'permanent':'trash',cascade:u.searchParams.get('cascade')==='true'}))return r.fulfill({status:409,json:{detail:{code:'delete_scope_changed'}}});
   if(!permanent)trash.push({...doc});else trash.splice(0);
   state.empty=true;return r.fulfill({status:204});
  }
  if(p===`/documents/${id}`){if(state.empty){deletedReads.push(q.method());return r.fulfill({status:404,json:{detail:'not found'}});}if(q.method()==='PUT'){if(state.failure)return r.fulfill({status:state.failure,json:{detail:'Injected save failure'}});Object.assign(doc,q.postDataJSON(),{updated_at:'2026-10-15T01:00:00Z'});}return ok(doc);}
  const startup=notesStartup.respond(q.method(),p+u.search);if(startup)return r.fulfill(startup);
  if(p==='/document-versions/')return ok([]);
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/config/home')return ok({value:JSON.stringify({live2d:false})});
  if(['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/auth/provider/config'&&q.method()==='GET'&&!u.search)return ok({issuer:'https://stella.test',discovery_url:'https://stella.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.test/auth/authorize',token_endpoint:'https://stella.test/auth/token',userinfo_endpoint:'https://stella.test/auth/userinfo',jwks_uri:'https://stella.test/auth/jwks',clients:[],capabilities:{}});
  if(p==='/auth/email-service')return ok({ready:false});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(['/tags/','/doc-tags/','/attachments/','/document-links/','/documents/recent','/auth/sessions','/auth/avatars','/homebg/',`/documents/${id}/backlinks`].includes(p))return ok([]);
  throw new Error('Unexpected fixture request '+q.method()+' '+p);
 });
 await page.addInitScript(({ws}:any)=>{if(sessionStorage.getItem('notes-fixture'))return;sessionStorage.setItem('notes-fixture','1');localStorage.clear();localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'fixture-owner',workspaceId:ws}));localStorage.setItem('stella_list_fold','1');localStorage.setItem('stella_note_edit_mode','markdown');},{ws});
 await page.goto(options.ancestor?`/notes?doc=${id}`:'/notes');if(!options.empty)await expect(page.locator('.preview h1')).toBeVisible();else await expect(page.locator('.blank')).toContainText('新建');
 return {doc,calls,errors,state,drafts,trash,deletedReads,deletedReadConsole,clientPreferenceRequests};
}
test('global mobile shell removes legacy top spacer outside notes',async({page})=>{
 await page.setViewportSize({width:393,height:852});await fixture(page);
 await page.locator('.notes-handle').click();await page.locator('.nav-item').filter({hasText:'个人主页'}).click();
 await expect(page.locator('.content.flush')).toBeVisible();
 expect(await page.locator('.content').evaluate(el=>getComputedStyle(el).paddingTop)).toBe('0px');
 await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.locator('.nav-item').filter({hasText:'设置'}).click();
 await expect(page).toHaveURL(/settings/);
 expect(await page.locator('.content').evaluate(el=>getComputedStyle(el).paddingTop)).toBe('10px');
});
test('global handle is centered slender and dims softly without swallowing the first tap',async({page})=>{
 await page.setViewportSize({width:393,height:852});await fixture(page);
 const handle=page.locator('.notes-handle'),box=(await handle.boundingBox())!;
 expect(box.width).toBe(16);expect(box.height).toBe(64);expect(box.y+box.height/2).toBe(426);
 await handle.hover();await page.mouse.move(390,20);await page.waitForTimeout(2800);
 expect(await page.locator('.notes-handle-face').evaluate(el=>Number(getComputedStyle(el).opacity))).toBe(1);
 await expect(page.locator('.notes-handle-face')).toHaveCSS('opacity','0.28');
 await page.screenshot({path:out+'/idle-dim.png'});
 await handle.click();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);await expect(page.locator('.notes-navigation')).toBeHidden();
 await page.keyboard.press('Escape');await expect(handle).toBeFocused();await expect(page.locator('.notes-handle-face')).toHaveCSS('opacity','1');
});
test('idle exact deadline, midpoint, hover focus touch resize visibility and reduced motion',async({page})=>{
 await page.clock.install();await page.setViewportSize({width:393,height:852});const m=await fixture(page);
 await page.clock.pauseAt(await page.evaluate(()=>Date.now()+100));
 const handle=page.locator('.notes-handle'),face=page.locator('.notes-handle-face'),nav=page.locator('.notes-navigation');
 const activityBefore=m.calls.filter(c=>c.p==='/auth/activity').length;
 await handle.dispatchEvent('pointerenter',{pointerType:'mouse'});await handle.dispatchEvent('pointerleave',{pointerType:'mouse'});
 await page.clock.runFor(2999);await expect(nav).not.toHaveClass(/handle-idle/);expect(m.calls.filter(c=>c.p==='/auth/activity')).toHaveLength(activityBefore);
 await page.locator('.preview').dispatchEvent('wheel',{deltaY:2});await page.clock.runFor(1);await expect(nav).toHaveClass(/handle-idle/);
 const midpoint=await face.evaluate(el=>{getComputedStyle(el).opacity;const a=el.getAnimations().find(a=>(a as CSSTransition).transitionProperty==='opacity')!;a.pause();a.currentTime=300;return {opacity:Number(getComputedStyle(el).opacity),duration:a.effect!.getTiming().duration};});
 expect(midpoint.duration).toBe(600);expect(midpoint.opacity).toBeGreaterThan(.28);expect(midpoint.opacity).toBeLessThan(1);console.log('IDLE_MIDPOINT',JSON.stringify(midpoint));await page.screenshot({path:out+'/idle-midpoint.png'});
 await handle.dispatchEvent('pointerenter',{pointerType:'mouse'});await page.clock.runFor(4000);await expect(nav).not.toHaveClass(/handle-idle/);
 await handle.dispatchEvent('pointerleave',{pointerType:'mouse'});await handle.focus();await page.clock.runFor(4000);await expect(nav).not.toHaveClass(/handle-idle/);expect(await handle.evaluate(el=>getComputedStyle(el).outlineStyle)).toBe('solid');
 await handle.evaluate(el=>(el as HTMLElement).blur());await page.clock.runFor(3000);await expect(nav).toHaveClass(/handle-idle/);
 await handle.dispatchEvent('pointerdown',{pointerType:'touch'});await expect(nav).not.toHaveClass(/handle-idle/);await handle.dispatchEvent('click');await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);await page.keyboard.press('Escape');await expect(handle).toBeFocused();
 await handle.evaluate(el=>(el as HTMLElement).blur());await page.emulateMedia({reducedMotion:'reduce'});await page.clock.runFor(3000);await expect(face).toHaveCSS('opacity','0.28');await expect(face).toHaveCSS('transition-duration','0s');
 await page.setViewportSize({width:393,height:520});await expect(nav).not.toHaveClass(/handle-idle/);expect((await handle.boundingBox())!.y+32).toBe(260);
 const activityAfterTouch=m.calls.filter(c=>c.p==='/auth/activity').length;
 await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));await expect(nav).not.toHaveClass(/handle-idle/);await page.clock.runFor(4000);expect(m.calls.filter(c=>c.p==='/auth/activity')).toHaveLength(activityAfterTouch);expect(m.errors).toEqual([]);
});
test.describe('touchscreen global handle',()=>{
 test.use({hasTouch:true,isMobile:true});
 for(const close of ['mask','footer'])test(`touch ${close} close retains nonvisible focus and resumes idle fade`,async({page})=>{
  await page.setViewportSize({width:393,height:852});const m=await fixture(page);
  const handle=page.locator('.notes-handle'),face=page.locator('.notes-handle-face');
  await expect(face).toHaveCSS('opacity','0.28');
  await handle.tap();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);
  if(close==='mask')await page.locator('.mobile-mask').tap({position:{x:300,y:50}});else await page.locator('.mobile-close').tap();
  await expect(page.locator('.mobile-mask')).toHaveCount(0);await expect(handle).toBeFocused();
  expect(await handle.evaluate(el=>({visible:el.matches(':focus-visible'),hover:el.matches(':hover')}))).toEqual({visible:false,hover:false});
  const activity=m.calls.filter(c=>c.p==='/auth/activity').length;
  await page.waitForTimeout(3650);await expect(face).toHaveCSS('opacity','0.28',{timeout:500});await expect(handle).toBeFocused();
  await page.screenshot({path:`${out}/touch-${close}-idle.png`});
  await page.waitForTimeout(4000);await expect(face).toHaveCSS('opacity','0.28');await expect(handle).toBeFocused();
  expect(m.calls.filter(c=>c.p==='/auth/activity')).toHaveLength(activity);expect(m.errors).toEqual([]);
  await handle.tap();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);
 });
 for(const [route,label] of [['home','个人主页'],['settings','设置'],['status','服务器']])test(`touch route ${route} resumes idle after focus restoration`,async({page})=>{
  await page.setViewportSize({width:393,height:852});const m=await fixture(page);
  await page.locator('.notes-handle').tap();await page.locator('.nav-item').filter({hasText:label}).tap();
  await expect(page).toHaveURL(new RegExp(route==='home'?'/$':'/'+route+'$'));
  const handle=page.locator('.notes-handle');await expect(handle).toBeFocused();
  expect(await handle.evaluate(el=>el.matches(':focus-visible'))).toBe(false);
  await page.waitForTimeout(3650);await expect(page.locator('.notes-handle-face')).toHaveCSS('opacity','0.28',{timeout:500});
  await expect(handle).toBeFocused();await page.screenshot({path:`${out}/touch-route-${route}-idle.png`});expect(m.errors).toEqual([]);
 });
 test('keyboard Tab Enter Escape keeps restored focus visible through idle deadline',async({page})=>{
  await page.setViewportSize({width:393,height:852});const m=await fixture(page);
  const handle=page.locator('.notes-handle');await page.keyboard.press('Tab');await expect(handle).toBeFocused();
  await page.keyboard.press('Enter');await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);await page.keyboard.press('Escape');
  await expect(handle).toBeFocused();expect(await handle.evaluate(el=>el.matches(':focus-visible'))).toBe(true);
  await page.waitForTimeout(3650);await expect(page.locator('.notes-handle-face')).toHaveCSS('opacity','1');
  expect(await handle.evaluate(el=>getComputedStyle(el).outlineStyle)).toBe('solid');expect(m.errors).toEqual([]);
 });
 test('dimmed handle opens drawer on one real touch tap',async({page})=>{
  await page.setViewportSize({width:393,height:852});await fixture(page);const handle=page.locator('.notes-handle');
  await expect(page.locator('.notes-handle-face')).toHaveCSS('opacity','0.28');const box=(await handle.boundingBox())!;
  await page.touchscreen.tap(box.x+8,box.y+32);await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);await expect(page.locator('.notes-navigation')).toBeHidden();
  await page.screenshot({path:out+'/touch-one-tap-drawer.png'});await page.locator('.mobile-close').tap();await expect(handle).toBeFocused();await expect(page.locator('.notes-handle-face')).toHaveCSS('opacity','1');
 });
});
test('short viewport preserves settings outer and populated server inner scroll reachability',async({page})=>{
 await page.setViewportSize({width:393,height:320});const m=await fixture(page);
 await page.locator('.notes-handle').click();await page.locator('.nav-item').filter({hasText:'设置'}).click();await expect(page.locator('.content > .page')).toBeVisible();
 expect(await page.locator('.content').evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);await page.locator('.content').evaluate(el=>el.scrollTop=el.scrollHeight);expect(await page.locator('.content').evaluate(el=>el.scrollTop+el.clientHeight>=el.scrollHeight-1)).toBe(true);await page.screenshot({path:out+'/settings-short-scrolled.png'});
 await page.route('**/nodes/',r=>r.fulfill({json:Array.from({length:20},(_,i)=>({id:i+1,name:'Offline fixture '+(i+1),status:'offline',platform:'linux',components:{}}))}));
 await page.locator('.notes-handle').click();await page.locator('.nav-item').filter({hasText:'服务器'}).click();await expect(page.locator('.nodes-view .card')).toHaveCount(20);
 const nodes=page.locator('.nodes-view');expect(await nodes.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);await nodes.evaluate(el=>el.scrollTop=el.scrollHeight);expect(await nodes.evaluate(el=>el.scrollTop+el.clientHeight>=el.scrollHeight-1)).toBe(true);await page.locator('.nodes-view .card').last().scrollIntoViewIfNeeded();await expect(page.locator('.nodes-view .card').last()).toBeInViewport();await page.screenshot({path:out+'/servers-short-scrolled.png'});expect(m.errors).toEqual([]);
});
for(const width of [320,393,430,768,769,1440])test(`global actual App routes geometry ${width}`,async({page})=>{
 await page.setViewportSize({width,height:852});const m=await fixture(page);
 const samples:any[]=[];
 for(const [name,label] of [['home','个人主页'],['notes','笔记'],['settings','设置'],['status','服务器'],['drive','drive'],['gallery','gallery'],['external','external']]){
  if(width<=768)await page.locator('.notes-handle').click();
  await page.locator('.nav-item').filter({hasText:label}).click();
  await expect(page).toHaveURL(new RegExp(name==='home'?'/$':name==='notes'?'/notes$':name==='settings'?'/settings$':name==='status'?'/status$':'/apps/fixture-'+name+'$'));
  if(name==='home')await expect(page.locator('.content')).toHaveClass(/flush/);else await expect(page.locator('.content')).not.toHaveClass(/flush/);
  await expect(page.locator('.mobile-mask')).toHaveCount(0);
  await expect(page.locator('.fade-enter-active, .fade-leave-active')).toHaveCount(0);
  if(['drive','gallery','external'].includes(name)){const selector=`iframe[name="stella-external-module-frame-fixture-${name}"]`,frame=page.frameLocator(selector);await expect(page.locator(selector)).toBeVisible();await expect(page.locator('iframe:visible')).toHaveCount(1);await expect(frame.getByRole('heading')).toHaveText('Explicit offline website fixture');await frame.getByRole('button').scrollIntoViewIfNeeded();await expect(frame.getByRole('button')).toBeInViewport();}
  if(name==='settings')await expect(page.locator('.content > .page')).toBeVisible();
  if(name==='notes')await expect(page.locator('.preview h1')).toBeVisible();
  const sample=await page.locator('.content').evaluate(el=>{const s=getComputedStyle(el);return {top:s.paddingTop,left:s.paddingLeft,right:s.paddingRight,overflow:s.overflowY,rect:el.getBoundingClientRect().toJSON(),scroll:el.scrollHeight,client:el.clientHeight};});
  const embedded=['drive','gallery','external'].includes(name),fullBleed=name==='home'||embedded&&width<=768;
  expect(sample.top).toBe(fullBleed?'0px':width<=768?'10px':['settings','status'].includes(name)?'0px':'28px');expect(sample.left).toBe(fullBleed?'0px':width<=768?(name==='settings'?'28px':'12px'):'32px');expect(sample.right).toBe(fullBleed?'0px':width<=768?'12px':'32px');
  expect(sample.overflow).toBe(name==='notes'&&width<=768?'hidden':'auto');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(width<=768){const box=(await page.locator('.notes-handle').boundingBox())!;expect(box).toMatchObject({x:0,width:16,height:64});expect(box.y+32).toBe(426);expect(await page.locator('.hamburger').count()).toBe(1);}else await expect(page.locator('.notes-navigation')).toBeHidden();
  await page.locator('.content').evaluate(el=>{el.scrollTop=el.scrollHeight;});expect(await page.locator('.content').evaluate(el=>el.scrollTop+el.clientHeight>=el.scrollHeight-1)).toBe(true);
  samples.push({name,...sample});await page.screenshot({path:`${out}/global-${width}-${name}.png`});
 }
 console.log('GLOBAL_APP_GEOMETRY',JSON.stringify({width,samples}));expect(m.errors).toEqual([]);
});
test('workspace directory alone has a warm cream background',async({page})=>{
 await page.setViewportSize({width:393,height:852});await fixture(page,'随手记',{ancestor:true});
 expect(await page.locator('.directory-button').evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(239, 211, 171)');
 expect(await page.locator('.breadcrumb').evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
 expect(await page.locator('.crumb').filter({hasText:'祖先路径'}).evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
 await page.screenshot({path:out+'/393-warm-path.png'});
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await expect(page.locator('.doc-list')).toBeVisible();
});
test('mobile notes single handle opens drawer directly without a top spacer',async({page})=>{
 await page.setViewportSize({width:393,height:852});await fixture(page);
 expect(await page.locator('.content').evaluate(el=>getComputedStyle(el).paddingTop)).toBe('10px');
 expect(await page.locator('.notes-navigation button').count()).toBe(1);
 await page.getByRole('button',{name:'打开导航',exact:true}).click();
 await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);
 await expect(page.getByRole('button',{name:'收起导航',exact:true})).toBeVisible();
 await expect(page.locator('.notes-navigation')).toBeHidden();
 await page.getByRole('button',{name:'收起导航',exact:true}).click();
 await expect(page.getByRole('button',{name:'打开导航',exact:true})).toBeFocused();
 await page.screenshot({path:out+'/393-nav-closed.png'});
});
for(const [width,height] of [[320,740],[393,852],[430,932],[852,393],[1440,1000]])test(`navigation geometry and single handle ${width}x${height}`,async({page})=>{
 await page.setViewportSize({width,height});const m=await fixture(page);
 if(width<=768){
  await page.emulateMedia({reducedMotion:'reduce'});
  expect(await page.locator('.sidebar').evaluate(el=>getComputedStyle(el).transitionDuration)).toBe('0s');
  const controls=page.locator('.notes-navigation');expect((await controls.boundingBox())!.width).toBe(16);
  const geometry=()=>page.evaluate(()=>Object.fromEntries(['.notes-page','.panes','.title-readonly','.preview'].map(s=>[s,document.querySelector(s)!.getBoundingClientRect().toJSON()])));
  const shown=await geometry();
  const padding=await page.locator('.content').evaluate(el=>({left:getComputedStyle(el).paddingLeft,right:getComputedStyle(el).paddingRight}));
  expect(padding).toEqual({left:'12px',right:'12px'});
  expect(shown['.notes-page'].left).toBe(12);expect(shown['.notes-page'].right).toBe(width-12);
  const nav=(await controls.boundingBox())!;
  for(const s of ['.breadcrumb','.title-readonly','.toolbar']){const box=(await page.locator(s).boundingBox())!;expect(nav.y).toBeGreaterThanOrEqual(box.y+box.height);}
  expect(nav.y+nav.height/2).toBe(height/2);expect(nav.x).toBe(0);
  const handle=page.getByRole('button',{name:'打开导航',exact:true});const box=(await handle.boundingBox())!;expect(box.width).toBe(16);expect(box.height).toBe(64);
  await page.screenshot({path:`${out}/floating-${width}x${height}-closed.png`});
  await handle.click();expect(await geometry()).toEqual(shown);
  await expect(controls).toBeHidden();await expect(page.locator('.account')).toBeVisible();
  const close=page.getByRole('button',{name:'收起导航',exact:true});const cb=(await close.boundingBox())!;expect(cb.y+cb.height).toBeLessThanOrEqual(height);expect(cb.width).toBeGreaterThanOrEqual(44);
  await page.screenshot({path:`${out}/floating-${width}x${height}-open.png`});
  await close.click();expect(await geometry()).toEqual(shown);await expect(handle).toBeFocused();
  console.log('FLOATING_GEOMETRY',JSON.stringify({width,height,padding,shown,nav,handle:box,close:cb}));
  const body=await page.locator('.preview h1').boundingBox();expect(body!.y).toBeLessThanOrEqual(120);
  await page.evaluate(()=>localStorage.setItem('stella_notes_nav_hidden','1'));await page.reload();await expect(handle).toBeVisible();
  const before=await page.locator('.content').boundingBox();await handle.click();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);expect(await page.locator('.content').boundingBox()).toEqual(before);
  await page.locator('.nav-item').filter({hasText:'笔记'}).click();await expect(page.locator('.mobile-mask')).toHaveCount(0);
  await expect(handle).toBeVisible();
 }else {await expect(page.locator('.notes-navigation')).toBeHidden();await expect(page.locator('.sidebar')).toBeVisible();}
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(await page.locator('.content').evaluate(el=>el.scrollHeight-el.clientHeight)).toBeLessThanOrEqual(1);
 expect(m.errors).toEqual([]);await page.screenshot({path:`${out}/nav-${width}x${height}.png`});
});
test('obsolete navigation storage is never accessed and single handle is keyboard operable',async({page})=>{
 await page.addInitScript(()=>{const get=Storage.prototype.getItem,set=Storage.prototype.setItem;Storage.prototype.getItem=function(k){if(k==='stella_notes_nav_hidden')throw new DOMException('fixture denied','SecurityError');return get.call(this,k);};Storage.prototype.setItem=function(k,v){if(k==='stella_notes_nav_hidden')throw new DOMException('fixture denied','QuotaExceededError');set.call(this,k,v);};});
 await page.setViewportSize({width:393,height:852});const m=await fixture(page);const handle=page.getByRole('button',{name:'打开导航',exact:true});await handle.focus();await page.keyboard.press('Enter');await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);for(let i=0;i<22;i++){await page.keyboard.press('Tab');expect(await page.locator('.sidebar').evaluate(el=>el.contains(document.activeElement))).toBe(true);}await page.keyboard.press('Escape');await expect(handle).toBeFocused();expect(m.errors).toEqual([]);
});
test('drawer and handle share actual CSS timeline, reverse together and end noninteractive',async({page})=>{
 await page.setViewportSize({width:393,height:852});await fixture(page);
 await page.screenshot({path:out+'/motion-closed.png'});
 const sample=async(open:boolean)=>page.evaluate(async(open)=>{
  (document.querySelector(open?'.notes-handle':'.mobile-close') as HTMLButtonElement).click();
  await new Promise<void>(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r())));
  const side=document.querySelector('.sidebar')!,handle=document.querySelector('.notes-navigation')!;
  const a=side.getAnimations().find(a=>(a as CSSTransition).transitionProperty==='transform')!,b=handle.getAnimations().find(a=>(a as CSSTransition).transitionProperty==='opacity')!;
  const info={startDelta:Math.abs(Number(a.startTime)-Number(b.startTime)),duration:a.effect!.getTiming().duration,easingA:a.effect!.getTiming().easing,easingB:b.effect!.getTiming().easing};
  for(const anim of [a,b]){anim.pause();anim.currentTime=100;}
  const x=new DOMMatrix(getComputedStyle(side).transform).m41,opacity=Number(getComputedStyle(handle).opacity),width=side.getBoundingClientRect().width;
  return {...info,x,opacity,width,visibility:getComputedStyle(handle).visibility};
 },open);
 const opening=await sample(true);expect(opening.startDelta).toBeLessThan(1);expect(opening.duration).toBe(200);expect(opening.easingA).toBe(opening.easingB);expect(opening.x).toBeLessThan(0);expect(opening.x).toBeGreaterThan(-opening.width*1.05);expect(opening.opacity).toBeGreaterThan(0);expect(opening.opacity).toBeLessThan(1);expect(Math.abs(opening.opacity+opening.x/(opening.width*1.05))).toBeLessThan(.02);
 await page.screenshot({path:out+'/motion-mid-open.png'});
 await page.evaluate(()=>{for(const selector of ['.sidebar','.notes-navigation'])for(const a of document.querySelector(selector)!.getAnimations())a.finish();});
 await expect(page.locator('.notes-navigation')).toBeHidden();await expect(page.locator('.notes-navigation')).toHaveAttribute('inert','');await expect(page.locator('.notes-handle')).toHaveAttribute('tabindex','-1');
 await expect(page.locator('main.content')).toHaveAttribute('inert','');
 expect(await page.locator('.notes-navigation').evaluate(el=>getComputedStyle(el).pointerEvents)).toBe('none');await page.locator('.notes-handle').evaluate(el=>(el as HTMLElement).focus());expect(await page.locator('.notes-handle').evaluate(el=>el===document.activeElement)).toBe(false);
 await page.screenshot({path:out+'/motion-open.png'});
 const closing=await sample(false);expect(closing.startDelta).toBeLessThan(1);expect(closing.opacity).toBeGreaterThan(0);expect(closing.opacity).toBeLessThan(1);expect(Math.abs(closing.opacity+closing.x/(closing.width*1.05))).toBeLessThan(.02);await page.screenshot({path:out+'/motion-mid-close.png'});
 await page.evaluate(()=>{for(const selector of ['.sidebar','.notes-navigation'])for(const a of document.querySelector(selector)!.getAnimations())a.finish();});
 await expect(page.locator('.sidebar')).toHaveAttribute('inert','');await expect(page.locator('.notes-handle')).toBeFocused();
 // Real rapid open → close → reopen; CSS reverses from its current value, not an endpoint.
 const reverse=await page.evaluate(async()=>{
  const side=document.querySelector('.sidebar')!,handle=document.querySelector('.notes-navigation')!;
  const read=()=>({x:new DOMMatrix(getComputedStyle(side).transform).m41,o:Number(getComputedStyle(handle).opacity)});
  (document.querySelector('.notes-handle') as HTMLElement).click();await new Promise(r=>setTimeout(r,65));const before=read();
  (document.querySelector('.mobile-close') as HTMLElement).click();await new Promise<void>(r=>requestAnimationFrame(()=>r()));const turn=read();await new Promise(r=>setTimeout(r,35));const back=read();
  (document.querySelector('.notes-handle') as HTMLElement).click();await new Promise(r=>setTimeout(r,240));return {before,turn,back,end:read()};
 });expect(Math.abs(reverse.turn.x-reverse.before.x)).toBeLessThan(80);expect(reverse.back.x).toBeLessThan(reverse.turn.x);expect(reverse.back.o).toBeGreaterThan(reverse.turn.o);expect(reverse.end.x).toBe(0);expect(reverse.end.o).toBe(0);
 await page.mouse.click(380,400);await expect(page.locator('.mobile-mask')).toHaveCount(0);await expect(page.locator('.notes-handle')).toBeFocused();
 console.log('DRAWER_TIMELINE',JSON.stringify({opening,closing,reverse}));
});
test('desktop collapsed footer keeps bell and fold only; resize restores complete mobile account',async({page})=>{
 await page.setViewportSize({width:1440,height:1000});await fixture(page);
 await page.getByTitle('收起侧栏',{exact:true}).click();await expect(page.locator('.account')).toBeHidden();await expect(page.locator('.profile .avatar')).toBeVisible();
 const bell=page.locator('.bell-btn');await expect(bell).toBeVisible();
 const fold=page.getByTitle('展开侧栏',{exact:true});
 // Visibility changes immediately, while the sidebar width is still transitioning.
 // Await that actual transition and sample all rectangles in the same frame.
 const {b,f,side}=await page.locator('.sidebar').evaluate(async el=>{
  void getComputedStyle(el).width;
  await Promise.all(el.getAnimations().map(animation=>animation.finished));
  const rect=(target:Element)=>{const r=target.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
  return {b:rect(el.querySelector('.bell-btn')!),f:rect(el.querySelector('[title="展开侧栏"]')!),side:rect(el)};
 });
 expect(b.y+b.height).toBeLessThanOrEqual(f.y);for(const r of [b,f]){expect(r.x).toBeGreaterThanOrEqual(side.x);expect(r.x+r.width).toBeLessThanOrEqual(side.x+side.width);}
 await page.screenshot({path:out+'/desktop-collapsed-footer.png'});
 for(const width of [320,393,430]){await page.setViewportSize({width,height:852});await page.locator('.notes-handle').click();await expect(page.locator('.account')).toBeVisible();await expect(page.locator('.acc-name')).toBeVisible();await expect(bell).toBeVisible();await expect(page.getByRole('button',{name:'收起导航',exact:true})).toBeVisible();await page.getByRole('button',{name:'收起导航',exact:true}).click();}
 await page.setViewportSize({width:1440,height:1000});await fold.click();await expect(page.locator('.account')).toBeVisible();
});
test('directory-open 768 boundary keeps global handle above directory and drawer mask owns pointer stack',async({page})=>{
 await page.setViewportSize({width:1440,height:1000});const m=await fixture(page);
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await expect(page.locator('.doc-list')).toBeVisible();
 await page.getByTitle('收起侧栏',{exact:true}).click();await expect(page.locator('.account')).toBeHidden();
 const directory=()=>page.locator('.doc-list').getAttribute('class');const before=await directory();
 const hit=async(selector:string,x?:number,y?:number)=>page.locator(selector).evaluate((el,point)=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(point.x??r.x+r.width/2,point.y??r.y+r.height/2));},{x,y});
 for(const width of [768,769,768,393,320]){
  await page.setViewportSize({width,height:852});
  if(width===769){await expect(page.locator('.notes-navigation')).toBeHidden();await expect(page.locator('.sidebar')).not.toHaveAttribute('inert');continue;}
  await expect(page.locator('.doc-list')).toBeVisible();expect(await hit('.notes-handle')).toBe(true);
  const geometry=await page.locator('.notes-page').boundingBox();expect(geometry!.x).toBe(12);expect(geometry!.width).toBe(width-24);
  await page.screenshot({path:`${out}/layer-${width}-handle.png`});
  await page.locator('.notes-handle').click();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);await expect(page.locator('main')).toHaveAttribute('inert','');
  await expect(page.locator('.mobile-close')).toBeFocused();await expect.poll(()=>hit('.mobile-close')).toBe(true);
  // x=300 is outside the 232px global drawer but still inside the 320px notes directory.
  expect(await hit('.mobile-mask',300,400)).toBe(true);
  expect(await page.locator('.notes-page').boundingBox()).toEqual(geometry);
  await page.screenshot({path:`${out}/layer-${width}-drawer.png`});
  if(width===768)await page.mouse.click(300,400);else await page.locator('.mobile-close').click();
  await expect(page.locator('.mobile-mask')).toHaveCount(0);await expect(page.locator('.notes-handle')).toBeFocused();
  await expect(page.locator('main')).not.toHaveAttribute('inert');await expect(page.locator('.doc-list')).toBeVisible();expect(await directory()).toBe(before);
 }
 expect(m.errors).toEqual([]);
});
test('mobile notes info modal blocks global handle and restores it after dismissal',async({page})=>{
 await page.setViewportSize({width:768,height:852});const m=await fixture(page);
 await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'文档信息与标签',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'文档信息'});await expect(dialog).toBeFocused();
 expect(await page.locator('.notes-handle').evaluate(el=>{const r=el.getBoundingClientRect();return {inert:!!el.closest('[inert]'),covered:!el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};})).toEqual({inert:true,covered:true});
 await page.locator('.notes-handle').evaluate(el=>(el as HTMLElement).focus());expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
 await page.screenshot({path:out+'/layer-info-modal.png'});await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
 await page.locator('.notes-handle').click();await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);expect(m.errors).toEqual([]);
});
test('regression IME survives the real dirty draft timer rerender',async({page})=>{
 const m=await fixture(page);await page.getByRole('button',{name:'编辑',exact:true}).click();
 // A title alone is not a body draft. Dirty the actual Markdown editor so the
 // real 2500ms timer can fire while the title is in composition.
 await page.locator('.input-wrap .cm-content').press('Control+End');await page.keyboard.type(' dirty body');
 const title=page.getByRole('textbox',{name:'笔记标题',exact:true});await title.fill('已提交');
 await title.evaluate((el:HTMLTextAreaElement)=>{el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));el.value='已提交正在组合';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'正在组合'}));});
 await expect(page.locator('.status-bar')).toContainText('草稿已发送');await expect(title).toHaveValue('已提交正在组合');
 await expect.poll(()=>m.drafts.length).toBe(1);expect(m.drafts[0].message.content).toContain(' dirty body');
 expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(0);
 await title.dispatchEvent('compositionend');await page.getByRole('button',{name:'阅览',exact:true}).click();
 await expect(page.locator('.title-readonly')).toHaveText('已提交正在组合');
 expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(1);
 const saved=JSON.parse(m.calls.find(c=>c.method==='PUT').body);
 expect(saved.consumed_draft).toEqual({draft_updated_at:m.drafts[0].receipt.draft_updated_at,content_hash:m.drafts[0].receipt.content_hash});
 expect(m.drafts).toHaveLength(1);expect(m.errors).toEqual([]);
});
for(const scenario of ['empty','deleted'])test(`regression ${scenario} workspace can create without an editor`,async({page})=>{
 await page.setViewportSize({width:393,height:852});const m=await fixture(page,'随手记',{empty:scenario==='empty'});
 if(scenario==='deleted'){await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'确认移入回收站',exact:true}).click();await expect(page.locator('.editor')).toHaveCount(0);expect(m.trash).toHaveLength(1);expect(m.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);}
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await expect(page.locator('.doc-list')).toBeVisible();await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'新建笔记',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();
 await page.getByRole('dialog').getByRole('textbox',{name:'标题',exact:true}).fill('空态新建成功');await page.getByRole('button',{name:'创建',exact:true}).click();
 await expect(page.locator('.title-readonly')).toHaveText('空态新建成功');expect(m.calls.filter(c=>c.p==='/documents/'&&c.method==='POST')).toHaveLength(1);
 await page.screenshot({path:`${out}/${scenario}-create.png`});expect(m.errors).toEqual([]);
 expect(m.deletedReads).toEqual(scenario==='deleted'?['GET']:[]);expect(m.deletedReadConsole).toHaveLength(scenario==='deleted'?1:0);
});
for(const kind of ['title','info'])test(`regression ${kind} dialog owns focus and restores background`,async({page})=>{
 await fixture(page);const trigger=page.getByRole('button',{name:kind==='title'?'展开完整标题':'更多',exact:true});await trigger.click();
 if(kind==='info')await page.getByRole('button',{name:'文档信息与标签',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:kind==='title'?'完整标题':'文档信息'});
 await expect(dialog).toBeFocused();await page.keyboard.press('Shift+Tab');expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
 await page.keyboard.press('Tab');expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
 expect(await page.locator('.preview').evaluate(el=>!!el.closest('[inert]'))).toBe(true);
 expect(await page.evaluate(()=>getComputedStyle(document.body).overflow)).toBe('hidden');
 await page.screenshot({path:`${out}/${kind}-dialog.png`});await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(trigger).toBeFocused();
 expect(await page.locator('.preview').evaluate(el=>!!el.closest('[inert]'))).toBe(false);
});
test('regression find spans inline formatted text nodes in reading and rich mode',async({page})=>{
 await fixture(page,'格式搜索',{content:'# 清爽阅读\n\n跨**格式**搜索，跨**格式**搜索'});
 for(const mode of ['reading','rich']){
  if(mode==='rich'){await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'所见即所得',exact:true}).click();await expect(page.locator('.ProseMirror')).toBeVisible();}
  await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'文内查找',exact:true}).click();await page.getByRole('textbox',{name:'文内查找',exact:true}).fill('跨格式搜索');
  await page.getByRole('button',{name:'下一处',exact:true}).click();await expect(page.locator('.note-find')).toContainText('1 / 2');expect(await page.evaluate(()=>getSelection()?.toString())).toBe('跨格式搜索');
  await page.getByRole('button',{name:'下一处',exact:true}).click();await expect(page.locator('.note-find')).toContainText('2 / 2');await page.keyboard.press('Escape');
 }
});
test('regression reverting a failed save clears obsolete error without claiming remote sync',async({page})=>{
 const m=await fixture(page);await page.getByRole('button',{name:'编辑',exact:true}).click();const title=page.getByRole('textbox',{name:'笔记标题',exact:true});await title.fill('失败修改');m.state.failure=500;
 await page.getByRole('button',{name:'重试保存',exact:true}).click();await expect(page.locator('.status-bar')).toContainText('保存失败');await title.fill('随手记');
 const count=m.calls.filter(c=>c.method==='PUT').length;await page.getByRole('button',{name:'重试保存',exact:true}).click();await expect(page.locator('.status-bar')).not.toContainText('保存失败');
 await expect(page.locator('.status-bar')).toContainText('未重新确认远端');expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(count);
});
test('regression two line title has no padded third line paint area',async({page})=>{
 await page.setViewportSize({width:320,height:740});await fixture(page,'长标题适配'.repeat(200));
 const box=await page.locator('.title-readonly').evaluate(el=>{const s=getComputedStyle(el);return {padding:parseFloat(s.paddingTop)+parseFloat(s.paddingBottom),height:el.clientHeight,line:parseFloat(s.lineHeight)};});
 expect(box.padding).toBe(0);expect(box.height).toBeLessThanOrEqual(Math.ceil(box.line*2));await page.screenshot({path:out+'/320-clamp.png'});
});
test('short title reading has compact chrome and no timeline requests',async({page})=>{
 await page.setViewportSize({width:393,height:852});const m=await fixture(page);
 const firstBody=await page.locator('.preview h1').evaluate(e=>e.getBoundingClientRect().top);expect(firstBody).toBeLessThanOrEqual(155);console.log('FIRST_BODY_Y',firstBody);
 await expect(page.locator('.tag-bar')).toHaveCount(0);await expect(page.locator('.status-bar')).toHaveCount(0);
 await expect(page.getByText('关联时间线',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'更多',exact:true}).click();await expect(page.getByRole('button',{name:'版本历史',exact:true})).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'版本历史',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'文档信息与标签',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'文档信息'})).toBeVisible();await page.keyboard.press('Escape');
 expect(m.calls.filter(c=>c.p.includes('timeline')||c.p.endsWith('/node'))).toEqual([]);expect(m.errors).toEqual([]);
 await page.screenshot({path:out+'/393-reading.png'});
});
for(const [width,height] of [[320,740],[393,852],[852,393],[1440,1000]])for(const [kind,title] of [['zh','长标题适配'.repeat(200)],['en','W'.repeat(1000)],['emoji','🌸👩🏽‍💻✨'.repeat(150)]])test(`${width}x${height} ${kind} read/edit title preserves value`,async({page})=>{
 await page.setViewportSize({width:Number(width),height:Number(height)});const m=await fixture(page,String(title));
 const overflow=()=>page.evaluate(()=>({doc:document.documentElement.scrollWidth,w:innerWidth,editor:document.querySelector('.editor')!.scrollWidth,client:document.querySelector('.editor')!.clientWidth}));
 let size=await overflow();expect(size.doc).toBeLessThanOrEqual(size.w);expect(size.editor).toBeLessThanOrEqual(size.client);
 await page.locator('.title-readonly').click();await expect(page.getByRole('dialog',{name:'完整标题'})).toContainText(String(title));await page.keyboard.press('Escape');
 await page.screenshot({path:`${out}/${width}x${height}-${kind}-reading.png`});
 await page.getByRole('button',{name:'编辑',exact:true}).click();await expect(page.getByRole('textbox',{name:'笔记标题',exact:true})).toHaveValue(String(title));
 size=await overflow();expect(size.doc).toBeLessThanOrEqual(size.w);expect(size.editor).toBeLessThanOrEqual(size.client);
 await expect(page.getByRole('button',{name:'阅览',exact:true})).toBeVisible();await page.screenshot({path:`${out}/${width}x${height}-${kind}-editing.png`});expect(m.errors).toEqual([]);
});
test('title input normalizes newlines immediately, composition stays intact, save failure remains visible',async({page})=>{
 await page.setViewportSize({width:393,height:852});const m=await fixture(page);await page.getByRole('button',{name:'编辑',exact:true}).click();const title=page.getByRole('textbox',{name:'笔记标题',exact:true});
 await title.fill('第一行\n第二行\r\n第三行');await expect(title).toHaveValue('第一行 第二行 第三行');
 await title.dispatchEvent('compositionstart');await title.fill('中文输入');await title.dispatchEvent('compositionend');await title.press('Enter');await expect(title).toHaveValue('中文输入');
 await expect(page.locator('.status-bar')).toContainText('待保存');m.state.failure=500;await page.getByRole('button',{name:'阅览',exact:true}).click();await expect(page.locator('.status-bar')).toContainText('保存失败');
 m.state.failure=409;await page.getByRole('button',{name:'阅览',exact:true}).click();await expect(page.locator('.status-bar')).toContainText('版本冲突');await expect(title).toHaveValue('中文输入');
 await page.screenshot({path:out+'/save-conflict.png'});m.state.failure=0;await page.getByRole('button',{name:'阅览',exact:true}).click();expect(m.doc.title).toBe('中文输入');
});
test('touch menu routes, drawers, find and export remain reachable without document writes',async({page})=>{
 await page.setViewportSize({width:393,height:852});const m=await fixture(page);
 const menu=async()=>page.getByRole('button',{name:'更多',exact:true}).click();
 await menu();await page.locator('.preview').click({position:{x:8,y:120}});await expect(page.locator('.note-more-menu')).toHaveCount(0);
 await menu();await page.getByRole('button',{name:'大纲',exact:true}).click();await expect(page.locator('.toc-panel')).toBeVisible();await expect(page.locator('.note-more-menu')).toHaveCount(0);await page.locator('.toc-item').last().click();await expect(page.locator('.toc-panel')).toHaveCount(0);
 await menu();await page.getByRole('button',{name:'文内查找',exact:true}).click();await page.getByRole('textbox',{name:'文内查找',exact:true}).fill('第一段正文');await page.getByRole('button',{name:'下一处',exact:true}).click();await expect(page.locator('.note-find')).toContainText('1 / 1');await page.keyboard.press('Escape');
 await menu();await page.getByRole('button',{name:'版本历史',exact:true}).click();await expect(page.getByRole('dialog',{name:'版本历史'})).toBeVisible();await page.keyboard.press('Escape');
 await menu();await page.getByRole('button',{name:'导出',exact:true}).click();await expect(page.locator('.export-window')).toBeVisible();const download=page.waitForEvent('download');await page.getByRole('button',{name:'确定导出',exact:true}).click();expect((await download).suggestedFilename()).toBe('随手记.md');
 await menu();await page.getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 expect(m.calls.filter(c=>c.method==='DELETE'||c.method==='PUT')).toEqual([]);
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await expect(page.locator('.doc-list')).toBeVisible();await page.locator('.list-drawer-shade').click({position:{x:380,y:400}});await expect(page.locator('.doc-list')).toBeHidden();
 await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'所见即所得',exact:true}).click();await expect(page.locator('.rich-editor .ProseMirror')).toContainText('第一段正文');expect(await page.locator('.rich-editor .ProseMirror').evaluate(el=>getComputedStyle(el).fontSize)).toBe('16px');await page.screenshot({path:out+'/393-rich-editing.png'});
 const metrics=await page.evaluate(()=>{const p=document.querySelector('.preview')!,e=document.querySelector('.notes-page')!,c=document.querySelector('.content')!;return {notes:e.getBoundingClientRect().toJSON(),outerScroll:c.scrollHeight-c.clientHeight,font:getComputedStyle(p).fontSize,line:getComputedStyle(p).lineHeight};});expect(metrics.outerScroll).toBeLessThanOrEqual(1);expect(metrics.font).toBe('16px');console.log('NOTES_METRICS',JSON.stringify(metrics));expect(m.errors).toEqual([]);
});
