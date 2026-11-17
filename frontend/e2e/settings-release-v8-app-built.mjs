// Actual production App/router/styles, strict synthetic HTTP only. No backend/DB/Agent.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
import {createHash} from 'node:crypto';
const out=process.env.STELLA_SETTINGS_EVIDENCE,dist=process.env.STELLA_APP_DIST;assert(out&&dist);fs.mkdirSync(out,{recursive:true});assert(!fs.existsSync(path.join(out,'browser-result.json')));
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const source=fs.readFileSync('../agent/stella_agent.py'),hash=createHash('sha256').update(source).digest('hex');
const result={kind:'production-built actual App; synthetic exact HTTP, no backend/DB/SMTP/Agent',unknown:[],errors:[],console:[],checks:[],screenshots:[],requests:[]};let browser;
try{browser=await chromium.launch({headless:true,args:['--no-sandbox']});for(const width of [1365,390,320]){
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(7000);
 const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:false});await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
 page.on('pageerror',e=>result.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')result.console.push(m.text());});
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications'&&!u.search)return;result.unknown.push('WS '+u.href);ws.close();});
 await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();result.requests.push([m,p+u.search]);const json=body=>route.fulfill({json:body});
  if(u.origin!==origin){result.unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
  if(m==='GET'&&!u.search&&(p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
  if(m==='GET'&&p==='/settings'&&/^\?section=(profile|authentication|account|services|access|appearance|navigation|backups|performance)$/.test(u.search))return route.continue();
  if(m==='GET'&&p==='/status'&&u.search==='?view=nodes')return route.continue();
  const pref=prefs.respond(m,p+u.search,req.postDataJSON());if(pref)return route.fulfill(pref);
  if(u.search&&!(m==='GET'&&p==='/auth/sessions'&&['?page=1&page_size=20&exclude_current=true','?current_only=true','?page=21&page_size=1&exclude_current=true'].includes(u.search))){result.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');}
  if(m==='POST'&&p==='/auth/activity')return json({ok:true});
  if(m!=='GET'){result.unknown.push(m+' '+p);return route.abort('blockedbyclient');}
  if(p==='/auth/me')return json({id:'synthetic-owner',username:'yunxi',display_name:'云曦',email:'yunxi@example.test',email_verified:false,is_admin:false,home_bg:'',avatar_url:''});
  if(p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(p==='/auth/avatars')return json([]);if(p==='/auth/email-service')return json({ready:false});
  if(p==='/auth/sessions')return json(u.search==='?current_only=true'?[{id:'session-current',device:'Firefox Linux',browser_name:'Firefox',os_name:'Linux',ip:'192.0.2.42',remember:true,created_at:'2026-10-20T00:00:00Z',last_seen:'2026-10-21T00:00:00Z',expires_at:null,current:true,owner:'synthetic-owner',mine:true,login_origin:'https://stella.example.test'}]:[]);
  if(p==='/auth/provider/config')return json({issuer:'https://stella.example.test',discovery_url:'https://stella.example.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.test/auth/oidc/authorize',token_endpoint:'https://stella.example.test/auth/oidc/token',userinfo_endpoint:'https://stella.example.test/auth/oidc/userinfo',jwks_uri:'https://stella.example.test/auth/oidc/jwks',clients:[],capabilities:{}});
  if(p==='/navigation')return json({entries:[{id:'home',title:'主页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'}],legacy_routes:{}});
  if(p==='/external-modules')return json([]);if(p==='/notifications/unread-count')return json({count:0});
  if(p==='/avatar.png'||p==='/assets/homebg/default-bg-kimono-1920.webp')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#25232a"/></svg>'});
  if(p==='/config/access-entries')return json({settings:{revision:1,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://stella.private.test'},issuer:'https://stella.example.test',deployed:{public:'https://stella.example.test',private:'https://stella.private.test'},websites:[]});
  if(p==='/admin/email/config')return json({host:'smtp.example.test',port:465,username:'noreply@example.test',password:'',from_name:'Stella',enabled:false});
  if(p==='/operations/backups')return json({config:{revision:1,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0},records:[],job:null,storage:{node:'isolated-node',available:true,free_bytes:10737418240,error:null},next_run:null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}});
  if(p==='/homebg/'||p==='/homebg')return json([]);if(p==='/config/site-background')return json({url:null});if(p==='/config/public-host')return json({value:'https://stella.example.test'});if(p==='/component-installs')return json([]);
  if(p==='/nodes/')return json([{id:2,name:'测试节点',platform:'linux',host:'192.0.2.2',status:'online',agent_version:'0.6.18',installed:true,last_seen_at:'2026-10-21T00:00:00Z',interfaces:{},created_at:'2026-10-20T00:00:00Z',net_type:'public'}]);
  if(p==='/nodes/host')return json({installed:false,local_install_supported:false,node_id:null});
  if(p==='/agent/version')return json({version:'0.6.16'});if(p==='/agent/release')return json({source_version:'0.6.18',source_sha256:hash,source_size:source.length,announcement_version:'0.6.16',rollout_policy:'pinned'});if(p==='/agent/script')return route.fulfill({contentType:'text/plain;charset=utf-8',body:source});
  result.unknown.push(m+' '+p);return route.abort('blockedbyclient');
 });
 const shot=async key=>{await page.mouse.move(width-1,0);await page.waitForTimeout(200);const name=`${key}-${width}.png`;await page.screenshot({path:path.join(out,name)});result.screenshots.push(name);};
 await page.goto(origin+'/settings?section=profile');await page.getByRole('heading',{name:'账号与登录',exact:true}).waitFor();await page.getByRole('button',{name:'编辑昵称',exact:true}).click();await page.locator('#profile-name').fill('尚未保存的昵称');
 await page.locator('.profile-security-link a').click();assert.equal(await page.locator('#profile-name').inputValue(),'尚未保存的昵称');assert.equal(await page.getByRole('alertdialog').count(),0);await page.locator('#profile-name').fill('云曦');await page.getByRole('heading',{name:'账号与登录',exact:true}).scrollIntoViewIfNeeded();await shot('account');
 if(width>=769){await page.locator('nav[aria-label="设置分组"] a').filter({hasText:'站点与服务'}).click();}else{await page.locator('.settings-mobile-nav .dd-btn').click();await page.getByRole('option').filter({hasText:'站点与服务'}).click();}
 await page.locator('#email-service [aria-label="SMTP 服务地址"]').waitFor();assert.equal(await page.locator('[aria-label="SMTP 服务地址"]').inputValue(),'smtp.example.test');await shot('services');
 for(const [key,title,marker] of [['appearance','外观与显示','.appearance-settings'],['navigation','导航与网站','.nav-settings'],['backups','备份与恢复','.backup-center'],['performance','性能与存储','.performance-card']]){await page.goto(origin+'/settings?section='+key);await page.getByRole('heading',{name:title,exact:true}).waitFor();await shot(key);}
 await page.goto(origin+'/status?view=nodes');await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.locator('.agent-dialog .version').waitFor();const text=await page.locator('.agent-dialog').textContent();assert(text.includes('下载源码版本')&&text.includes('自动更新公告版本')&&text.includes('已锁定')&&text.includes('0.6.16')&&text.includes('0.6.18'));await shot('agent');await page.locator('.agent-dialog').getByRole('button',{name:'源码',exact:true}).click();await page.getByRole('button',{name:'查看源码',exact:true}).click();await page.locator('pre').waitFor();assert.equal(await page.locator('pre').textContent(),source.toString());assert((await page.locator('.source-check').textContent()).includes('与下载源码信息一致'));await shot('agent-source');
 const geometry=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,dialog:document.querySelector('.agent-dialog').getBoundingClientRect().toJSON()}));assert(geometry.scroll<=width&&geometry.dialog.x>=0&&geometry.dialog.right<=width);result.checks.push({width,geometry,sourceBytes:source.length,sourceHash:hash});await context.close();
 }assert.deepEqual(result.unknown,[]);assert.deepEqual(result.errors,[]);assert.deepEqual(result.console,[]);result.passed=true;console.log(JSON.stringify({passed:true,scenarios:result.checks.length,screenshots:result.screenshots.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(r=>server.httpServer.close(r));}
