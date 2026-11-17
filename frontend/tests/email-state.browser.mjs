import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createServer,preview} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const fixtureBundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(fixtureBundle.outputFiles[0].text).toString('base64'));
const out=process.env.STELLA_PROFILE_EVIDENCE;
assert.ok(out && path.isAbsolute(out),'Explicit private evidence directory required');fs.mkdirSync(out,{recursive:true});
const built=process.env.STELLA_EMAIL_DIST;
if(built)assert.ok(path.isAbsolute(built));
const server=built?await preview({configFile:false,root:process.cwd(),build:{outDir:built},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}}):await createServer({configFile:false,root:process.cwd(),plugins:[vue()],cacheDir:path.join(out,'vite-browser-cache'),optimizeDeps:{entries:['index.html'],include:['vue','vue-router','pinia']},server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
let browser;const results={checks:[],geometry:[],unknown:[],errors:[],requests:[],screenshots:[]};
try{
 if(!built)await server.listen();const origin=server.resolvedUrls.local[0].replace(/\/$/,'');browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1365,height:900},serviceWorkers:'block'});const page=await context.newPage();
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
 let user={id:'isolated-profile-owner',username:'fixture-login',display_name:'隔离昵称',email:'fixture@example.test',email_verified:false,is_admin:false,home_bg:'',avatar_url:''};
 let smtp=false,holdRead=false,releaseRead,failRead=false;let pendingRead=null;
 await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');window.__toastFrames=[];function sample(){const t=document.querySelector('.toast');if(t){const s=getComputedStyle(t),r=t.getBoundingClientRect();window.__toastFrames.push({t:performance.now(),opacity:+s.opacity,transform:s.transform,x:r.x,y:r.y,cls:t.className});}requestAnimationFrame(sample);}requestAnimationFrame(sample);});
 page.on('pageerror',e=>results.errors.push(e.message));
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&['/','/ws/notifications'].includes(u.pathname))return;results.unknown.push('WS '+ws.url());ws.close();});
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();const json=(body,status=200)=>route.fulfill({json:body,status});
  if(u.origin!==origin){results.unknown.push(m+' '+req.url());return route.abort('blockedbyclient');}
  if(m==='GET'&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||p.startsWith('/assets/')||p.startsWith('/static/')||p==='/favicon.svg'||req.isNavigationRequest()))return route.continue();
  results.requests.push({path:p,method:m});
  const pref=preferences.respond(m,p+u.search,req.postDataJSON());if(pref)return route.fulfill(pref);
  if(u.search){results.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');}
  if(p==='/auth/me'&&m==='PATCH'){const d=req.postDataJSON();user={...user,...d,...(d.email&&d.email!==user.email?{email_verified:false}:{})};return json(user);}
  if(m==='POST'&&(p==='/auth/email/send-code'||p==='/auth/email/resend'))return json({ok:true});
  if(p==='/auth/email/verify'&&m==='POST'){user={...user,email:req.postDataJSON().email,email_verified:true};return json({ok:true});}
  if(p==='/auth/me'&&m==='GET'){if(failRead){failRead=false;return json({detail:'读取确认失败'},503);}if(holdRead){pendingRead=new Promise(r=>releaseRead=r);await pendingRead;}return json(user);}
  if(p==='/avatar.png'&&m==='GET')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/><text x="16" y="44" fill="#18191e" font-size="32">星</text></svg>'});
  if(p==='/nodes/host'&&m==='GET')return json({installed:true});
  if(p==='/auth/status'&&m==='GET')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(p==='/auth/security'&&m==='GET')return json({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/auth/email-service'&&m==='GET')return json({ready:smtp});
  if(p==='/auth/activity'&&m==='POST')return json({ok:true});
  if(p==='/navigation'&&m==='GET')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'},{id:'help',title:'文档中心'}],legacy_routes:{}});
  if(p==='/notifications/unread-count'&&m==='GET')return json({count:0});
  if(m==='GET'&&['/auth/avatars','/auth/sessions','/external-modules','/homebg/','/nodes/','/monitors/'].includes(p))return json([]);
  results.unknown.push(m+' '+p);return route.abort('blockedbyclient');
 });
 const shot=async(name)=>{const target=path.join(out,name+'.png');await page.screenshot({path:target});results.screenshots.push(target);};
 const settled=()=>page.waitForFunction(()=>!document.querySelector('[class*="-enter-active"],[class*="-leave-active"],[class*="-enter-from"],[class*="-leave-to"]')&&document.getAnimations().every(a=>a.playState!=='running'||a.effect?.getComputedTiming().iterations===Infinity));
 const rect=selector=>page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};});
 await page.goto(origin+'/settings?section=profile');await page.locator('#profile-username').waitFor();await settled();
 for(const scenario of [{width:1365,height:900},{width:1920,height:900},{width:2900,height:900,zoom:2},{width:683,height:225},{width:1450,height:800,zoom:1.75},{width:1365,height:400,zoom:2},{width:320,height:700},{width:390,height:700}]){
  await page.setViewportSize({width:scenario.width,height:scenario.height});
  await page.evaluate(z=>document.documentElement.style.zoom=String(z),scenario.zoom||1);
  await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await page.locator('#profile-email-draft').waitFor();await page.locator('.profile-email-field').evaluate(el=>el.scrollIntoView({block:'center'}));await settled();
  const field=await rect('#profile-email-draft'),state=await rect('.email-state-trigger'),actions=await rect('.profile-email-actions'),value=await rect('.profile-email-value');
  assert.ok(Math.abs(field.y+field.height/2-state.y-state.height/2)<2,'State icon must share input center, never a second line');
  if(scenario.width/(scenario.zoom||1)>1000)assert.ok(Math.abs(field.y+field.height/2-actions.y-actions.height/2)<2,'Desktop actions must share input center');
  assert.ok(state.x>=field.right+4);assert.ok(actions.x>=field.right+8||actions.y>=field.bottom+8);assert.ok(actions.bottom<= (await rect('.profile-email-row')).bottom+1);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  results.geometry.push({...scenario,field,state,actions,value});await shot('email-'+scenario.width+'-'+(scenario.zoom||1)+'-edit');if(scenario.width===2900){const target=path.join(out,'email-wide-560px-row.png');await page.locator('.profile-email-field').screenshot({path:target});results.screenshots.push(target);}
  await page.getByRole('button',{name:'取消',exact:true}).click();
 }
 await page.evaluate(()=>document.documentElement.style.zoom='1');await page.setViewportSize({width:1365,height:900});
 const trigger=()=>page.locator('.email-state-trigger');
 const close=()=>page.keyboard.press('Escape');
 await trigger().click();await page.getByRole('link',{name:'前往服务与通知'}).waitFor();assert.equal(await trigger().getAttribute('aria-label'),'邮件服务不可用');assert.equal(await page.getByRole('link',{name:'前往服务与通知'}).getAttribute('href'),'/settings?section=services');await shot('state-unavailable');await close();
 smtp=true;await trigger().click();await page.getByRole('button',{name:'发送验证码',exact:true}).waitFor();assert.equal(await trigger().getAttribute('aria-label'),'邮箱待验证');assert.equal(results.requests.filter(r=>r.method==='POST'&&r.path.includes('email')).length,0);await shot('state-pending');
 await page.getByRole('button',{name:'发送验证码',exact:true}).click();await page.locator('#profile-email-code').waitFor();assert.equal(results.requests.filter(r=>r.path==='/auth/email/send-code').length,1);
 await page.locator('#profile-email-code').fill('123456');failRead=true;await page.getByRole('button',{name:'完成验证',exact:true}).click();await page.getByRole('dialog').getByRole('alert').waitFor();assert.equal(await trigger().getAttribute('aria-label'),'邮箱待验证');assert.equal(results.requests.filter(r=>r.path==='/auth/email/verify').length,1);
 await page.getByRole('button',{name:'完成验证',exact:true}).click();await page.getByRole('button',{name:'邮箱已验证',exact:true}).waitFor();assert.equal(results.requests.filter(r=>r.path==='/auth/email/verify').length,1);await trigger().click();await page.getByText('此邮箱已通过验证，无需再次发送验证码。',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'发送验证码',exact:true}).count(),0);await shot('state-verified');await close();
 await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await page.locator('#profile-email-draft').fill('saved@example.test');assert.equal(await trigger().getAttribute('aria-label'),'新邮箱待保存或验证');
 holdRead=true;await page.getByRole('button',{name:'保存邮箱',exact:true}).click();await page.waitForTimeout(100);assert.equal(await page.locator('#profile-email-draft').count(),1);holdRead=false;releaseRead();await page.getByRole('button',{name:'邮箱待验证',exact:true}).waitFor();assert.equal(user.email_verified,false);
 // Mobile dialog, focus/Escape and short/200%-equivalent viewport boundaries.
 await page.locator('.toast').last().waitFor({state:'detached'});
 for(const viewport of [{width:320,height:700},{width:390,height:700},{width:683,height:225},{width:2900,height:900,zoom:2}]){
  await page.setViewportSize({width:viewport.width,height:viewport.height});await page.evaluate(z=>document.documentElement.style.zoom=String(z),viewport.zoom||1);await trigger().click();await page.getByRole('button',{name:'发送验证码',exact:true}).waitFor();await page.waitForTimeout(50);
  const panel=await rect('.email-state-popover');assert.ok(panel.x>=7&&panel.y>=7&&panel.right<=viewport.width-7&&panel.bottom<=viewport.height-7,'Popover must fit viewport');await shot('popover-'+viewport.width+'-'+viewport.height);await close();assert.equal(await trigger().evaluate(el=>document.activeElement===el),true);
 }
 await page.evaluate(()=>document.documentElement.style.zoom='1');await page.setViewportSize({width:320,height:400});await trigger().click();await page.getByRole('button',{name:'发送验证码',exact:true}).click();await page.locator('#profile-email-code').waitFor();await page.waitForTimeout(50);const codePanel=await rect('.email-state-popover');assert.ok(codePanel.x>=7&&codePanel.y>=7&&codePanel.right<=313&&codePanel.bottom<=393);assert.equal(await page.locator('#profile-email-code').evaluate(el=>document.activeElement===el),true);await shot('popover-mobile-code');await close();
 results.checks.push('Single entry: unavailable/settings, pending/explicit send-code, verified/no-send; fresh SMTP GET; verify readback-only retry; unverified save; keyboard Escape/focus and bounded mobile/short popovers');
 results.passed=true;assert.deepEqual(results.unknown,[]);assert.deepEqual(results.errors,[]);
}catch(e){results.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(results,null,2));await browser?.close();if(built)await new Promise((resolve,reject)=>server.httpServer.close(e=>e?reject(e):resolve()));else await server.close();}
