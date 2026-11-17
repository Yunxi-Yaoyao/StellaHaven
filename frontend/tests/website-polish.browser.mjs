// Actual App/SFCs over a private loopback Vite server; synthetic HTTP only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createServer,preview} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.STELLA_WEBSITE_EVIDENCE;
assert.ok(out&&path.isAbsolute(out),'Explicit evidence directory required');fs.mkdirSync(path.join(out,'screenshots'),{recursive:true});
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const receipt=JSON.parse(fs.readFileSync('tests/fixtures/websiteLowconfigReceipt.json','utf8'));
let item=structuredClone(receipt.before),entries=[],hold=false,release,held=false,corrupt=false,rejectWrite=false,deleted=false;
const entrySettings={revision:7,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://stella.private.test'};
const results={checks:[],unknown:[],errors:[],requests:[],geometry:[],screenshots:[],snapshots:[]};
const built=process.env.STELLA_APP_DIST;
if(built)assert.ok(path.isAbsolute(built));
const server=built?await preview({configFile:false,root:process.cwd(),build:{outDir:built},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}}):await createServer({configFile:false,root:process.cwd(),plugins:[vue()],cacheDir:path.join(out,'browser-cache'),optimizeDeps:{entries:['index.html']},server:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
let browser;
try{
 if(!built)await server.listen();const origin=server.resolvedUrls.local[0].replace(/\/$/,'');browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1365,height:900},serviceWorkers:'block'}),page=await context.newPage();
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
 await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
 page.on('pageerror',e=>results.errors.push(e.message));
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&['/','/ws/notifications'].includes(u.pathname))return;results.unknown.push('WS '+ws.url());ws.close();});
 await context.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),b=req.postDataJSON();
  const json=(value,status=200)=>route.fulfill({json:value,status});
  if(u.origin!==origin){results.unknown.push(m+' '+req.url());return route.abort('blockedbyclient');}
  if(m==='GET'&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||p.startsWith('/assets/')||p.startsWith('/static/')||p==='/favicon.svg'||req.isNavigationRequest()))return route.continue();
  results.requests.push({method:m,path:p,...(b?{body:b}:{})});
  const pref=preferences.respond(m,p+u.search,b);if(pref)return route.fulfill(pref);
  if(u.search){results.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');}
  if(p==='/auth/me'&&m==='GET')return json({id:'isolated-website-owner',username:'fixture-login',display_name:'隔离昵称',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''});
  if(p==='/auth/status'&&m==='GET')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(p==='/auth/security'&&m==='GET')return json({enabled:true,configured:true,elevated:true,single_user:true,setup_required:false});
  if(p==='/auth/activity'&&m==='POST')return json({ok:true});
  if(p==='/notifications/unread-count'&&m==='GET')return json({count:0});
  if(p==='/config/access-entries'&&m==='GET')return json({settings:entrySettings,deployed:{public:entrySettings.public_origin,private:entrySettings.private_origin},issuer:'https://issuer.example.test',websites:[{id:item.id,name:'hidden-engineering-detail',public_address:'https://upstream.example.test',private_address:'https://alternate.example.test'}]});
  if(p==='/admin/email/config'&&m==='GET')return json({host:'',port:465,password:'',username:'',enabled:false,from_name:''});
  if(p==='/avatar.png'&&m==='GET')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
  if(p==='/nodes/host'&&m==='GET')return json({installed:true});
  if(p==='/navigation'&&m==='GET')return json({entries,legacy_routes:{}});
  if(p==='/navigation'&&m==='PUT'){entries=b.reset?[]:b.entries;return json({entries});}
  if(p==='/external-modules'&&m==='GET')return json(deleted?[]:[item]);
  if(p==='/external-modules/'+item.id&&m==='GET'){
   if(hold){held=true;await new Promise(resolve=>{release=resolve;});}
   if(deleted)return json({detail:'missing'},404);
   return json(corrupt?{...item,private_address:'https://wrong.test/'}:item);
  }
  if(p==='/external-modules/'+item.id&&m==='DELETE'){deleted=true;entries=entries.filter(e=>e.id!==item.id);return route.fulfill({status:204});}
  if(p==='/website-settings/check'&&m==='POST')return json({...receipt.response.check,normalized_url:b.address});
  if(p==='/website-settings/'+item.id&&m==='PATCH'){
   if(rejectWrite)return json({detail:'输入校验未通过，草稿未改动'},422);
   item={...item,browser_url:b.address,name:b.name||item.name,icon:b.icon,entry_policy:b.entry_policy??item.entry_policy};
   if(Object.hasOwn(b,'private_address'))item.private_address=b.private_address;
   if(b.connection)item.connection={...b.connection,has_token:!!b.connection.token||item.connection?.has_token};
   if(b.custom)item.injection={...item.injection,active:b.custom,draft:b.custom};
   entries=entries.filter(e=>e.id!==item.id).concat({id:item.id,title:item.name,icon:item.icon,visible:b.visible});
   return json({...item,check:{...receipt.response.check,normalized_url:b.address}});
  }
  results.unknown.push(m+' '+p);return route.abort('blockedbyclient');
 });
 const settled=()=>page.waitForFunction(()=>!document.querySelector('[class*="-enter-active"],[class*="-leave-active"]'));
 const shot=async name=>{const file=path.join(out,'screenshots',name+'.png');await page.screenshot({path:file});results.screenshots.push(file);};
 const clearToast=async()=>{await page.locator('.toast').waitFor({state:'detached'});};
 const open=async()=>{await page.getByRole('button',{name:'编辑 '+item.name,exact:true}).click();await page.locator('#website-address').waitFor();await page.locator('.inline-editor fieldset:enabled').waitFor();await page.waitForFunction(address=>document.querySelector('#website-address')?.value===address,item.browser_url);};
 await page.goto(origin+'/settings?section=navigation');await page.locator('.nav-settings').waitFor();
 for(const width of [1365,1920,320,390]){
  await page.setViewportSize({width,height:900});await open();await settled();
  assert.equal(await page.getByLabel('其他访问地址',{exact:true}).count(),0);assert.equal(await page.getByLabel('内网地址',{exact:true}).count(),0);
  assert.equal(await page.locator('#website-address').inputValue(),receipt.before.browser_url);
  await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
  if(await page.getByText('自定义请求头',{exact:true}).count())await page.getByText('自定义请求头',{exact:true}).click();
  assert.equal(await page.locator('.inline-editor').getByText('连接方式',{exact:true}).count(),0);assert.equal(await page.getByText('更多连接选项',{exact:true}).count(),0);assert.equal(await page.getByText('凭据名称',{exact:true}).count(),0);
  const selector=page.locator('.website-setting-row').filter({hasText:'入口选择'});
  assert.equal(await selector.locator('details').count(),0);assert.equal(await selector.getByRole('button',{name:'始终使用默认入口',exact:true}).count(),1);
  const geometry=await page.locator('.inline-editor').evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,right:r.right,width:r.width,scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth};});
  assert.ok(geometry.x>=0&&geometry.right<=width+1);assert.ok(geometry.scrollWidth<=width);results.geometry.push({viewportWidth:width,kind:'proxy',...geometry});await shot('proxy-'+width);
  const prior=structuredClone(item);await page.getByLabel('显示名称',{exact:true}).fill('网站名称'+width);
  if(width===1365){hold=true;held=false;}
  await page.getByRole('button',{name:'保存',exact:true}).click();
  if(width===1365){await page.waitForFunction(()=>document.querySelector('.inline-editor fieldset')?.disabled);for(let i=0;i<100&&!held;i++)await new Promise(r=>setTimeout(r,20));assert.ok(held);assert.equal(await page.locator('.toast').count(),0);hold=false;release();}
  await page.getByText('网站已保存',{exact:true}).waitFor();assert.equal(await page.locator('.toast').count(),1);assert.equal(await page.locator('.nav-settings').getByText('网站已保存',{exact:true}).count(),0);await page.locator('.inline-editor').waitFor({state:'detached'});await settled();await shot('website-toast-'+width);
  const request=results.requests.filter(r=>r.method==='PATCH').at(-1).body;assert.ok(!Object.hasOwn(request,'private_address'));assert.ok(!Object.hasOwn(request,'connection'));assert.deepEqual(item.connection,prior.connection);assert.equal(request.entry_policy,prior.entry_policy);assert.equal(item.private_address,prior.private_address);assert.equal(item.origin,prior.origin);assert.equal(item.target_id,prior.target_id);assert.deepEqual(item.injection,prior.injection);results.snapshots.push({width,request,before:prior,after:structuredClone(item)});await clearToast();
 }
 results.checks.push('Proxy form has upstream only, independent fixed-default policy; metadata omits generated alternate; one shared toast after GET at four widths');
 // Independently exercise follow/public UI rather than only preserving wire values.
 await page.setViewportSize({width:1365,height:900});await open();
 await page.locator('.website-setting-row').filter({hasText:'入口选择'}).getByRole('button',{name:'始终使用默认入口',exact:true}).click();await page.getByRole('option',{name:'跟随当前 Stella 入口',exact:true}).click();
 await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('网站已保存',{exact:true}).waitFor();assert.equal(item.entry_policy,'follow');assert.equal(item.private_address,receipt.before.private_address);await clearToast();
 // Saved-but-unconfirmed is persistent; retry is GET only and emits exactly once.
 await open();await page.getByLabel('显示名称',{exact:true}).fill('等待回读');corrupt=true;
 const writes=results.requests.filter(r=>r.method==='PATCH').length;await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'保存结果尚未确认'}).waitFor();assert.equal(await page.locator('.toast').count(),0);await shot('readback-failure');corrupt=false;await page.getByRole('button',{name:'重试回读',exact:true}).click();await page.getByText('网站已保存',{exact:true}).waitFor();assert.equal(results.requests.filter(r=>r.method==='PATCH').length,writes+1);assert.equal(await page.locator('.toast').count(),1);await clearToast();
 // Inline validation failure retains editor and typed value.
 await open();await page.getByLabel('显示名称',{exact:true}).fill('保留失败输入');rejectWrite=true;await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'输入校验未通过'}).waitFor();assert.equal(await page.locator('.toast').count(),0);assert.equal(await page.getByLabel('显示名称',{exact:true}).inputValue(),'保留失败输入');await shot('write-failure');rejectWrite=false;await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('网站已保存',{exact:true}).waitFor();await clearToast();
 results.checks.push('Unconfirmed GET mismatch remains inline; retry performs no second PATCH; validation failure retains draft without success');
 // Second prior-site DTO is a synthetic Immich-like direct/OIDC fixture, not real PG.
 item={...item,mode:'iframe',connection:{transport:'direct',auth_mode:'oidc',header_name:'Authorization',injection_delivery:'loader',has_token:false},browser_url:'https://original.example.test/base?q=a%2Fb#start',private_address:'https://other.example.test/library?q=x%2Fy#last',entry_policy:'follow'};entries=[];
 await page.reload();await page.locator('.nav-settings').waitFor();
 for(const width of [1365,1920,320,390]){
  await page.setViewportSize({width,height:900});await open();await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();await settled();
  assert.equal(await page.getByLabel('其他访问地址',{exact:true}).count(),0);assert.equal(await page.getByText('更多连接选项',{exact:true}).count(),0);assert.equal(await page.getByText('连接方式',{exact:true}).count(),0);assert.equal(await page.getByText('自定义请求头',{exact:true}).count(),0);
  assert.equal(await page.locator('#website-address').inputValue(),item.browser_url);await shot('direct-'+width);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const prior=structuredClone(item);await page.getByLabel('自定义 CSS',{exact:true}).fill('/* fixture CSS '+width+' */body{color:teal}');await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('网站已保存',{exact:true}).waitFor();
  const request=results.requests.filter(r=>r.method==='PATCH').at(-1).body;assert.ok(!Object.hasOwn(request,'private_address'));assert.ok(!Object.hasOwn(request,'connection'));assert.equal(item.private_address,prior.private_address);assert.deepEqual(item.connection,prior.connection);assert.equal(item.browser_url,'https://original.example.test/base?q=a%2Fb#start');results.snapshots.push({kind:'direct-oidc',width,before:prior,after:structuredClone(item),request});await clearToast();
 }
 results.checks.push('Direct OIDC fixture keeps exact hidden alternate path/query/fragment and transport during metadata/CSS edits at four widths');
 for(const header of ['Authorization','X-API-Key']){
  item={...item,mode:'isolated_proxy',connection:{transport:'proxy',auth_mode:'header',header_name:header,injection_delivery:'proxy',has_token:true}};entries=[];await page.reload();await page.locator('.nav-settings').waitFor();
  for(const width of [1365,1920,320,390]){
   await page.setViewportSize({width,height:900});await open();const custom=page.getByLabel('自定义请求头',{exact:true});assert.equal(await custom.isVisible(),header!=='Authorization');assert.equal(await custom.inputValue(),header);
   if(header==='Authorization')await page.getByText('自定义请求头',{exact:true}).click();assert.ok(await custom.isVisible());await custom.scrollIntoViewIfNeeded();await shot('header-'+header+'-'+width);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   const prior=structuredClone(item);await page.getByLabel('显示名称',{exact:true}).fill('Header网站'+header+width);await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('网站已保存',{exact:true}).waitFor();const payload=results.requests.filter(r=>r.method==='PATCH').at(-1).body;assert.ok(!Object.hasOwn(payload,'connection'));assert.deepEqual(item.connection,prior.connection);await clearToast();
  }
 }
 // New login choice uses an automatic compatible connection; no transport selector.
 await page.getByRole('button',{name:'＋ 添加网站',exact:true}).click();await page.getByLabel('网站地址',{exact:true}).fill('https://new.example.test/path');await page.locator('.connection-grid>label').filter({hasText:'登录方式'}).getByRole('button').click();await page.getByRole('option',{name:'服务端凭据',exact:true}).click();await page.getByLabel('Token',{exact:true}).fill('Bearer synthetic-only');assert.equal(await page.getByLabel('自定义请求头',{exact:true}).isVisible(),false);await page.getByRole('button',{name:'检测',exact:true}).click();await page.locator('[aria-label="检测结果"]').waitFor();const draftCheck=results.requests.filter(r=>r.path==='/website-settings/check').at(-1).body;assert.equal(draftCheck.connection.transport,'auto');assert.equal(draftCheck.connection.header_name,'Authorization');assert.equal(draftCheck.connection.injection_delivery,'proxy');await shot('new-auto-header');await page.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'放弃修改',exact:true}).click();await page.locator('.inline-editor').waitFor({state:'detached'});results.checks.push('Authorization hidden by default, saved X-API-Key accurately expanded at four widths; new Header login remains auto');
 await page.setViewportSize({width:1365,height:900});await page.getByRole('button',{name:'下移 个人主页',exact:true}).click();await page.getByText('导航已同步',{exact:true}).waitFor();assert.equal(await page.locator('.toast').count(),1);assert.equal(await page.locator('.nav-settings').getByText('导航已同步',{exact:true}).count(),0);await shot('navigation-toast');await clearToast();
 await open();await page.getByRole('button',{name:'删除网站入口',exact:true}).click();await page.getByRole('button',{name:'确认删除入口',exact:true}).click();await page.getByText('网站入口已删除',{exact:true}).waitFor();assert.equal(await page.locator('.toast').count(),1);assert.equal(await page.getByRole('button',{name:'编辑 '+item.name,exact:true}).count(),0);await shot('delete-toast');await clearToast();results.checks.push('Navigation and deletion use shared single toast, no parent duplicate or permanent success paragraph');
 for(const width of [1365,1920,320,390]){
  await page.setViewportSize({width,height:900});await page.goto(origin+'/settings?section=services');await page.getByLabel('默认入口地址',{exact:true}).waitFor();await settled();
  assert.equal(await page.getByLabel('默认入口地址',{exact:true}).inputValue(),entrySettings.public_origin);assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),entrySettings.private_origin);
  assert.equal(await page.getByText('入口与网站详情',{exact:true}).count(),0);assert.equal(await page.getByLabel('节点连接主机名',{exact:true}).count(),0);assert.equal(await page.getByText('hidden-engineering-detail',{exact:true}).count(),0);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await shot('entry-'+width);
 }
 assert.ok(!results.requests.some(r=>r.path==='/config/public-host'));results.checks.push('Actual SettingsPage removes engineering detail and Agent-host UI/initial GET, keeping two main-site origins');
 // The actual current reader, not a rendered substitute of the guide.
 for(const width of [1365,1920,320,390]){
  await page.setViewportSize({width,height:900});await page.goto(origin+'/help?section=guide&page=websites');await page.locator('.doc-reading').waitFor();await settled();assert.ok((await page.locator('.doc-reading').textContent()).includes('系统自动选择已登记的隔离入口'));await shot('website-guide-'+width);
 }
 results.checks.push('Actual documentation reader explains automatic transport, preserved legacy addresses and optional Header override');
 assert.deepEqual(results.unknown,[]);assert.deepEqual(results.errors,[]);results.passed=true;await context.close();
}catch(error){results.failure={message:error.message,stack:error.stack};throw error;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(results,null,2));await browser?.close();if(built)await new Promise((resolve,reject)=>server.httpServer.close(e=>e?reject(e):resolve()));else await server.close();}
