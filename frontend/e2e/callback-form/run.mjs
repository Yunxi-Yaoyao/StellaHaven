// HTTP component acceptance only: API and management grant below are synthetic.
// No production proxy, credentials, identity linking or real secret reveal.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const root=process.cwd();
const output=process.env.STELLA_CALLBACK_OUTPUT||await mkdtemp(path.join(tmpdir(),'stella-callback-evidence-'));
await mkdir(output,{recursive:true});
const cache=await mkdtemp(path.join(tmpdir(),'stella-callback-vite-'));
const initial=()=>({issuer:'https://stella.example.com',discovery_url:'https://stella.example.com/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.com/oauth/authorize',token_endpoint:'https://stella.example.com/oauth/token',userinfo_endpoint:'https://stella.example.com/oauth/userinfo',jwks_uri:'https://stella.example.com/oauth/jwks',capabilities:{},clients:[{client_id:'immich',name:'家庭相册',enabled:true,has_secret:true,scopes:['openid','profile','email'],redirect_uris:['https://photos.example.com/auth/login','https://photos.p/user-settings','https://yunxi.life/auth/login','http://192.168.1.8:2283/auth/login','http://localhost:2283/user-settings','app.immich:///oauth-callback']}]});
let state=initial(),failWrite=false,partialRead=false;
const writes=[];
const auth='\0callback-auth',api='\0callback-api';
const server=await createServer({configFile:false,root,cacheDir:cache,plugins:[vue(),{name:'callback-isolation',enforce:'pre',resolveId(id,importer){if(id.endsWith('/home/auth'))return auth;if(id==='../../api/client'||(id==='./client'&&importer?.endsWith('/api/authProvider.ts')))return api;},load(id){if(id===auth)return `import {ref,reactive} from 'vue';export const isAdmin=ref(true);export const auth=reactive({sessionGeneration:0,requestEpoch:0,sessionClosing:false,suspended:false,me:{id:'fixture-owner'}});`;if(id===api)return `export async function api(path,options){const response=await fetch('/fixture-api'+path,{...options,headers:{'Content-Type':'application/json'}});const body=await response.json();if(!response.ok)throw {...body,status:response.status};return body;}`;},configureServer(vite){vite.middlewares.use(async(req,res,next)=>{
 if(req.url==='/fixture-api/auth/provider/config'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(partialRead?{clients:null}:state));return;}
 if(req.url?.startsWith('/fixture-api/')){let body='';for await(const chunk of req)body+=chunk;writes.push({method:req.method,path:req.url,body:JSON.parse(body||'null')});res.setHeader('Content-Type','application/json');if(failWrite){res.statusCode=400;res.end(JSON.stringify({detail:'回调地址未通过校验；草稿保留'}));return;}if(req.method==='PATCH'){Object.assign(state.clients[0],JSON.parse(body));res.end(JSON.stringify(state.clients[0]));return;}throw Error('fixture forbids this operation');}

 if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml('/',`<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>:root{--bg-base:#151619;--bg-panel:#202126;--bg-raised:#292b31;--text-hi:#ececf0;--text-lo:#babcc6;--accent:#9bd9c8;--accent-dim:#548c80;color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#151619;color:#ececf0;font-family:system-ui,sans-serif}main{max-width:980px;padding:24px;margin:auto}header{font-size:12px;color:#babcc6;margin:0 0 16px}@media(max-width:600px){main{padding:12px}}</style></head><body><main><header>隔离组件验证 · 模拟应用数据 / 管理解锁，不连接真实服务</header><div id="app"></div></main><script type="module" src="/e2e/callback-form/fixture.ts"></script></body></html>`));return;}next();
 });}}],optimizeDeps:{entries:['e2e/callback-form/fixture.ts'],include:['vue','vue-router']},server:{host:'127.0.0.1',port:0},appType:'custom'});
let browser;
const receipts=[];
try{
 await server.listen();const port=server.httpServer.address().port,url=`http://127.0.0.1:${port}/`;
 assert.equal((await fetch(url)).status,200);
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 for(const width of [320,390,1280]){
  state=initial();failWrite=false;partialRead=false;writes.length=0;
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
  const page=await context.newPage(),errors=[],requests=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error('FIXTURE_PAGE_ERROR',e.message);});page.on('console',msg=>{if(msg.type()==='error')console.error('FIXTURE_CONSOLE',msg.text());});
  await page.route('**/*',async route=>{const requestURL=new URL(route.request().url());requests.push(requestURL.origin);if(requestURL.hostname!=='127.0.0.1')return route.abort();return route.continue();});
  try{
   await page.goto(url);await page.getByText('已连接应用（1）',{exact:true}).click();await page.locator('[data-client-details]>summary').click();await page.getByRole('button',{name:'编辑',exact:true}).click();
   await page.getByLabel('应用地址 1',{exact:true}).waitFor();assert.equal(await page.getByLabel('回调用途路径 2',{exact:true}).inputValue(),'/user-settings');
   assert.equal(await page.locator('[data-legacy-callbacks]').evaluate(e=>e.open),false);
   assert.equal(await page.locator('.secret-panel').count(),0);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await page.getByLabel('应用名称',{exact:true}).focus();await page.keyboard.press('Tab');assert.equal(await page.getByLabel('Client ID',{exact:true}).evaluate(e=>e===document.activeElement),true);
   await page.getByLabel('回调用途路径 1',{exact:true}).fill('/auth/login\n/user-settings');
   await page.getByLabel('回调用途路径 2',{exact:true}).fill('/user-settings\n/auth/login');
   await page.getByRole('button',{name:'预览变更',exact:true}).click();
   assert.equal(writes.length,0);assert.match(await page.getByLabel('回调变更摘要',{exact:true}).innerText(),/新增 2 · 移除 0/);
   assert.equal(await page.locator('[data-review]').evaluate(e=>e===document.activeElement),true);
   await page.screenshot({path:path.join(output,`callback-${width}.png`),fullPage:true});
   failWrite=true;await page.getByRole('button',{name:'保存变更',exact:true}).click();await page.getByRole('alert').waitFor();
   assert.equal(await page.getByLabel('回调用途路径 2',{exact:true}).inputValue(),'/user-settings\n/auth/login');
   failWrite=false;await page.getByRole('button',{name:'保存变更',exact:true}).click();await page.getByText('变更已保存',{exact:true}).waitFor();
   assert.equal(writes.length,2);assert.deepEqual(state.clients[0].redirect_uris,initial().clients[0].redirect_uris.concat(['https://photos.example.com/user-settings','https://photos.p/auth/login']));
   // A partial HTTP response is unknown, never a fabricated empty registration.
   partialRead=true;await page.reload();await page.getByRole('alert').waitFor();assert.equal(await page.getByText('尚未连接应用。',{exact:true}).count(),0);
   assert.deepEqual(errors,[]);assert.equal(new Set(requests).size,1);
   receipts.push({width,http:true,overflow:false,keyboard:true,explicitPreview:true,serverFailureDraftRetained:true,verifiedReadback:true,partialReadRejected:true,secretRendered:false,mockBoundary:'HTTP stub API; synthetic elevated admin; no real provider/authentication'});
  }finally{await context.clearCookies();await context.close();}
 }
 await writeFile(path.join(output,'browser-result.json'),JSON.stringify(receipts,null,2));console.log(JSON.stringify(receipts,null,2));
}finally{await browser?.close();await server.close();await rm(cache,{recursive:true,force:true});}
