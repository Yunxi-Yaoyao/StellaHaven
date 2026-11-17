// Full production-built App/router/shared CSS; bounded synthetic HTTP only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.STELLA_WINDOWS_EVIDENCE,dist=process.env.STELLA_APP_DIST;
assert(out&&path.isAbsolute(out)&&dist&&path.isAbsolute(dist));fs.mkdirSync(out,{recursive:true});
assert(!fs.existsSync(path.join(out,'browser-result.json')),'owned output must be fresh');
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'production-built actual App/router; synthetic HTTP, not live probes or PG',checks:[],screenshots:[],writes:[],errors:[],unknown:[],console:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 for(const width of [1365,390,320]){
  const context=await browser.newContext({viewport:{width,height:width<500?820:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(12000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));page.on('console',m=>result.console.push({width,type:m.type(),text:m.text()}));
  const now=new Date().toISOString();
  const monitor=(id,status,reason)=>({id,name:`业务探测 ${id}`,node_id:7,type:'ping',target:'owned.example',interval:60,timeout:5,status,status_reason:reason,last_check_at:now,last_latency_ms:2,management:null});
  const monitors=[{...monitor(1,'up','healthy'),name:'节点 A 服务',target:'very-long-owned-monitor-target.example.test:443',type:'tcp',visible:true,enabled:true,last_latency_ms:999999.9},{...monitor(2,'down','failure'),name:'关闭端口探测',type:'tcp',target:'owned.example:8443',visible:true,enabled:true},{...monitor(3,'down','pending'),last_check_at:null,last_latency_ms:null,name:'独立监控',visible:true,enabled:true}];
  monitors.push({...monitors[0],id:4,name:'hidden member',visible:false},{...monitors[0],id:5,name:'disabled solo',enabled:false});
  const groups=[{id:1,name:'业务服务监控组',child_ids:[1,2,4],eligible_child_ids:[1,2],visible:true,enabled:true,failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,unknown_count:0,up_count:1,automatic:true}];
  const nodes=[{id:7,name:'探测节点',host:'192.0.2.7',platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['tcp','ping']}}}];
  let expire=false;let nextId=20,soloPosts=0,groupPosts=0,failRead=false,loseAck=false,receipt=null;
  const history=id=>id===3?[]:Array.from({length:12},(_,i)=>({ts:new Date(Date.now()-(11-i)*60000).toISOString(),success:id===1,latency_ms:id===1?(i===11?0:2+i):null,loss_pct:id===1?0:100,sample_count:1,success_count:id===1?1:0,latency_count:id===1?1:0,loss_count:1}));
  await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications'&&!u.search)return;result.unknown.push('WS '+u.href);ws.close();});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),b=req.postDataJSON();const json=(body,status=200)=>route.fulfill({status,json:body});
   if(u.origin!==origin){result.unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
   if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
   const pref=prefs.respond(m,p+u.search,b);if(pref)return route.fulfill(pref);
   if(u.search&&!(m==='GET'&&((/^\/monitors\/\d+\/series$/.test(p)&&[...u.searchParams.keys()].every(k=>['start','end','step','limit'].includes(k)))||(p==='/alerts/incidents'&&u.search==='?limit=5&offset=0&status=unresolved')))){result.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');}
   if(m==='GET'&&p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
   if(m==='GET'&&p==='/maps/world.geo.json')return json({type:'FeatureCollection',features:[{type:'Feature',properties:{name:'bounded geometry'},geometry:{type:'Polygon',coordinates:[[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]]}}]});
   if(m==='GET'&&p==='/auth/me')return json({id:'fixture-owner',username:'fixture',display_name:'监控用户',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''});
   if(m==='GET'&&p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
   if(m==='POST'&&p==='/auth/activity')return json({ok:true});
   if(m==='GET'&&p==='/navigation')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'}],legacy_routes:{}});
   if(m==='GET'&&p==='/notifications/unread-count')return json({count:0});
   if(m==='GET'&&p==='/external-modules')return json([]);
   if(m==='GET'&&p==='/nodes/host')return json({installed:true});
   if(m==='GET'&&p==='/nodes/')return json(nodes);
   if(m==='GET'&&p==='/nodes/7')return json({...nodes[0],latest_metrics:[],latest_sys_metric:null});
   if(m==='GET'&&p==='/nodes/map-topology')return json({generated_at:now,nodes:[],links:[],stats:{located:0,unknown:0,links:0}});
   if(m==='PATCH'&&/^\/monitors\/\d+$/.test(p)){const item=monitors.find(i=>i.id===+p.split('/')[2]);assert(item);Object.assign(item,b);groups[0].eligible_child_ids=groups[0].child_ids.filter(id=>monitors.find(i=>i.id===id)?.visible!==false&&monitors.find(i=>i.id===id)?.enabled!==false);result.writes.push({width,m,p,b});return json(item);}
   if(m==='PUT'&&p==='/monitors/groups/1'){Object.assign(groups[0],b);result.writes.push({width,m,p,b});return json(groups[0]);}
   if(m==='POST'&&p==='/auth/refresh')return json({detail:'expired'},401);
   if(m==='GET'&&/^\/monitors\/\d+\/checks$/.test(p))return json([{id:1,ts:now,success:true,latency_ms:2},{id:2,ts:now,success:false,latency_ms:null}]);
   if(m==='GET'&&p==='/monitors/')result.checks.push({width,readback:true,names:monitors.map(x=>x.name)});
   if(m==='GET'&&p==='/monitors/')return expire?json({detail:'expired'},401):failRead?json({detail:'Synthetic readback forbidden'},403):json(monitors);
   if(m==='GET'&&p==='/monitors/groups')return failRead?json({detail:'Synthetic readback forbidden'},403):json(groups);
   if(m==='GET'&&/^\/monitors\/\d+\/series$/.test(p))return json(history(+p.split('/')[2]));
   if(m==='GET'&&/^\/monitors\/\d+\/mtr$/.test(p))return json([]);
   if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
   if(m==='GET'&&p.startsWith('/monitors/groups/receipts/'))return receipt?json(receipt):json({detail:'inconclusive'},404);
   if(m==='POST'&&p==='/monitors/'){
    soloPosts++;assert(!('items' in b)&&!('group_id' in b));const item={...b,id:nextId++,status:'down',status_reason:'pending',last_check_at:null,last_latency_ms:null};monitors.push(item);result.writes.push({width,m,p,b,id:item.id});failRead=true;if(loseAck)return route.abort('failed');return json(item,201);
   }
   if(m==='POST'&&p==='/monitors/groups'){
    groupPosts++;assert.equal(b.items.length,2);const ids=[];for(const item of b.items){const id=nextId++;ids.push(id);monitors.push({...item,id,status:'down',status_reason:'pending',last_check_at:null,last_latency_ms:null});}const group={id:8,name:b.name,child_ids:ids,failure_policy:b.failure_policy,rotation_seconds:b.rotation_seconds,status:'down',up_count:0,down_count:2,unknown_count:0};groups.push(group);receipt={group_id:group.id,monitor_ids:ids};result.writes.push({width,m,p,b});return json(group,201);
   }
   result.unknown.push(m+' '+p);return route.abort('blockedbyclient');
  });
  const shot=async name=>{await page.mouse.move(0,0);const file=path.join(out,`${name}-${width}.png`);await page.screenshot({path:file});result.screenshots.push(file);};

  const baselineWrites=result.writes.length;const manager=page.getByRole('dialog',{name:'监控管理',exact:true}),group=page.getByRole('dialog',{name:'监控组设置',exact:true}),item=page.getByRole('dialog',{name:'编辑监控项',exact:true});
  const ready=async()=>{await manager.waitFor();await page.waitForFunction(()=>document.querySelector('.management-panel header button')?.disabled===false);};
  const enter=async()=>{await page.getByRole('button',{name:'监控管理',exact:true}).click();await ready();};
  const close=async()=>{await manager.getByRole('button',{name:'关闭监控管理',exact:true}).click();await manager.waitFor({state:'hidden'});};
  const geom=async(loc,label)=>{const g=await loc.evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,right:r.right,top:r.top,bottom:r.bottom,scroll:el.scrollWidth,client:el.clientWidth};});result.checks.push({width,label,geometry:g});assert(g.x>=0&&g.right<=width+1&&g.scroll<=g.client+1,label+JSON.stringify(g));};
  await page.goto(origin+'/status?view=overview#service-monitors');await page.locator('.mon-card').first().waitFor();await enter();await geom(manager.locator('.management-panel'),'manager');await shot('management-groups');
  assert.equal(await manager.locator('details').count(),0);assert.equal(await manager.getByRole('switch').count(),2);
  await manager.getByRole('button',{name:'编辑',exact:true}).click();await group.waitFor();assert.equal(await manager.isVisible(),false);await geom(group,'group');assert.equal(await group.locator('.member-list-head').getByRole('button',{name:'新建监控项',exact:true}).count(),1);await shot('group-editor');
  await group.getByRole('button',{name:'编辑监控项 节点 A 服务',exact:true}).click();await item.waitFor();assert.equal(await group.isVisible(),false);await item.getByLabel('名称',{exact:true}).fill('取消不应保存');await item.getByRole('button',{name:'返回监控组',exact:true}).click();await group.waitFor();assert.equal(monitors[0].name,'节点 A 服务');
  const memberMenu=group.getByRole('button',{name:'成员操作 节点 A 服务',exact:true});await memberMenu.focus();await page.keyboard.press('ArrowDown');await page.getByRole('menu',{name:'成员操作 节点 A 服务',exact:true}).waitFor();await geom(page.getByRole('menu',{name:'成员操作 节点 A 服务',exact:true}),'member-menu');assert(await page.getByRole('menuitem',{name:'移出监控组',exact:true}).isEnabled());await page.keyboard.press('Escape');assert(await memberMenu.evaluate(e=>e===document.activeElement));assert.equal(groups[0].child_ids.length,3);
  await group.getByRole('button',{name:'聚合与轮播设置 ›',exact:true}).click();const rules=page.getByRole('dialog',{name:'聚合与轮播设置',exact:true});await rules.waitFor();await geom(rules,'rules');await page.waitForTimeout(180);await page.keyboard.press('Escape');await page.waitForTimeout(220);if(await rules.isVisible()){(result.blockers??=[]).push({width,issue:'rules Escape did not close nested native dialog; 完成 used to continue'});await rules.getByRole('button',{name:'完成',exact:true}).focus();await page.keyboard.press('Escape');await page.waitForTimeout(180);result.checks.push({width,rulesEscapeAfterFocusButton:!(await rules.isVisible())});if(await rules.isVisible())await rules.getByRole('button',{name:'完成',exact:true}).click();}await rules.waitFor({state:'hidden'});await group.getByRole('button',{name:'取消',exact:true}).click();assert.equal(result.writes.length,baselineWrites);await enter();await manager.getByRole('button',{name:'编辑',exact:true}).click();await group.waitFor();await group.getByLabel('监控组名称',{exact:true}).fill('业务服务监控组已保存');await group.getByRole('button',{name:'保存设置',exact:true}).click();await group.waitFor({state:'hidden'});assert.equal(groups[0].name,'业务服务监控组已保存');
  await enter();await manager.getByRole('switch',{name:'总览显示 业务服务监控组已保存',exact:true}).click();await ready();assert.equal(groups[0].visible,false);await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===1);await enter();await manager.getByRole('switch',{name:'总览显示 业务服务监控组已保存',exact:true}).click();await ready();
  await manager.getByRole('switch',{name:'启用 业务服务监控组已保存',exact:true}).click();await ready();await close();await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===1);await enter();await manager.getByRole('switch',{name:'启用 业务服务监控组已保存',exact:true}).click();await ready();
  await manager.getByRole('tab',{name:/独立监控/}).click();const solo=manager.locator('.item-row').filter({has:page.getByRole('button',{name:'独立监控',exact:true})});await solo.getByRole('button',{name:'编辑',exact:true}).click();await item.waitFor();await geom(item,'item');await shot('item-editor');
  await item.getByLabel('名称',{exact:true}).fill('独立监控已保存');await item.getByLabel('目标',{exact:true}).fill('saved.example.test:9443');await item.getByLabel('检测间隔（秒）',{exact:true}).fill('75');await item.getByLabel('超时（秒）',{exact:true}).fill('7');
  // Initial standalone type is ping; select TCP so target stays valid.
  await item.locator('.dd-btn').first().click();await page.getByRole('option',{name:'TCP',exact:true}).click();
  await item.getByRole('button',{name:'保存',exact:true}).click();await item.waitFor({state:'hidden'});assert.equal(monitors[2].name,'独立监控已保存');assert.equal(monitors[2].target,'saved.example.test:9443');assert.equal(monitors[2].interval,75);assert.equal(monitors[2].timeout,7);
  await enter();await manager.getByRole('tab',{name:/独立监控/}).click();const saved=manager.locator('.item-row').filter({has:page.getByRole('button',{name:'独立监控已保存',exact:true})});await saved.getByRole('button',{name:'编辑',exact:true}).click();await item.waitFor();assert.equal(await item.getByLabel('名称',{exact:true}).inputValue(),'独立监控已保存');
  await item.getByRole('button',{name:'查看历史',exact:true}).click();const hist=page.getByRole('dialog',{name:'监控项历史',exact:true});await hist.waitFor();await hist.locator('li').nth(1).waitFor();await hist.locator('.dd-btn').click();await page.getByRole('option',{name:'异常',exact:true}).click();assert.equal(await hist.locator('li').count(),1);assert.match(await hist.locator('li').textContent(),/异常/);await geom(hist,'history');await page.waitForTimeout(180);await page.keyboard.press('Escape');await page.waitForTimeout(220);if(await hist.isVisible()){(result.blockers??=[]).push({width,issue:'history Escape did not close nested native dialog; close button used to continue'});await hist.getByRole('button',{name:'关闭历史',exact:true}).focus();await page.keyboard.press('Escape');await page.waitForTimeout(180);result.checks.push({width,historyEscapeAfterFocusButton:!(await hist.isVisible())});if(await hist.isVisible())await hist.getByRole('button',{name:'关闭历史',exact:true}).click();}await hist.waitFor({state:'hidden'});
  await item.getByRole('button',{name:'监控项操作',exact:true}).click();await page.getByRole('menuitem',{name:'删除监控项…',exact:true}).click();const confirm=page.getByRole('dialog',{name:'确认删除监控项',exact:true});await confirm.waitFor();assert.match(await confirm.textContent(),/删除「独立监控已保存」/);await confirm.getByRole('button',{name:'取消',exact:true}).click();await item.getByRole('button',{name:'取消',exact:true}).click();assert.equal(monitors.length,5);
  await enter();await manager.getByRole('button',{name:'添加监控',exact:true}).click();const add=page.getByRole('dialog',{name:'添加监控',exact:true});await add.waitFor();await add.getByLabel('监控项名称 1',{exact:true}).fill('新增独立');await add.getByLabel('监控项目标 1',{exact:true}).fill('owned.example:443');await add.getByRole('button',{name:'创建监控',exact:true}).click();await add.getByRole('alert').waitFor();assert.equal(soloPosts,1);await page.keyboard.press('Escape');assert(await add.isVisible());failRead=false;await add.getByRole('button',{name:'重新确认创建结果',exact:true}).click();await add.waitFor({state:'hidden'});assert.equal(soloPosts,1);
  await enter();await manager.getByRole('button',{name:'添加监控',exact:true}).click();await add.waitFor();await add.getByRole('button',{name:'监控组',exact:true}).click();await add.getByLabel('监控组名称',{exact:true}).fill('新增组');await add.getByLabel('监控项名称 1',{exact:true}).fill('新成员1');await add.getByLabel('监控项目标 1',{exact:true}).fill('owned.example:443');await add.getByRole('button',{name:'添加监控项',exact:true}).click();await add.getByLabel('监控项名称 2',{exact:true}).fill('新成员2');await add.getByLabel('监控项目标 2',{exact:true}).fill('owned.example:8443');await add.getByRole('button',{name:'创建监控',exact:true}).click();await add.waitFor({state:'hidden'});assert.equal(groupPosts,1);assert(result.writes.find(x=>x.m==='POST'&&x.p==='/monitors/groups').b.request_key);
  if(width===1365){await enter();expire=true;await manager.getByRole('button',{name:'重新读取',exact:true}).click();const login=page.getByRole('dialog',{name:'Stella 登录',exact:true});await login.waitFor();assert.equal(await manager.isVisible(),false);assert(await login.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}));}
  result.checks.push({width,journey:'overview-manager-group-item-cancel-menu-rules-toggle-solo-save-history-delete-cancel-create',passed:true});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=!result.blockers?.length;console.log(JSON.stringify({passed:result.passed,blockers:result.blockers,checks:result.checks.length,screenshots:result.screenshots.length,writes:result.writes.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}