// Real unmodified production App/router; synthetic HTTP only, no live service.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.STELLA_GROUP_EVIDENCE,dist=process.env.STELLA_APP_DIST;
assert(out&&path.isAbsolute(out)&&dist&&path.isAbsolute(dist));fs.mkdirSync(out,{recursive:true});
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'Actual production-built App; synthetic auth/grant and monitor HTTP, not live PG/Agent',checks:[],screenshots:[],requests:[],errors:[],expectedFaults:[],boundaryProbes:[],unknown:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 const allScenarios=[...[403,401,404,500].map(status=>({name:`get-${status}`,status})),{name:'post-unknown-get-401',status:401,unknownPost:true},{name:'elevation-get-503',status:503,elevation:true}];
 const scenarios=process.env.STELLA_GROUP_SCENARIO?allScenarios.filter(s=>s.name===process.env.STELLA_GROUP_SCENARIO):allScenarios;assert(scenarios.length,'Unknown requested scenario');
 for(const width of [1365,320])for(const scenario of scenarios){
  const context=await browser.newContext({viewport:{width,height:width===1365?1080:850},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();
  const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  let boundaryActive=false;const boundaryRejected=[];
  const boundaryExpected=['HEAD /monitors/groups','GET /monitors/groups?unexpected=1','WS /ws/unknown-fixture'];
  const rejectUnknown=tag=>{if(boundaryActive&&boundaryExpected.includes(tag))boundaryRejected.push(tag);else result.unknown.push(tag);};
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));page.on('console',m=>{if(m.type()!=='error')return;const u=new URL(m.location().url||origin);if((boundaryActive&&u.pathname==='/monitors/groups'&&m.text().includes('net::ERR_BLOCKED_BY_CLIENT'))||(u.pathname==='/monitors/groups/4/children'&&((scenario.elevation&&m.text().includes('403 (Forbidden)'))||(scenario.unknownPost&&m.text().includes('net::ERR_FAILED'))))||(u.pathname==='/monitors/groups'&&m.text().includes(`${scenario.status} (`))||(scenario.status===401&&u.pathname==='/auth/refresh'&&m.text().includes('503 (Service Unavailable)')))result.expectedFaults.push({width,scenario:scenario.name,path:u.pathname,error:m.text()});else result.errors.push(m.text());});
  const now=new Date().toISOString();
  const monitors=[{id:10,name:'默认入口 · ICMP',node_id:7,type:'ping',target:'192.0.2.3',interval:60,timeout:1,status:'up',last_check_at:now,last_latency_ms:1.2,management:'entry_icmp'},
   {id:11,name:'其他入口 · ICMP',node_id:7,type:'ping',target:'192.0.2.4',interval:60,timeout:1,status:'unknown',last_check_at:null,last_latency_ms:null,management:'entry_icmp'}];
  const groups=[{id:4,name:'测试节点A-LongUnbrokenParentNameForReceiptRegression → 中心',child_ids:[10,11],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:1,automatic:true,source_node_id:7},
   {id:5,name:'节点B-LongUnbrokenNameWithoutSpacesForOverflowRegression → 中心',child_ids:[],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:0,automatic:true,source_node_id:8}];
  const nodes=[{id:7,name:'测试节点 A',host:'192.0.2.7',platform:'linux',status:'pending',components:null},{id:8,name:'测试节点 B',host:'192.0.2.8',platform:'linux',status:'pending',components:null}];
  let nextId=12,elevated=!scenario.elevation,failedRead=false,injectReadFailure=false,heldRead=false,releaseRead,readStarted;
  let postCount=0,committed=0;
  await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications'&&!u.search)return;rejectUnknown(u.origin===origin.replace('http:','ws:')?'WS '+u.pathname+u.search:'WS '+ws.url());ws.close();});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),b=req.postDataJSON();const json=(body,status=200)=>route.fulfill({status,...(status===204?{body:''}:{json:body})});
   if(u.origin!==origin){rejectUnknown(m+' '+req.url());return route.abort('blockedbyclient');}
   if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
   result.requests.push({width,scenario:scenario.name,method:m,path:p,query:u.search,...(b?{body:b}:{})});
   const pref=preferences.respond(m,p+u.search,b);if(pref)return route.fulfill(pref);
   if(u.search&&!(m==='GET'&&((/^\/monitors\/(10|11|12)\/series$/.test(p)&&[...u.searchParams.keys()].every(k=>['start','end','step','limit'].includes(k)))||(p==='/alerts/incidents'&&u.search==='?limit=5&offset=0&status=unresolved')))){rejectUnknown(m+' '+p+u.search);return route.abort('blockedbyclient');}
   if(m==='GET'&&p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
   if(m==='GET'&&p==='/maps/world.geo.json')return json({type:'FeatureCollection',features:[{type:'Feature',properties:{name:'Synthetic bounded geometry'},geometry:{type:'Polygon',coordinates:[[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]]}}]});
   if(m==='GET'&&p==='/auth/me')return json({id:'fixture-owner',username:'fixture',display_name:'隔离监控用户',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''});
   if(m==='GET'&&p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
   if(m==='GET'&&p==='/auth/security')return json({enabled:true,configured:true,elevated,expires_at:null,single_user:true,setup_required:false});
   if(m==='POST'&&p==='/auth/admin/unlock'){assert.deepEqual(b,{password:''});elevated=true;return json({ok:true});}
   if(m==='POST'&&p==='/auth/refresh'&&scenario.status===401)return json({detail:'Synthetic refresh unavailable; do not replay writes'},503);
   if(m==='POST'&&p==='/auth/activity')return json({ok:true});
   if(m==='GET'&&p==='/navigation')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'}],legacy_routes:{}});
   if(m==='GET'&&p==='/notifications/unread-count')return json({count:0});
   if(m==='GET'&&p==='/external-modules')return json([]);
   if(m==='GET'&&p==='/nodes/host')return json({installed:true});
   if(m==='GET'&&p==='/nodes/')return json(nodes);
   if(m==='GET'&&p==='/nodes/map-topology')return json({generated_at:now,nodes:[],links:[],stats:{located:0,unknown:0,links:0}});
   if(m==='GET'&&p==='/monitors/')return json(monitors);
   if(m==='GET'&&p==='/monitors/groups'){if(injectReadFailure){failedRead=true;return json({detail:`Synthetic GET readback ${scenario.status}`},scenario.status);}if(heldRead){readStarted?.();await new Promise(resolve=>releaseRead=resolve);}return json(groups);}
   if(m==='GET'&&/^\/monitors\/(10|11|12)\/(series|mtr)$/.test(p))return json([]);
   if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
   if(m==='POST'&&p==='/monitors/groups/4/children'){
    postCount++;
    if(!elevated)return json({detail:{code:'admin_elevation_required'}},403);
    const child={...b,id:nextId++,status:'unknown',last_check_at:null,last_latency_ms:null,management:null};monitors.push(child);groups[0].child_ids.push(child.id);committed++;injectReadFailure=true;if(scenario.unknownPost)return route.abort('failed');return json(child,201);
   }
   if(m==='PATCH'&&/^\/monitors\/(10|12)$/.test(p)){assert(elevated);const item=monitors.find(item=>item.id===+p.split('/').at(-1));Object.assign(item,b);return json(item);}
   if(m==='DELETE'&&p==='/monitors/12'){assert(elevated);monitors.splice(monitors.findIndex(item=>item.id===12),1);groups.forEach(g=>g.child_ids=g.child_ids.filter(id=>id!==12));return json(null,204);}
   if(m==='PUT'&&p==='/monitors/groups/4'){assert(elevated);Object.assign(groups[0],b);return json(groups[0]);}
   rejectUnknown(m+' '+p);return route.abort('blockedbyclient');
  });
  const shot=async name=>{const file=path.join(out,`${scenario.name}-${name}-${width}.png`);await page.screenshot({path:file});result.screenshots.push(file);};
  await page.goto(origin+'/status?view=overview#service-monitors');await page.getByText(groups[0].name,{exact:true}).waitFor();
  boundaryActive=true;
  const boundaryResults=await page.evaluate(async()=>{
   const denied=[];for(const [url,method] of [['/monitors/groups','HEAD'],['/monitors/groups?unexpected=1','GET']]){try{await fetch(url,{method});denied.push(false);}catch{denied.push(true);}}
   denied.push(await new Promise(resolve=>{const ws=new WebSocket(location.origin.replace('http:','ws:')+'/ws/unknown-fixture');ws.onclose=()=>resolve(true);ws.onerror=()=>resolve(false);}));return denied;
  });
  boundaryActive=false;assert.deepEqual(boundaryResults,[true,true,true]);assert.deepEqual(boundaryRejected.sort(),[...boundaryExpected].sort());result.boundaryProbes.push({width,scenario:scenario.name,rejected:boundaryRejected});
  await page.locator('#service-monitors').scrollIntoViewIfNeeded();await page.mouse.move(0,0);await shot('overview');
  const empty=page.locator('.mon-card').filter({hasText:groups[1].name});assert((await empty.textContent()).includes('未知'));assert(!(await empty.textContent()).includes('0 ms'));
  const bounds=await page.locator('.mon-card').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect();return {x:r.x,right:r.right,scroll:el.scrollWidth,client:el.clientWidth,children:[...el.querySelectorAll('.mon-name,.mon-group-health,button,.mon-target')].map(e=>{const c=e.getBoundingClientRect();return c.left>=r.left-1&&c.right<=r.right+1;})};}));assert(bounds.every(r=>r.x>=0&&r.right<=width&&r.scroll<=r.client+1&&r.children.every(Boolean)),JSON.stringify(bounds));
  await page.getByRole('button',{name:'管理父监控子项',exact:true}).click();await page.getByRole('button',{name:'新建子项',exact:true}).click();await page.getByLabel('子项名称',{exact:true}).fill('附加 TCP');await page.getByLabel('子项目标',{exact:true}).fill('192.0.2.3:443');await page.getByRole('button',{name:'创建并加入',exact:true}).click();
  if(scenario.elevation){await page.getByRole('heading',{name:'解锁管理权限',exact:true}).waitFor();assert.equal(monitors.length,2);
  // Synthetic fixture verifies orchestration only: no password or credential is
  // entered. Dispatching submit exercises the actual modal/API/retry flow.
   await page.locator('.admin-dialog form').evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));await page.getByRole('button',{name:'确认重试一次',exact:true}).click();}
  await page.locator('.group-dialog [role="alert"]').waitFor();
  const retry=page.getByRole('button',{name:'重新确认创建结果',exact:true});assert.equal(await retry.count(),1,'Denied readback must retain receipt and offer GET-only confirmation');await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='重新确认创建结果'&&!b.disabled));
  if(scenario.unknownPost){await retry.click();await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='重新确认创建结果'&&!b.disabled));}
  assert(failedRead);assert.equal(monitors.length,3);const posts=postCount;assert.equal(posts,scenario.elevation?2:1);assert.equal(committed,1);
  // A real denied GET must keep the creation task, not offer a fresh POST.
  await retry.click();await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='重新确认创建结果'&&!b.disabled));assert.equal(postCount,posts);
  for(const name of ['取消新建','关闭父监控设置','保存组合'])assert(await page.getByRole('button',{name,exact:true}).isDisabled());
  assert.equal(await page.getByLabel('子项名称',{exact:true}).inputValue(),'附加 TCP');
  await page.keyboard.press('Escape');assert.equal(await page.locator('.group-dialog').count(),1);
  await page.locator('.group-mask').click({position:{x:1,y:1}});assert.equal(await page.locator('.group-dialog').count(),1);
  // Actual router link activation cannot unmount the receipt-owning editor.
  await page.locator('a[href="/"]').first().evaluate(el=>el.click());await page.waitForTimeout(50);assert.equal(new URL(page.url()).pathname,'/status');assert.equal(await page.locator('.child-form').count(),1);
  if(scenario.status===403){
   const pendingBounds=await page.locator('.group-dialog').evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,scroll:el.scrollWidth,client:el.clientWidth};});assert(pendingBounds.left>=0&&pendingBounds.right<=width&&pendingBounds.scroll<=pendingBounds.client+1,JSON.stringify(pendingBounds));
   await page.locator('.group-dialog').evaluate(el=>el.scrollTop=0);await shot('pending-receipt');
   await page.locator('.group-dialog').evaluate(el=>el.scrollTop=el.scrollHeight);await shot('pending-receipt-actions');
  }
  injectReadFailure=false;
  if(scenario.unknownPost){await retry.click();await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='重新确认创建结果'&&!b.disabled));assert.equal(postCount,1);assert.equal(await page.locator('.child-form').count(),1);assert((await page.locator('.group-dialog').textContent()).includes('不代表可以安全重建'));result.checks.push({width,scenario:scenario.name,postCount,committed,unknownReceiptRetained:true,closeBlocked:true,routeBlocked:true});await context.close();continue;}
  // Hold the confirming GET: draft/task remain, no premature success/duplicate.
  heldRead=true;const started=new Promise(resolve=>readStarted=resolve);await retry.click();await started;
  assert(await retry.isDisabled());assert.equal(await page.locator('.child-form').count(),1);assert.equal(await page.getByLabel('子项名称',{exact:true}).inputValue(),'附加 TCP');assert.equal(postCount,posts);assert.equal(await page.locator('.toast').count(),0);
  heldRead=false;releaseRead();await page.locator('.child-form').waitFor({state:'detached'});await page.getByRole('button',{name:'编辑子项 附加 TCP',exact:true}).waitFor();assert.equal(postCount,posts);await shot('children');
  const dialog=await page.locator('.group-dialog').evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,right:r.right,scroll:el.scrollWidth,client:el.clientWidth,children:[...el.querySelectorAll('input,button,.dd')].filter(e=>e.getClientRects().length).map(e=>{const b=e.getBoundingClientRect();return b.left>=r.left-1&&b.right<=r.right+1;})};});assert(dialog.x>=0&&dialog.right<=width&&dialog.scroll<=dialog.client+1&&dialog.children.every(Boolean),JSON.stringify(dialog));
  await page.getByRole('button',{name:'编辑子项 附加 TCP',exact:true}).click();await page.locator('.edit-body').waitFor();await page.keyboard.press('Escape');await page.locator('.edit-body').waitFor({state:'detached'});assert.equal(await page.locator('.group-dialog').count(),1);
  await page.getByRole('button',{name:'编辑子项 附加 TCP',exact:true}).click();const edit=page.locator('.edit-body');await edit.locator('input').first().fill('改名 TCP');await edit.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('button',{name:'永久删除子项 改名 TCP',exact:true}).waitFor();
  await page.getByRole('button',{name:'永久删除子项 改名 TCP',exact:true}).click();await page.getByRole('button',{name:'取消删除',exact:true}).click();assert(monitors.some(m=>m.name==='改名 TCP'));await page.getByRole('button',{name:'永久删除子项 改名 TCP',exact:true}).click();await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await page.getByRole('button',{name:'编辑子项 改名 TCP',exact:true}).waitFor({state:'detached'});assert(!monitors.some(m=>m.id===12));
  await page.getByRole('button',{name:'编辑子项 默认入口 · ICMP',exact:true}).click();await edit.getByText('Ping · 自动入口',{exact:true}).waitFor();assert(await edit.locator('input[type=number]').isDisabled());await edit.locator('input').first().fill('自动名称可编辑');await edit.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('button',{name:'编辑子项 自动名称可编辑',exact:true}).waitFor();
  await page.locator('.child-choice input[type=checkbox]').nth(1).uncheck();await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.locator('.group-dialog').waitFor({state:'detached'});assert.deepEqual(groups[0].child_ids,[10]);assert(monitors.some(m=>m.id===11));
  await page.getByRole('button',{name:'管理父监控子项',exact:true}).click();await page.locator('.child-choice input[type=checkbox]').nth(1).check();await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.locator('.group-dialog').waitFor({state:'detached'});assert.deepEqual(groups[0].child_ids,[10,11]);
  for(const legacy of ['/settings?section=servers','/settings?tab=servers']){await page.goto(origin+legacy);await page.waitForURL('**/status?view=overview#service-monitors');await page.locator('#service-monitors').waitFor();assert.equal(await page.locator('.node-monitoring').count(),0);}
  result.checks.push({width,scenario:scenario.name,bounds,dialog,postCount:posts,committed,crud:true,automaticReadOnly:true,nestedEscape:true,legacyRedirect:true,actualAppElevation:!!scenario.elevation,readbackOnlyRetry:true,heldReadback:true,closeBlocked:true,routeBlocked:true});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise((resolve,reject)=>server.httpServer.close(e=>e?reject(e):resolve()));}
