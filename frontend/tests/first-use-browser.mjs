// Closed product-build fixture: no proxy, database, real accounts or Agents.
import http from 'node:http';
import {readFileSync,existsSync,statSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {outputFiles}=await require('esbuild').build({entryPoints:[path.resolve('tests/fixtures/clientPreferences.ts')],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(outputFiles[0].text).toString('base64'));
import {createNotesStartupFixture} from './fixtures/notesStartup.mjs';
const {chromium}=require('playwright');
const root=path.resolve('../docs/v11-onboarding/build'),out=path.resolve('../docs/v11-onboarding');
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png','.svg':'image/svg+xml'};
const server=http.createServer((req,res)=>{const p=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname);const target=p.startsWith(root+'/')&&existsSync(p)&&statSync(p).isFile()?p:path.join(root,'index.html');res.writeHead(200,{'Content-Type':mime[path.extname(target)]||'application/octet-stream'});res.end(readFileSync(target));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1365,height:900}});const page=await context.newPage();
let signed=false,initialized=false;const unexpected=[],errors=[];
const me={id:'fresh-fixture-owner',username:'fixture',display_name:'Fixture',is_admin:false,avatar_url:'',home_bg:'',email:'',email_verified:false};
const preferences=createClientPreferencesFixture({storage:{stella_home_theme:'daybreak'},allowWrite:true});const notes=createNotesStartupFixture('fixture-workspace');
await page.routeWebSocket('**/*',ws=>ws.onMessage(()=>{}));page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url()),p=url.pathname;const send=(json,status=200)=>route.fulfill({status,json});
 if(url.origin!==origin){unexpected.push(req.method()+' '+req.url());return route.abort();}
 if(req.method()==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')))return route.continue();
 if(p==='/auth/status')return send({initialized,has_users:initialized,email_enabled:false});
 if(p==='/auth/me'||p==='/auth/refresh')return send(signed?me:{detail:'guest'},signed?200:401);
 if(p==='/auth/register'||p==='/auth/login'){signed=true;initialized=true;return send(me);}
 if(p==='/auth/logout'){signed=false;return send({ok:true});}
 const pref=preferences.respond(req.method(),p+url.search,req.method()==='PUT'?req.postDataJSON():undefined);if(pref)return route.fulfill(pref);
 const note=notes.respond(req.method(),p+url.search,signed);if(note)return route.fulfill(note);
 if(p==='/config/access-entries')return send({settings:{revision:0,enabled:false,public_origin:'',private_origin:null},deployed:{public:''},websites:[]});
 if(p==='/auth/email-service')return send({ready:false});
 if(p==='/operations/backups')return send({config:{enabled:false,directory:''},storage:{available:false}});
 if(p==='/config/site-background')return send({value:''});
 if(p==='/homebg/media')return send({url:'',status:'ready',variants:{original:''}});
 if(p==='/navigation')return send({modules:[],entries:[{id:'home',kind:'builtin',label:'主页',icon:'home',order:0,visible:true},{id:'settings',kind:'builtin',label:'设置',icon:'settings',order:1,visible:true}]});
 if(p==='/auth/provider/config')return send({issuer:origin,discovery_url:origin+'/.well-known/openid-configuration',authorization_endpoint:origin+'/oauth/authorize',token_endpoint:origin+'/oauth/token',userinfo_endpoint:origin+'/oauth/userinfo',jwks_uri:origin+'/oauth/jwks',clients:[],capabilities:{}});
 if(p==='/auth/security')return send({enabled:false,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
 if(p==='/notifications/unread-count')return send({count:0});
 if(['/nodes/','/external-modules','/notifications','/auth/avatars','/auth/sessions','/homebg/'].includes(p))return send([]);
 if(p==='/config/public-host')return send({value:''});
 if(p==='/auth/activity')return send({ok:true});
 if(['/favicon.ico','/favicon.svg','/avatar.png','/live2dcubismcore.min.js'].includes(p)||p.startsWith('/assets/'))return route.fulfill({status:204,body:''});
 unexpected.push(req.method()+' '+p+url.search);return send({detail:'unhandled closed fixture'},501);
});
try{
 await page.goto(origin+'/login');await page.getByRole('button',{name:'开始初始化',exact:true}).click();const inputs=page.locator('.auth input');await inputs.nth(0).fill('fixture');await inputs.nth(2).fill('fixture-password-only');await page.getByRole('button',{name:'点亮港口',exact:true}).click();await page.locator('.first-use').waitFor();assert.equal(new URL(page.url()).searchParams.get('section'),'first-use');
 await page.getByText('尚无节点心跳；待报到不算接入',{exact:true}).waitFor();
 for(const width of [1365,390,320]){await page.setViewportSize({width,height:900});await page.screenshot({path:path.join(out,`first-use-${width}.png`),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${width}`);}
 await page.getByRole('button',{name:'全部暂跳过',exact:true}).click();assert.equal(await page.getByText('已暂跳过',{exact:true}).count(),6);await page.getByRole('button',{name:'返回主站',exact:true}).click();await page.waitForURL(origin+'/');
 await page.goto(origin+'/settings?section=account');await page.getByRole('link',{name:'首次使用清单',exact:true}).click();await page.locator('.first-use').waitFor();assert.equal(await page.getByText('已暂跳过',{exact:true}).count(),6);
 signed=false;await page.goto(origin+'/login');await page.getByRole('button',{name:'回港',exact:true}).click();await page.waitForTimeout(150);assert.notEqual(new URL(page.url()).searchParams.get('section'),'first-use');
 assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({passed:true,widths:[1365,390,320],unexpected,errors},null,2));console.log('PASS actual App first-register → checklist → skip all → home → return → normal login; three widths');
}finally{await browser.close();await new Promise(r=>server.close(r));}
