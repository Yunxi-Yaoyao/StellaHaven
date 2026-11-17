// Production-built App/router/CSS. All API writes are bounded in-memory fixtures.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {preview} from '../../../node_modules/vite/dist/node/index.js';
import {chromium} from '../../../node_modules/playwright/index.mjs';
import {build} from '../../../node_modules/esbuild/lib/main.js';
const root=new URL('../../../',import.meta.url).pathname;
const out=process.env.STELLA_DELETE_EVIDENCE,dist=process.env.STELLA_APP_DIST;
assert(out&&path.isAbsolute(out)&&dist&&path.isAbsolute(dist));fs.mkdirSync(out,{recursive:true});
const bundle=await build({entryPoints:[root+'tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root,build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'actual production-built App/router/CSS; bounded synthetic HTTP only',checks:[],screenshots:[],writes:[],errors:[],unknown:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 for(const width of [1365,390,320]){
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(12000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));
  const now=new Date().toISOString();
  const monitor=(id,name,extra={})=>({id,name,node_id:7,type:'tcp',target:'owned.example:443',interval:60,timeout:5,status:'up',status_reason:'healthy',visible:true,enabled:true,effective_enabled:true,last_check_at:now,last_latency_ms:2,management:null,...extra});
  let monitors=[monitor(7,'业务探测VeryLongUnbrokenMonitorNameForEllipsis'),monitor(8,'保留的独立监控'),monitor(9,'系统入口探测',{management:'entry_icmp'}),monitor(10,'编辑页删除验证')];
  let groups=[{id:2,name:'业务监控组',child_ids:[7],eligible_child_ids:[7],failure_policy:'any',rotation_seconds:0,status:'up',visible:true,enabled:true,up_count:1,down_count:0,unknown_count:0},{id:3,name:'自动入口组',automatic:true,child_ids:[9],eligible_child_ids:[9],failure_policy:'any',rotation_seconds:0,status:'up',visible:true,enabled:true,up_count:1,down_count:0,unknown_count:0}];
  monitors.push(monitor(11,'第二成员名称'),monitor(12,'ACK丢失成员'),monitor(13,'并发成员'));
  groups[0].name='业务监控组VeryLongUnbrokenGroupNameForNarrowConfirmation';groups[0].child_ids=[7,11];groups[0].eligible_child_ids=[7,11];
  for(const [id,name,ids] of [[4,'可删除空组',[]],[5,'回执丢失组',[12]],[6,'范围变化组',[13]]])groups.push({...groups[0],id,name,child_ids:ids,eligible_child_ids:ids});
  for(const group of groups)group.stable_uuid=randomUUID();
  let scopeReadsFail=0;const atomicWrites=[];let scopeRace=true;
  const nodes=[{id:7,name:'探测节点',host:'192.0.2.7',platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['tcp','ping']}}}];
  let rejectSolo=true,readFailures=0,groupReadFailures=0,deleteCalls=0;
  await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications')return;result.unknown.push('WS '+u.href);ws.close();});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();const json=(body,status=200)=>route.fulfill({status,json:body});
   if(u.origin!==origin){result.unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
   if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
   const pref=prefs.respond(m,p+u.search,req.postDataJSON());if(pref)return route.fulfill(pref);
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
   if(m==='GET'&&p==='/monitors/'){if(readFailures){readFailures--;return json({detail:'Synthetic read failure'},503);}return json(monitors);}
   if(m==='GET'&&p==='/monitors/groups'){if(groupReadFailures){groupReadFailures--;return json({detail:'Synthetic group read failure'},503);}return json(groups);}
   if(m==='GET'&&/^\/monitors\/\d+\/(series|checks|mtr)$/.test(p))return json([]);
   if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
   if(m==='GET'&&/^\/monitors\/groups\/(2|4|5|6)\/deletion-state$/.test(p)){
    if(scopeReadsFail){scopeReadsFail--;return json({detail:'Synthetic scoped read failure'},503);}
    const id=+p.split('/')[3],g=groups.find(g=>g.id===id),expected=u.searchParams.getAll('expected_child_ids').map(Number);
    return json({stable_uuid:g?.stable_uuid??null,identity_matches:u.searchParams.has('expected_stable_uuid')?!!g&&g.stable_uuid===u.searchParams.get('expected_stable_uuid'):null,group_exists:!!g,name:g?.name??null,children:g?g.child_ids.map(mid=>monitors.find(m=>m.id===mid)):[],protected:false,remaining_child_ids:expected.filter(mid=>monitors.some(m=>m.id===mid))});
   }
   if(m==='POST'&&/^\/monitors\/groups\/(2|4|5|6)\/delete$/.test(p)){
    const id=+p.split('/')[3],body=req.postDataJSON(),g=groups.find(g=>g.id===id);assert(g);assert.deepEqual(Object.keys(body),['expected_child_ids','expected_stable_uuid']);assert.equal(body.expected_stable_uuid,g.stable_uuid);
    atomicWrites.push({id,expected:body.expected_child_ids});result.writes.push({width,m,p,body});
    if(id===6&&scopeRace){scopeRace=false;monitors.push(monitor(14,'确认后新增成员'));g.child_ids.push(14);return json({detail:'Synthetic concurrent membership change'},409);}
    assert.deepEqual([...body.expected_child_ids].sort(),[...g.child_ids].sort());const ids=[...g.child_ids];monitors=monitors.filter(m=>!ids.includes(m.id));groups=groups.filter(g=>g.id!==id);
    if(id===2)scopeReadsFail=1;
    if(id===5)return route.abort('connectionreset');
    return route.fulfill({status:204,body:''});
   }
   result.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');
  });
  const shot=async name=>{await page.mouse.move(0,0);const file=path.join(out,`${name}-${width}.png`);await page.screenshot({path:file});result.screenshots.push(file);};
  const geometry=async(selector)=>{const rects=await page.locator(selector).evaluateAll(els=>els.filter(el=>el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();return {text:el.textContent,client:el.clientWidth,scroll:el.scrollWidth,x:r.x,right:r.right,width:r.width,height:r.height};}));for(const r of rects){assert(r.scroll<=r.client+1,`${selector} overflow at ${width}: ${JSON.stringify(r)}`);assert(r.x>=0&&r.right<=width,`${selector} outside viewport at ${width}: ${JSON.stringify(r)}`);}return rects;};
  await page.goto(origin+'/status?view=overview#service-monitors');await page.getByRole('button',{name:'监控管理',exact:true}).click();
  const manager=page.getByRole('dialog',{name:'监控管理',exact:true}),confirm=page.getByRole('dialog',{name:'确认删除监控组',exact:true});await manager.waitFor();await shot('direct-group-list');
  const groupName=groups[0].name,trigger=manager.getByRole('button',{name:'删除监控组 '+groupName,exact:true});
  assert.equal(await manager.locator('.group-row').filter({hasText:'自动入口组'}).getByRole('button',{name:'删除',exact:true}).count(),0);
  await trigger.click();await confirm.getByRole('button',{name:'确认删除整组',exact:true}).waitFor();assert.match(await confirm.textContent(),/2 个监控项/);assert.match(await confirm.textContent(),/第二成员名称/);assert.match(await confirm.textContent(),/MTR/);await shot('whole-group-confirm');const confirmGeometry=await geometry('.group-delete-window[open],.group-delete-window[open]>h3,.group-delete-window[open] li');
  await confirm.getByRole('button',{name:'取消',exact:true}).click();await confirm.waitFor({state:'detached'});assert.equal(atomicWrites.length,0);assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label')),'删除监控组 '+groupName);
  await trigger.click();await confirm.waitFor();await page.keyboard.press('Escape');await confirm.waitFor({state:'detached'});assert.equal(atomicWrites.length,0);
  await trigger.click();await confirm.getByRole('button',{name:'确认删除整组',exact:true}).click();await confirm.getByRole('alert').filter({hasText:'删除尚未确认'}).waitFor();assert.equal(await confirm.getByRole('button',{name:'取消',exact:true}).isDisabled(),true);await shot('ack-scoped-read-failure');await page.keyboard.press('Escape');assert(await confirm.isVisible());
  await confirm.getByRole('button',{name:'重新读取确认',exact:true}).click();await confirm.waitFor({state:'detached'});assert.equal(atomicWrites.length,1);assert(!groups.some(g=>g.id===2));assert(!monitors.some(m=>[7,11].includes(m.id)));await manager.getByRole('button',{name:'删除监控组 可删除空组',exact:true}).waitFor();
  await manager.getByRole('button',{name:'删除监控组 可删除空组',exact:true}).click();await confirm.getByText('空组：只删除此监控组。',{exact:true}).waitFor();await shot('empty-group-confirm');await confirm.getByRole('button',{name:'确认删除整组',exact:true}).click();await confirm.waitFor({state:'detached'});assert.deepEqual(atomicWrites.at(-1),{id:4,expected:[]});
  await manager.getByRole('button',{name:'删除监控组 回执丢失组',exact:true}).click();await confirm.getByRole('button',{name:'确认删除整组',exact:true}).click();await confirm.getByRole('alert').waitFor();await shot('lost-ack-no-replay');const before=atomicWrites.length;await confirm.getByRole('button',{name:'重新读取确认',exact:true}).click();await confirm.waitFor({state:'detached'});assert.equal(atomicWrites.length,before);
  await manager.getByRole('button',{name:'删除监控组 范围变化组',exact:true}).click();await confirm.getByRole('button',{name:'确认删除整组',exact:true}).click();await confirm.getByRole('alert').filter({hasText:'成员范围已变化'}).waitFor();assert(groups.some(g=>g.id===6));assert.equal(await confirm.getByRole('button',{name:'确认删除整组',exact:true}).count(),0);await shot('scope-409');await confirm.getByRole('button',{name:'重新读取范围',exact:true}).click();await confirm.getByText('确认后新增成员',{exact:true}).waitFor();await shot('scope-refreshed-reconfirm');const beforeReconfirm=atomicWrites.length;assert.equal(beforeReconfirm,4);await confirm.getByRole('button',{name:'确认删除整组',exact:true}).click();await confirm.waitFor({state:'detached'});assert.deepEqual(atomicWrites.at(-1),{id:6,expected:[13,14]});assert.equal(atomicWrites.length,5);
  await manager.locator('.group-row').filter({hasText:'自动入口组'}).waitFor();await shot('only-system-group-remains');await geometry('.management-panel .group-row');
  assert.deepEqual(groups.map(g=>g.id),[3]);assert(monitors.some(m=>m.id===8));assert(monitors.some(m=>m.id===9));
  result.checks.push({width,directGroupList:true,scopeNamesAndCount:true,cancelAndEscapeZeroWrites:true,emptyDelete:true,ackReadFailureNoReplay:true,lostAckNoReplay:true,scope409Reconfirm:true,systemBoundary:true,atomicWrites,confirmGeometry});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify(result.checks));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}