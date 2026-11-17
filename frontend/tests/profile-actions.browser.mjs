import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const fixtureBundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(fixtureBundle.outputFiles[0].text).toString('base64'));
const out=process.env.STELLA_PROFILE_EVIDENCE;
assert.ok(out && path.isAbsolute(out),'Explicit private evidence directory required');fs.mkdirSync(out,{recursive:true});
const server=await createServer({configFile:false,root:process.cwd(),plugins:[vue()],cacheDir:path.join(out,'vite-browser-cache'),optimizeDeps:{entries:['index.html']},server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
let browser;const results={checks:[],geometry:[],unknown:[],errors:[],requests:[],screenshots:[]};
try{
 await server.listen();const origin=server.resolvedUrls.local[0].replace(/\/$/,'');browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1365,height:900}});const page=await context.newPage();
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
 let user={id:'isolated-profile-owner',username:'fixture-login',display_name:'隔离昵称',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''};
 let smtp=false,holdRead=false,releaseRead;let pendingRead=null;
 await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');window.__toastFrames=[];function sample(){const t=document.querySelector('.toast');if(t){const s=getComputedStyle(t),r=t.getBoundingClientRect();window.__toastFrames.push({t:performance.now(),opacity:+s.opacity,transform:s.transform,x:r.x,y:r.y,cls:t.className});}requestAnimationFrame(sample);}requestAnimationFrame(sample);});
 page.on('pageerror',e=>results.errors.push(e.message));
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&['/','/ws/notifications'].includes(u.pathname))return;results.unknown.push('WS '+ws.url());ws.close();});
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();const json=(body,status=200)=>route.fulfill({json:body,status});
  if(u.origin!==origin){results.unknown.push(m+' '+req.url());return route.abort('blockedbyclient');}
  if(m==='GET'&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||p.startsWith('/assets/')||p==='/favicon.svg'||req.isNavigationRequest()))return route.continue();
  results.requests.push({path:p,method:m});
  const pref=preferences.respond(m,p+u.search,req.postDataJSON());if(pref)return route.fulfill(pref);
  if(p==='/auth/me'&&m==='PATCH'){const d=req.postDataJSON();user={...user,...d,...(d.email&&d.email!==user.email?{email_verified:false}:{})};return json(user);}
  if(p==='/auth/me'&&m==='GET'){if(holdRead){pendingRead=new Promise(r=>releaseRead=r);await pendingRead;}return json(user);}
  if(p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/><text x="16" y="44" fill="#18191e" font-size="32">星</text></svg>'});
  if(p==='/nodes/host')return json({installed:true});
  if(p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(p==='/auth/security')return json({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/auth/email-service')return json({ready:smtp});
  if(p==='/auth/activity'&&m==='POST')return json({ok:true});
  if(p==='/navigation')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'},{id:'help',title:'文档中心'}],legacy_routes:{}});
  if(p==='/notifications/unread-count')return json({count:0});
  if(p==='/config/public-host')return json({value:''});
  if(['/auth/avatars','/auth/sessions','/external-modules','/homebg/','/nodes/','/monitors/'].includes(p))return json([]);
  results.unknown.push(m+' '+p);return route.abort('blockedbyclient');
 });
 const shot=async(name)=>{const target=path.join(out,name+'.png');await page.screenshot({path:target});results.screenshots.push(target);};
 const settled=()=>page.waitForFunction(()=>!document.querySelector('[class*="-enter-active"],[class*="-leave-active"],[class*="-enter-from"],[class*="-leave-to"]')&&document.getAnimations().every(a=>a.playState!=='running'||a.effect?.getComputedTiming().iterations===Infinity));
 const rect=selector=>page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};});
 await page.goto(origin+'/settings?section=profile');await page.locator('#profile-username').waitFor();await settled();
 // The divider test deliberately runs before all other browser assertions.
 const divider=await page.locator('.settings-side').evaluate(el=>{const s=getComputedStyle(el,'::after');return {top:s.top,bottom:s.bottom,content:s.content};});
 assert.equal(divider.top,'24px');assert.equal(divider.bottom,'24px');results.checks.push('settings divider inset 24px without shifting navigation');
 for(const width of [1365,1920,320,390]){
  await page.setViewportSize({width,height:900});await settled();await shot('profile-'+width+'-display');
  const before=await rect('.profile-email-current');const action=await rect('.profile-email-current .profile-email-actions');assert.ok(Math.abs(before.right-action.right)<=1);
  await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await page.locator('#profile-email-draft').waitFor();await settled();
  assert.equal(await page.locator('.profile-email-address').count(),0);assert.equal(await page.getByRole('button',{name:'收起',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'发送验证码',exact:true}).count(),0);
  const field=await rect('#profile-email-draft'),editor=await rect('.profile-email-editor'),actions=await rect('.profile-email-editor .profile-email-actions');
  assert.ok(editor.height>=field.height);assert.ok(actions.bottom<=editor.bottom+1,'Actions must remain within the email editor, never overlap the footer');assert.ok(field.width<=340.1);assert.ok(Math.abs(editor.right-actions.right)<=1);assert.ok(field.right<=actions.x-12||field.bottom<=actions.y-8,'Value/actions must remain separate, not wrap into an undifferentiated row');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));results.geometry.push({width,field,editor,actions});await shot('profile-'+width+'-edit');
  await page.getByRole('button',{name:'取消',exact:true}).click();await settled();
 }
 await page.setViewportSize({width:1365,height:900});await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await page.locator('#profile-email-draft').fill('saved@example.test');
 holdRead=true;await page.getByRole('button',{name:'保存邮箱',exact:true}).click();await page.waitForTimeout(150);assert.equal(await page.locator('.toast').count(),0,'No success until authoritative GET');
 holdRead=false;releaseRead();await page.locator('.toast').waitFor();await shot('toast-entry');await page.waitForTimeout(300);await shot('toast-settled');
 const toast=await rect('.toast');assert.ok(toast.y>=16&&toast.y<60);assert.ok(toast.right<=1365-16);assert.equal(await page.locator('.toast').textContent(),'邮箱已保存，尚未验证');assert.equal(await page.locator('.profile-success').count(),0);
 await page.waitForFunction(()=>document.querySelector('.toast-leave-active'));await shot('toast-exit');await page.locator('.toast').waitFor({state:'detached'});results.toastFrames=await page.evaluate(()=>window.__toastFrames);
 assert.ok(results.toastFrames.some(f=>f.opacity>0&&f.opacity<1&&f.cls.includes('enter')));assert.ok(results.toastFrames.some(f=>f.opacity>0&&f.opacity<1&&f.cls.includes('leave')));results.checks.push('GET-gated top-right success, real slide-in/fade-out intermediate frames');
 await page.locator('#profile-username').fill('edited-login');await page.getByRole('button',{name:'保存用户名',exact:true}).click();await page.getByText('用户名已保存',{exact:true}).waitFor();assert.equal(user.username,'edited-login');assert.equal(user.display_name,'隔离昵称');results.checks.push('username separate editable field and real SettingsPage store readback');
 await page.locator('.toast').waitFor({state:'detached'});
 for(const width of [1920,320,390]){
  await page.setViewportSize({width,height:900});await page.locator('#profile-name').fill('确认昵称'+width);await page.getByRole('button',{name:'保存昵称',exact:true}).click();await page.locator('.toast').waitFor();await shot('toast-'+width+'-entry');
  await page.waitForFunction(()=>!document.querySelector('.toast-enter-active'));const box=await rect('.toast');assert.ok(box.x>=16&&box.right<=width-16&&box.y>=16&&box.y<60);await shot('toast-'+width+'-settled');
  await page.waitForFunction(()=>document.querySelector('.toast-leave-active'));await shot('toast-'+width+'-exit');await page.locator('.toast').waitFor({state:'detached'});
 }
 await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#profile-name').fill('减少动效昵称');await page.getByRole('button',{name:'保存昵称',exact:true}).click();await page.locator('.toast').waitFor();assert.equal(await page.locator('.toast').evaluate(el=>getComputedStyle(el).transitionDuration),'0s');await page.locator('.toast').waitFor({state:'detached'});await page.emulateMedia({reducedMotion:'no-preference'});await page.setViewportSize({width:1365,height:900});
 results.checks.push('top-right toast entry/settled/exit at 1920,320,390 and reduced motion');
 // Long content and short viewport do not fragment the scene-owned line or move sticky links out of view.
 await page.evaluate(()=>{const e=document.createElement('div');e.style.height='2200px';e.dataset.qaLong='';document.querySelector('#settings-content').append(e);});
 await page.locator('main.content').evaluate(el=>el.scrollTop=el.scrollHeight);await settled();
 const sticky=await rect('.settings-side-inner');assert.ok(sticky.y>=0&&sticky.y<100);await shot('settings-long-bottom');
 await page.evaluate(()=>document.querySelector('[data-qa-long]').remove());await page.locator('main.content').evaluate(el=>el.scrollTop=0);await page.setViewportSize({width:1365,height:200});await settled();await shot('settings-short-200');
 const short=await page.locator('.settings-side').evaluate(el=>({height:el.getBoundingClientRect().height,top:getComputedStyle(el,'::after').top,bottom:getComputedStyle(el,'::after').bottom}));assert.ok(short.height>48);assert.equal(short.top,'24px');assert.equal(short.bottom,'24px');
 await page.setViewportSize({width:1365,height:900});await page.goto(origin+'/help?section=guide&page=settings');await page.locator('.doc-directory').waitFor();await settled();await shot('documentation-divider');
 const docLine=await page.locator('.documentation').evaluate(el=>({top:getComputedStyle(el,'::after').top,bottom:getComputedStyle(el,'::after').bottom}));assert.equal(docLine.top,'24px');assert.equal(docLine.bottom,'24px');
 await page.goto(origin+'/status');await page.locator('.servers-bar').waitFor();await settled();await shot('servers-divider');
 const serverLine=await page.locator('.servers-bar').evaluate(el=>({top:getComputedStyle(el,'::after').top,bottom:getComputedStyle(el,'::after').bottom}));assert.equal(serverLine.top,'24px');assert.equal(serverLine.bottom,'24px');
 results.checks.push('settings long sticky / 200px short; documentation and server 24px divider inset');
 assert.deepEqual(results.unknown,[]);assert.deepEqual(results.errors,[]);results.passed=true;
 await context.close();
}catch(e){results.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(results,null,2));await browser?.close();await server.close();}
