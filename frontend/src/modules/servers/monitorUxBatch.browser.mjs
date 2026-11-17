// Actual built App/router/CSS -> real monitor API -> owned PostgreSQL.
// Only shell/auth/nodes/preferences fixtures are synthetic. No resident origin.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from '../../../node_modules/vite/dist/node/index.js';
import {chromium} from '../../../node_modules/playwright/index.mjs';
import {build} from '../../../node_modules/esbuild/lib/main.js';
const root=new URL('../../../',import.meta.url).pathname;
const out=process.env.STELLA_MONITOR_UX_OUT,dist=process.env.STELLA_APP_DIST,backend=process.env.STELLA_MONITOR_UX_HTTP;
assert(out&&path.isAbsolute(out)&&dist&&path.isAbsolute(dist)&&/^http:\/\/127\.0\.0\.1:\d+$/.test(backend));fs.mkdirSync(out,{recursive:true});
const bundle=await build({entryPoints:[root+'tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root,build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'actual built App/router/CSS + actual monitor API + loopback FastAPI + owned PostgreSQL; fixture auth/shell only',checks:[],screenshots:[],requests:[],errors:[],unknown:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 for(const width of [1440,393]){
  const reset=await(await fetch(backend+'/_fixture/reset',{method:'POST'})).json();
  const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(15000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));const now=new Date().toISOString();
  const nodes=[{id:reset.node_id,name:'隔离探测节点',host:'192.0.2.7',platform:'linux',status:'pending',last_seen_at:now,components:{}}];
  let loseCreate=true,loseDelete=true;const calls=[];
  await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications')return;result.unknown.push('WS '+u.href);ws.close();});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();const json=(body,status=200)=>route.fulfill({status,json:body});
   if(u.origin!==origin){result.unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
   if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
   if(p.startsWith('/monitors/')){
    calls.push({m,p,body:req.postData()});const response=await route.fetch({url:backend+p+u.search,maxRedirects:0});
    if(m==='POST'&&p==='/monitors/batches'&&loseCreate){loseCreate=false;assert.equal(response.status(),201);return route.abort('connectionreset');}
    if(m==='DELETE'&&loseDelete){loseDelete=false;assert.equal(response.status(),204);return route.abort('connectionreset');}
    return route.fulfill({response});
   }
   const pref=prefs.respond(m,p+u.search,req.postDataJSON());if(pref)return route.fulfill(pref);
   if(m==='GET'&&p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
   if(m==='GET'&&p==='/maps/world.geo.json')return json({type:'FeatureCollection',features:[{type:'Feature',properties:{name:'bounded'},geometry:{type:'Polygon',coordinates:[[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]]}}]});
   if(m==='GET'&&p==='/auth/me')return json({id:'owned-browser',username:'fixture',display_name:'隔离监控用户',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''});
   if(m==='GET'&&p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
   if(m==='POST'&&p==='/auth/activity')return json({ok:true});
   if(m==='GET'&&p==='/navigation')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'}],legacy_routes:{}});
   if(m==='GET'&&p==='/notifications/unread-count')return json({count:0});
   if(m==='GET'&&p==='/external-modules')return json([]);
   if(m==='GET'&&p==='/nodes/host')return json({installed:true});
   if(m==='GET'&&p==='/nodes/')return json(nodes);
   if(m==='GET'&&p==='/nodes/'+reset.node_id)return json({...nodes[0],latest_metrics:[],latest_sys_metric:null});
   if(m==='GET'&&p==='/nodes/map-topology')return json({generated_at:now,nodes:[],links:[],stats:{located:0,unknown:0,links:0}});
   if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
   result.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');
  });
  const state=async()=>await(await fetch(backend+'/_fixture/state')).json();
  const shot=async name=>{await page.mouse.move(0,0);const file=path.join(out,`${name}-${width}.png`);await page.screenshot({path:file});result.screenshots.push(file);};
  const geometry=async selector=>{const boxes=await page.locator(selector).evaluateAll(els=>els.filter(el=>el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();return {text:el.textContent,x:r.x,right:r.right,width:r.width,client:el.clientWidth,scroll:el.scrollWidth};}));for(const b of boxes){assert(b.scroll<=b.client+1,JSON.stringify(b));assert(b.x>=0&&b.right<=width,JSON.stringify(b));}return boxes;};
  await page.goto(origin+'/status?view=overview#service-monitors');await page.getByRole('button',{name:'监控管理',exact:true}).click();const manager=page.getByRole('dialog',{name:'监控管理',exact:true});await manager.waitFor();
  const row=manager.locator('.group-row').filter({hasText:'业务监控组'});assert.equal(await row.locator('.edit').count(),0);await row.getByRole('button',{name:'更多组操作 业务监控组',exact:true}).click();await shot('group-menu');await row.getByRole('menuitem',{name:'编辑监控组',exact:true}).click();
  const group=page.getByRole('dialog',{name:'监控组设置',exact:true});await group.waitFor();await group.getByRole('button',{name:'新建监控项',exact:true}).click();const create=page.getByRole('dialog',{name:'新建监控项',exact:true});await create.waitFor();assert.equal(await group.isVisible(),false);assert.equal(await page.locator('.child-form').count(),0);await create.getByRole('button',{name:'取消',exact:true}).click();await group.waitFor();assert.equal(await page.evaluate(()=>document.activeElement?.hasAttribute('data-create')),true);
  await group.getByRole('button',{name:'取消',exact:true}).click();
  // Returning to the list is required, not an Overview detour.
  await manager.waitFor();await manager.getByRole('button',{name:'添加监控',exact:true}).click();await create.waitFor();
  assert.equal(await create.getByLabel('端口',{exact:true}).inputValue(),'80');
  for(const type of ['ping','udp','http','https'])await create.locator('input[value="'+type+'"]').check();assert.equal(await create.getByLabel('端口',{exact:true}).inputValue(),'80/53/80/443');
  // Edit just UDP in the real input; no full-string re-entry.
  await create.getByLabel('端口',{exact:true}).evaluate(el=>{el.focus();el.setSelectionRange(3,5);});await page.keyboard.insertText('5353');assert.equal(await create.getByLabel('端口',{exact:true}).inputValue(),'80/5353/80/443');
  await create.locator('input[value=udp]').uncheck();await create.locator('input[value=udp]').check();assert.equal(await create.getByLabel('端口',{exact:true}).inputValue(),'80/5353/80/443');
  await create.getByLabel('监控项名称',{exact:true}).fill('多类型探测');await create.getByLabel('目标',{exact:true}).fill('2001:db8::1');await shot('create-all-types');await geometry('.create-window[open],.create-window[open] footer,.create-window[open] input');
  await create.getByRole('button',{name:'创建监控',exact:true}).click();await create.getByRole('alert').filter({hasText:'创建尚未确认'}).waitFor();assert.equal((await state()).groups.length,1);assert.equal((await state()).monitors.length,6);await shot('create-lost-ack');await create.getByRole('button',{name:'重新读取确认',exact:true}).click();await create.waitFor({state:'detached'});await manager.waitFor();assert.equal(calls.filter(c=>c.m==='POST'&&c.p==='/monitors/batches').length,1);
  await manager.getByRole('tab',{name:'独立监控 5',exact:true}).click();await manager.getByLabel('全选当前列表',{exact:true}).check();await manager.getByRole('button',{name:'批量删除 (5)',exact:true}).click();const bulk=page.getByRole('dialog',{name:'批量删除监控项',exact:true});await bulk.waitFor();await bulk.getByRole('button',{name:'确认批量删除',exact:true}).focus();await page.keyboard.press('Tab');assert.equal(await bulk.getByRole('button',{name:'取消',exact:true}).evaluate(el=>el===document.activeElement),true,'Tab stays inside bulk native dialog');await shot('bulk-confirm');const before=await state();await bulk.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await state(),before);assert.equal(calls.filter(c=>c.m==='DELETE').length,0);
  await manager.getByRole('button',{name:'批量删除 (5)',exact:true}).click();await bulk.getByRole('button',{name:'确认批量删除',exact:true}).click();await bulk.getByRole('button',{name:'完成',exact:true}).waitFor();assert.equal(calls.filter(c=>c.m==='DELETE').length,5);assert.equal((await state()).monitors.length,1);assert.equal((await state()).groups.length,1);await shot('bulk-deleted');await bulk.getByRole('button',{name:'完成',exact:true}).click();
  await manager.getByRole('tab',{name:'监控组 1',exact:true}).click();await manager.getByRole('button',{name:'更多组操作 业务监控组',exact:true}).click();await manager.getByRole('menuitem',{name:'编辑监控组',exact:true}).click();await group.waitFor();await group.getByRole('button',{name:'编辑监控项 组内探测',exact:true}).click();const item=page.getByRole('dialog',{name:'编辑监控项',exact:true});await item.waitFor();assert.equal(await item.getByLabel('目标',{exact:true}).inputValue(),'example.com');assert.equal(await item.getByLabel('端口',{exact:true}).inputValue(),'8443');assert.equal(await item.getByLabel('URL 路径、查询与片段',{exact:true}).inputValue(),'/legacy?q=1#x');await item.getByLabel('目标',{exact:true}).fill('new.example');await item.getByRole('button',{name:'保存',exact:true}).click();await group.waitFor();assert.equal((await state()).monitors[0].target,'https://new.example:8443/legacy?q=1#x');
  await group.getByRole('button',{name:'新建监控项',exact:true}).click();await create.waitFor();await create.getByLabel('监控项名称',{exact:true}).fill('组内新增');await create.getByLabel('目标',{exact:true}).fill('group.example');await create.locator('input[value=udp]').check();assert.equal(await create.getByLabel('端口',{exact:true}).inputValue(),'80/53');await create.getByRole('button',{name:'创建监控',exact:true}).click();await group.waitFor();assert.equal((await state()).groups.length,1);assert.equal((await state()).groups[0].child_ids.length,3);assert.equal(calls.filter(c=>c.m==='POST'&&c.p==='/monitors/batches').length,2);await shot('group-child-batch-created');
  await group.getByLabel('全选当前列表',{exact:true}).check();await group.getByRole('button',{name:'批量删除 (3)',exact:true}).click();await bulk.getByRole('button',{name:'确认批量删除',exact:true}).click();await bulk.getByRole('button',{name:'完成',exact:true}).click();await group.waitFor();assert.equal((await state()).groups.length,1);assert.deepEqual((await state()).groups[0].child_ids,[]);assert.equal((await state()).monitors.length,0);await shot('empty-group-kept');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);result.checks.push({width,realPG:true,portSegmentEdit:true,createPOSTs:calls.filter(c=>c.m==='POST'&&c.p==='/monitors/batches').length,deleteRequests:calls.filter(c=>c.m==='DELETE').length,final:await state()});result.requests.push({width,calls});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
