// Production-built App/router/CSS. All API writes are bounded in-memory fixtures.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
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
  const groups=[{id:2,name:'业务监控组',child_ids:[7],eligible_child_ids:[7],failure_policy:'any',rotation_seconds:0,status:'up',visible:true,enabled:true,up_count:1,down_count:0,unknown_count:0},{id:3,name:'自动入口组',automatic:true,child_ids:[9],eligible_child_ids:[9],failure_policy:'any',rotation_seconds:0,status:'up',visible:true,enabled:true,up_count:1,down_count:0,unknown_count:0}];
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
   if(m==='DELETE'&&/^\/monitors\/(7|8)$/.test(p)){
    deleteCalls++;const id=+p.split('/')[2];result.writes.push({width,m,p,rejected:id===8&&rejectSolo});
    if(id===8&&rejectSolo){rejectSolo=false;return json({detail:'Synthetic rejection'},403);}
    monitors=monitors.filter(m=>m.id!==id);for(const g of groups){g.child_ids=g.child_ids.filter(mid=>mid!==id);g.eligible_child_ids=g.child_ids;g.up_count=g.child_ids.length;}
    if(id===8)readFailures=1;else groupReadFailures=1;return route.fulfill({status:204,body:''});
   }
   result.unknown.push(m+' '+p+u.search);return route.abort('blockedbyclient');
  });
  const shot=async name=>{await page.mouse.move(0,0);const file=path.join(out,`${name}-${width}.png`);await page.screenshot({path:file});result.screenshots.push(file);};
  const geometry=async(selector)=>{const rects=await page.locator(selector).evaluateAll(els=>els.filter(el=>el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();return {text:el.textContent,client:el.clientWidth,scroll:el.scrollWidth,x:r.x,right:r.right,width:r.width,height:r.height};}));for(const r of rects){assert(r.scroll<=r.client+1,`${selector} overflow at ${width}: ${JSON.stringify(r)}`);assert(r.x>=0&&r.right<=width,`${selector} outside viewport at ${width}: ${JSON.stringify(r)}`);}return rects;};
  await page.goto(origin+'/status?view=overview#service-monitors');await page.getByRole('button',{name:'监控管理',exact:true}).click();const manager=page.getByRole('dialog',{name:'监控管理',exact:true});await manager.waitFor();await shot('management-groups');
  await manager.locator('.group-row').filter({hasText:'业务监控组'}).getByRole('button',{name:'编辑',exact:true}).click();const group=page.getByRole('dialog',{name:'监控组设置',exact:true});await group.waitFor();await shot('group-actions');const groupGeometry=await geometry('.group-dialog .child-row');
  await group.getByRole('button',{name:'删除监控项 业务探测VeryLongUnbrokenMonitorNameForEllipsis',exact:true}).click();const confirm=page.getByRole('dialog',{name:'确认删除监控项',exact:true});await confirm.waitFor();assert.equal(await page.getByRole('dialog',{name:'编辑监控项',exact:true}).count(),0);assert.match(await confirm.textContent(),/不会变为独立监控/);await shot('delete-member-confirm');await geometry('.item-window[open],.item-window[open]>h3');await confirm.getByRole('button',{name:'取消',exact:true}).click();await group.waitFor();assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label')),'删除监控项 业务探测VeryLongUnbrokenMonitorNameForEllipsis');assert.equal(deleteCalls,0);
  await group.getByRole('button',{name:'删除监控项 业务探测VeryLongUnbrokenMonitorNameForEllipsis',exact:true}).click();await confirm.getByRole('button',{name:'确认删除',exact:true}).click();await group.getByRole('button',{name:'重新读取监控项',exact:true}).waitFor();await shot('group-refresh-failed');await group.getByRole('button',{name:'重新读取监控项',exact:true}).click();await group.getByRole('button',{name:'重新读取监控项',exact:true}).waitFor({state:'detached'});await group.getByText('没有监控项，此组不会出现在总览。',{exact:true}).waitFor();assert.equal(deleteCalls,1);assert(!monitors.some(m=>m.id===7));assert.deepEqual(groups[0].child_ids,[]);await shot('last-member-empty-group');await group.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'监控管理',exact:true}).click();await manager.getByRole('tab',{name:'独立监控 2',exact:true}).click();await shot('standalone-actions');const listGeometry=await geometry('.management-panel .item-row');
  await manager.getByRole('button',{name:'删除监控项 保留的独立监控',exact:true}).click();await confirm.waitFor();await page.keyboard.press('Escape');await confirm.waitFor({state:'detached'});assert.equal(deleteCalls,1);
  await manager.getByRole('button',{name:'删除监控项 保留的独立监控',exact:true}).click();await confirm.getByRole('button',{name:'确认删除',exact:true}).click();await confirm.getByRole('alert').filter({hasText:'删除被拒绝'}).waitFor();assert(monitors.some(m=>m.id===8));await shot('delete-rejected-retry');await confirm.getByRole('button',{name:'确认删除',exact:true}).click();await confirm.getByRole('alert').waitFor();await shot('delete-ack-read-failed');assert.equal(await confirm.getByRole('button',{name:'取消',exact:true}).isDisabled(),true);await page.keyboard.press('Escape');assert(await confirm.isVisible());const beforeRetry=deleteCalls;await confirm.getByRole('button',{name:'重新读取确认',exact:true}).click();await confirm.waitFor({state:'detached'});assert.equal(deleteCalls,beforeRetry);assert.equal(await manager.locator('.item-row').count(),1);
  await manager.getByRole('button',{name:'编辑',exact:true}).click();const editor=page.getByRole('dialog',{name:'编辑监控项',exact:true});await editor.waitFor();await editor.getByRole('button',{name:'删除监控项',exact:true}).click();await confirm.waitFor();await shot('editor-direct-delete-confirm');await confirm.getByRole('button',{name:'取消',exact:true}).click();await editor.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'监控管理',exact:true}).click();await manager.locator('.group-row').filter({hasText:'自动入口组'}).getByRole('button',{name:'编辑',exact:true}).click();await group.waitFor();assert.equal(await group.getByRole('button',{name:/删除监控项/}).count(),0);await shot('automatic-boundary');await group.getByRole('button',{name:'取消',exact:true}).click();
  result.checks.push({width,lastMemberDeletedNotDetached:true,cancelNoMutation:true,standaloneDirect:true,editorDirect:true,rejectionRetry:true,ackReadRetryNoReplay:true,systemBoundary:true,deleteCalls,groupGeometry,listGeometry});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify(result.checks));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
