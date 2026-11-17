// Actual production App/router/shared CSS + real api/client wrappers. No live API.
import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';
import {preview} from 'vite';import {chromium} from 'playwright';import {build} from 'esbuild';
const out=process.env.STELLA_MANAGEMENT_EVIDENCE,dist=process.env.STELLA_APP_DIST;assert(out&&dist&&path.isAbsolute(out)&&path.isAbsolute(dist));fs.mkdirSync(out,{recursive:true});
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'production actual App + router + shared CSS; synthetic bounded HTTP only',checks:[],writes:[],unknown:[],errors:[]};let browser;
try{browser=await chromium.launch({headless:true});for(const width of [1365,390,320]){
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(10000);
 const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
 page.on('pageerror',e=>result.errors.push(e.stack||e.message));const now=new Date().toISOString();let failRead=false,expire=false,account='fixture-owner';
 const user=()=>({id:account,username:'fixture',display_name:'监控用户',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''});
 const monitors=[1,2,3].map(id=>({id,name:id===1?'正常成员':id===2?'异常成员':'独立监控',node_id:7,type:'tcp',target:'owned.example:443',interval:60,timeout:5,status:id===2?'down':'up',status_reason:id===2?'failure':'healthy',visible:true,enabled:true,effective_enabled:true,last_check_at:now,last_latency_ms:id===2?null:2}));
 const groups=[{id:1,name:'入口监控组',child_ids:[1,2],eligible_child_ids:[1,2],visible:true,enabled:true,failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,up_count:1,unknown_count:0}];
 const aggregate=()=>{const g=groups[0];g.eligible_child_ids=g.enabled?g.child_ids.filter(id=>{const m=monitors.find(m=>m.id===id);return m.visible&&m.enabled;}):[];g.up_count=g.eligible_child_ids.filter(id=>monitors.find(m=>m.id===id).status==='up').length;g.down_count=g.eligible_child_ids.length-g.up_count;for(const m of monitors)m.effective_enabled=m.enabled&&(m.id===3||g.enabled);};
 const nodes=[{id:7,name:'探测节点',host:'192.0.2.7',platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['tcp','ping']}}}];
 const history=[{id:1,monitor_id:1,ts:now,success:true,latency_ms:2,loss_pct:0},{id:2,monitor_id:1,ts:now,success:false,latency_ms:null,loss_pct:100}];
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications')return;result.unknown.push('WS '+u.href);ws.close();});
 await context.route('**/*',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),b=req.postDataJSON();const json=(body,status=200)=>route.fulfill({status,json:body});
  if(u.origin!==origin){result.unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
  if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
  if(m==='GET'&&p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
  const pref=prefs.respond(m,p+u.search,b);if(pref)return route.fulfill(pref);
  if(m==='GET'&&p==='/auth/me')return json(user());if(m==='GET'&&p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(m==='POST'&&p==='/auth/activity')return json({ok:true});if(m==='POST'&&p==='/auth/refresh')return json({detail:'expired'},401);
  if(m==='POST'&&p==='/auth/login'){expire=false;return json(user());}if(m==='GET'&&p==='/auth/security')return json({enabled:false,configured:true,elevated:false,single_user:true,setup_required:false});
  if(m==='GET'&&p==='/navigation')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'}],legacy_routes:{}});
  if(m==='GET'&&p==='/notifications/unread-count')return json({count:0});if(m==='GET'&&p==='/external-modules')return json([]);
  if(m==='GET'&&p==='/nodes/host')return json({installed:true});if(m==='GET'&&p==='/nodes/')return json(nodes);if(m==='GET'&&p==='/nodes/7')return json({...nodes[0],latest_metrics:[],latest_sys_metric:null});
  if(m==='GET'&&p==='/nodes/map-topology')return json({generated_at:now,nodes:[],links:[],stats:{located:0,unknown:0,links:0}});
  if(m==='GET'&&p==='/maps/world.geo.json')return json({type:'FeatureCollection',features:[{type:'Feature',properties:{name:'bounded geometry'},geometry:{type:'Polygon',coordinates:[[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]]}}]});
  if(m==='GET'&&p==='/monitors/')return expire?json({detail:'expired'},401):failRead?json({detail:'readback failed'},503):json(monitors);
  if(m==='GET'&&p==='/monitors/groups')return json(groups);
  if(m==='GET'&&/^\/monitors\/\d+\/series$/.test(p))return json(history);if(m==='GET'&&/^\/monitors\/\d+\/mtr$/.test(p))return json([]);if(m==='GET'&&/^\/monitors\/\d+\/checks$/.test(p))return json(history);
  if(m==='PATCH'&&/^\/monitors\/\d+$/.test(p)){const item=monitors.find(i=>i.id===+p.split('/')[2]);assert(item);Object.assign(item,b);aggregate();result.writes.push({width,m,p,b});return json(item);}
  if(m==='PUT'&&p==='/monitors/groups/1'){Object.assign(groups[0],b);aggregate();result.writes.push({width,m,p,b});return json(groups[0]);}
  if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
  result.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');
 });
 const dialog=page.getByRole('dialog',{name:'监控管理',exact:true});const row=name=>dialog.locator('.row').filter({has:page.locator('strong',{hasText:name})});
 const ready=async()=>{await dialog.getByRole('button',{name:'关闭',exact:true}).waitFor();await page.waitForFunction(()=>!document.querySelector('.management-panel header button')?.disabled);};
 const enter=async()=>{await page.getByRole('button',{name:'监控管理',exact:true}).click();await ready();};
 const close=async()=>{await dialog.getByRole('button',{name:'关闭',exact:true}).click();await dialog.waitFor({state:'hidden'});};
 const toggle=async(name,label)=>{await row(name).getByRole('button',{name:label,exact:true}).click();await ready();};
 await page.goto(origin+'/status?view=overview#service-monitors');await page.locator('.mon-card').first().waitFor();await page.locator('#service-monitors').scrollIntoViewIfNeeded();const entryLayout=await page.getByRole('button',{name:'监控管理',exact:true}).evaluate(el=>{const header=el.parentElement,r=header.getBoundingClientRect();return {header:r.toJSON(),scroll:header.scrollWidth,client:header.clientWidth,buttons:[...header.querySelectorAll('button')].map(b=>({text:b.textContent,rect:b.getBoundingClientRect().toJSON()}))};});result.checks.push({width,overviewEntryLayout:entryLayout});await page.screenshot({path:path.join(out,`entry-${width}.png`)});await enter();assert.equal(await dialog.locator('select').count(),0);assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label')),'搜索监控');
 // Native dialog traps Tab and restores the real Overview trigger after Escape.
 const last=dialog.getByRole('button',{name:'历史',exact:true}).last();await last.focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'关闭');await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.match(await page.evaluate(()=>document.activeElement?.textContent),/监控管理/);await enter();
 await page.mouse.click(2,2);await dialog.waitFor({state:'hidden'});await enter();await page.keyboard.press('Shift+Tab');assert.equal(await page.evaluate(()=>document.querySelector('.management-panel')?.contains(document.activeElement)),true);
 await toggle('异常成员','隐藏');await close();await page.waitForFunction(()=>document.querySelector('.mon-card .mon-counts')?.textContent==='异常 0正常 1');
 await enter();await toggle('异常成员','显示');await toggle('异常成员','停用');await close();await page.waitForFunction(()=>document.querySelector('.mon-card .mon-counts')?.textContent==='异常 0正常 1');
 await enter();assert.match(await row('异常成员').textContent(),/已停用/);await toggle('异常成员','启用');await toggle('入口监控组','停用组');assert.match(await row('正常成员').textContent(),/组已停用/);await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===1);
 await enter();await toggle('入口监控组','启用组');await toggle('入口监控组','隐藏组');await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===1);await enter();await toggle('入口监控组','显示组');
 await toggle('独立监控','隐藏');await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===1);await enter();await toggle('独立监控','显示');await toggle('独立监控','停用');await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===1);await enter();await toggle('独立监控','启用');
 await row('正常成员').getByRole('button',{name:'历史',exact:true}).click();await dialog.locator('.history li').nth(1).waitFor();await dialog.locator('.history .dd-btn').click();await dialog.getByRole('option',{name:'异常',exact:true}).click();assert.equal(await dialog.locator('.history li').count(),1);assert.match(await dialog.locator('.history li').textContent(),/异常/);
 assert.equal(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth),true);assert.equal(await dialog.locator('.management-panel').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
 await page.screenshot({path:path.join(out,`management-${width}.png`)});await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===2);assert.equal(await page.locator('.mon-card .mon-counts').first().textContent(),'异常 1正常 1');
 // ACK saved + GET failed: freeze mutations, preserve confirmation, only GET retries.
 await enter();failRead=true;const before=result.writes.length;await row('异常成员').getByRole('button',{name:'隐藏',exact:true}).click();await dialog.getByRole('alert').filter({hasText:'操作尚未确认'}).waitFor();assert.equal(await dialog.getByRole('button',{name:'关闭',exact:true}).isDisabled(),true);await page.keyboard.press('Escape');assert.equal(await dialog.isVisible(),true);failRead=false;await dialog.getByRole('button',{name:'重新读取',exact:true}).click();await ready();assert.equal(result.writes.length,before+1);await toggle('异常成员','显示');
 if(width===1365){await dialog.getByLabel('搜索监控').fill('owner-private');expire=true;await dialog.getByRole('button',{name:'重新读取',exact:true}).click();const login=page.getByRole('dialog',{name:'Stella 登录',exact:true});await login.waitFor();assert.equal(await dialog.isVisible(),false);assert.equal(await page.evaluate(()=>document.querySelector('dialog.management-mask')?.open??false),false);const hit=await login.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2));});assert.equal(hit,true);account='fixture-other';await login.locator('[autocomplete="username"]').fill('fixture-other');await login.locator('[type="password"]').fill('synthetic-fixture-only');await login.getByRole('button',{name:'回港',exact:true}).click();await login.waitFor({state:'hidden'});if(!await dialog.isVisible())await enter();else await ready();assert.equal(await dialog.getByLabel('搜索监控').inputValue(),'');assert.equal(await dialog.locator('.history').count(),0);await close();result.checks.push({authSuspended:true,loginInteractiveAboveManagement:true,crossAccountDraftClear:true});}
 result.checks.push({width,entry:true,groupAndSingleRecover:true,aggregateReadback:true,childStatus:true,historyDropdown:true,focusEscapeTab:true,ackGetFailureNoReplay:true});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify(result));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
