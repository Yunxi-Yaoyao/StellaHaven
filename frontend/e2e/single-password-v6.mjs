// Production-built complete App with fail-closed synthetic HTTP boundaries.
// This is UI/auth lifecycle acceptance, not a live server/deployment claim.
import http from 'node:http';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium,expect} from '@playwright/test';
import {createServer} from 'vite';
const output=process.env.STELLA_AUTH_OUTPUT;
if(!output)throw Error('explicit evidence directory required');
await mkdir(output,{recursive:true});
const dist=process.env.STELLA_AUTH_DIST||path.resolve('dist');
const vite=await createServer({configFile:false,root:process.cwd(),cacheDir:path.join(output,'browser-helper'),server:{host:'127.0.0.1'},optimizeDeps:{noDiscovery:true}});
const {createClientPreferencesFixture}=await vite.ssrLoadModule('/tests/fixtures/clientPreferences.ts');await vite.close();
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.woff2':'font/woff2','.png':'image/png','.webp':'image/webp'};
const server=http.createServer(async(req,res)=>{try{const p=new URL(req.url,'http://localhost').pathname;const target=p.startsWith('/static/')?path.join(dist,p):path.join(dist,'index.html');const data=await readFile(target);res.writeHead(200,{'Content-Type':mime[path.extname(target)]||'application/octet-stream'});res.end(data);}catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({headless:true,executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox']});
const results=[];
try{
for(const [width,height] of [[1365,900],[1200,900],[1920,900],[390,844],[320,720],[1365,480]]){
 const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),page=await context.newPage();
 let logged=false,denyWrite=false,probing=false;const unknown=[],errors=[],requests=[],writes=[],boundary=[];
 const reject=tag=>(probing?boundary:unknown).push(tag);
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off'},allowWrite:true});
 const profile={id:'single-owner-fixture',username:'owner',display_name:'隔离账号',is_admin:false,avatar_url:'',home_bg:'',email:'',email_verified:false};
 page.on('pageerror',e=>errors.push(e.message));
 await page.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!==base.replace('http:','ws:')||u.pathname!='/ws/notifications'||u.search)reject('WS '+ws.url());ws.close();});
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();
  if(u.origin!==base){reject(m+' '+u.href);return route.abort();}
  const allowedQueries={'/settings':['?section=services'],'/auth/sessions':['?current_only=true','?page=1&page_size=20&exclude_current=true','?page=21&page_size=1&exclude_current=true'],'/auth/sessions/history':['?page=1&page_size=20']};
  if(u.search&&!(m==='GET'&&allowedQueries[p]?.includes(u.search))){reject(m+' '+p+u.search);return route.fulfill({status:501,json:{detail:'Unsupported isolated query'}});}
  if(m==='GET'&&(p.startsWith('/static/')||['/','/settings'].includes(p)))return route.continue();
  const ok=json=>route.fulfill({json});requests.push(m+' '+p);
  const knownReads=['/auth/me','/auth/status','/auth/sessions','/auth/avatars','/auth/sessions/history','/auth/email-service','/auth/provider/config','/navigation','/config/access-entries','/notifications/unread-count','/external-modules','/notifications','/homebg/','/config/public-host','/config/site-background','/homebg/media','/admin/email/config','/avatar.png','/favicon.svg','/operations/backups/client-preferences'];
  const known=(m==='GET'&&knownReads.includes(p))||(m==='POST'&&['/auth/login','/auth/activity','/auth/refresh'].includes(p))||(m==='PUT'&&['/admin/email/config','/operations/backups/client-preferences'].includes(p));
  if(!known){reject(m+' '+p+u.search);return route.fulfill({status:501,json:{detail:'Unknown isolated method/path'}});}
  if(m==='POST'&&p==='/auth/login'){logged=true;return ok(profile);}
  if(m==='POST'&&p==='/auth/activity')return logged?ok({ok:true}):route.fulfill({status:401,json:{detail:'已过期'}});
  if((m==='GET'&&p==='/auth/me')||(m==='POST'&&p==='/auth/refresh'))return logged?ok(profile):route.fulfill({status:401,json:{detail:'未登录'}});
  if(m==='GET'&&p==='/auth/status')return ok({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(!logged && !['/config/site-background','/homebg/media','/favicon.svg'].includes(p))return route.fulfill({status:401,json:{detail:'未登录'}});
  if(p==='/operations/backups/client-preferences'){
   const answer=preferences.respond(m,p,m==='PUT'?req.postDataJSON():undefined);if(answer)return route.fulfill(answer);
  }
  if(m==='GET'&&p==='/navigation')return ok({entries:[],legacy_routes:{}});
  if(m==='GET'&&p==='/config/access-entries')return ok({settings:{revision:0,enabled:false,public_origin:'https://stella.example.test',private_origin:null},issuer:'https://stella.example.test',deployed:{public:'https://stella.example.test'},websites:[]});
  if(m==='GET'&&p==='/notifications/unread-count')return ok({count:0});
  if(m==='GET'&&['/auth/sessions','/auth/avatars','/external-modules','/notifications','/homebg/'].includes(p))return ok([]);
  if(m==='GET'&&p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(m==='GET'&&p==='/auth/email-service')return ok({ready:false});
  if(m==='GET'&&['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(m==='GET'&&p==='/homebg/media')return ok({source:'',poster:''});
  if(m==='GET'&&p==='/auth/provider/config')return ok({issuer:'https://stella.example.test',discovery_url:'https://stella.example.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.test/oauth/authorize',token_endpoint:'https://stella.example.test/oauth/token',userinfo_endpoint:'https://stella.example.test/oauth/userinfo',jwks_uri:'https://stella.example.test/oauth/jwks',capabilities:{},clients:[]});
  if(m==='GET'&&p==='/admin/email/config')return ok({host:'smtp.example.test',port:465,username:'fixture@example.test',has_password:true,enabled:false,from_name:'Stella'});
  if(m==='PUT'&&p==='/admin/email/config'){writes.push(p);return denyWrite?route.fulfill({status:403,json:{detail:'隔离403拒绝'}}):ok({ok:true});}
  if(m==='GET'&&['/avatar.png','/favicon.svg'].includes(p))return route.fulfill({status:204,body:''});
  reject(m+' '+p+u.search);return route.fulfill({status:500,json:{detail:'Unknown isolated request'}});
 });
 await page.addInitScript(()=>localStorage.setItem('stella_live2d','off'));
 await page.goto(base+'/settings?section=services');
 const dialog=page.getByRole('dialog',{name:'Stella 登录'});
 await expect(dialog).toBeVisible();await expect(page.getByLabel('SMTP 服务地址',{exact:true})).toBeHidden();
 await page.screenshot({path:path.join(output,`anonymous-${width}-${height}.png`)});
 const login=async()=>{await dialog.locator('input[autocomplete=username]').fill('owner');await dialog.locator('input[type=password]').fill('synthetic-ui-fixture-only');await dialog.getByRole('button',{name:'回港',exact:true}).click();await expect(dialog).toBeHidden();};
 await login();const smtp=page.getByLabel('SMTP 服务地址',{exact:true});await expect(smtp).toBeVisible();
 await expect(page.getByRole('button',{name:/解锁管理/})).toHaveCount(0);
 expect(requests.some(x=>x.includes('/auth/admin/')||x.endsWith('/auth/security'))).toBe(false);
 await smtp.fill('typed-smtp-fixture.test');await page.screenshot({path:path.join(output,`logged-in-${width}-${height}.png`)});
 if(width===1365&&height===900){
  // Real store suspension through watchdog HTTP failure, not injected auth state.
  logged=false;await page.waitForTimeout(31000);await expect(dialog).toBeVisible();
  await page.screenshot({path:path.join(output,'same-owner-relogin.png')});await login();
  await expect(smtp).toHaveValue('typed-smtp-fixture.test');
  denyWrite=true;await page.getByRole('button',{name:'应用 SMTP 配置',exact:true}).click();
  await expect(page.getByText('未保存，请重试',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:/解锁管理/})).toHaveCount(0);expect(writes).toEqual(['/admin/email/config']);
  await page.screenshot({path:path.join(output,'403-visible-no-replay.png')});
 }
 if(width===1365&&height===900){
  probing=true;const statuses=await page.evaluate(async()=>{const out=[];for(const [url,method] of [['/auth/me','HEAD'],['/auth/refresh','GET'],['/auth/me?unknown=1','GET'],['/auth/oidc/callback?code=synthetic','GET'],['https://blocked.fixture.invalid/auth/me','GET']]){try{out.push((await fetch(url,{method})).status);}catch{out.push(-1);}}out.push(await new Promise(resolve=>{const ws=new WebSocket(location.origin.replace('http:','ws:')+'/ws/unknown');ws.onclose=()=>resolve(0);}));return out;});probing=false;
  expect(statuses).toEqual([501,501,501,501,-1,0]);expect(boundary).toHaveLength(6);
 }
 expect(unknown).toEqual([]);expect(errors).toEqual([]);
 results.push({width,height,unknown,errors,requests,writes,boundary,secondPasswordRequests:requests.filter(x=>x.includes('/auth/admin/')||x.endsWith('/auth/security'))});
 await writeFile(path.join(output,'browser-result.json'),JSON.stringify({base,results},null,2));await context.close();
}
}finally{await browser.close();await new Promise(r=>server.close(r));}
console.log(JSON.stringify({viewports:results.length,unknown:results.flatMap(r=>r.unknown),errors:results.flatMap(r=>r.errors),output}));
