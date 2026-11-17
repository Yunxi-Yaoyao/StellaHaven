// Full production-built App/router/shared CSS; bounded synthetic HTTP only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.STELLA_GROUP_EVIDENCE,dist=process.env.STELLA_APP_DIST;
assert(out&&path.isAbsolute(out)&&dist&&path.isAbsolute(dist));fs.mkdirSync(out,{recursive:true});
assert(!fs.existsSync(path.join(out,'browser-result.json')),'owned output must be fresh');
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'production-built actual App/router; synthetic HTTP, not live probes or PG',checks:[],screenshots:[],writes:[],errors:[],unknown:[],console:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 for(const width of [1200,1365,390,320]){
  const context=await browser.newContext({viewport:{width,height:width<500?820:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(12000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));page.on('console',m=>result.console.push({width,type:m.type(),text:m.text()}));
  const now=new Date().toISOString();
  const monitor=(id,status,reason)=>({id,name:`业务探测 ${id}`,node_id:7,type:'ping',target:'owned.example',interval:60,timeout:5,status,status_reason:reason,last_check_at:now,last_latency_ms:2,management:null});
  const monitors=[monitor(1,'up','healthy')];
  const groups=[{id:1,name:'默认入口探测 · LongUnbrokenMonitorGroupNameForOverflow',child_ids:[1],failure_policy:'any',rotation_seconds:0,status:'up',down_count:0,unknown_count:0,up_count:1,automatic:true}];
  const nodes=[{id:7,name:'探测节点',host:'192.0.2.7',platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['tcp','ping']}}}];
  let nextId=20,soloPosts=0,groupPosts=0,failRead=false,loseAck=false,receipt=null;
  const history=id=>id===1?[{ts:now,success:true,latency_ms:2,loss_pct:0,sample_count:1,success_count:1,latency_count:1,loss_count:1}]:[];
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
   if(m==='GET'&&p==='/monitors/')return failRead?json({detail:'Synthetic readback forbidden'},403):json(monitors);
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
  await page.goto(origin+'/status?view=overview#service-monitors');const card=page.locator('.mon-card').first();await card.waitFor();await page.locator('#service-monitors').scrollIntoViewIfNeeded();
  assert.equal(await page.locator('.mon-card').count(),1);assert.equal(await card.locator('.mon-counts').textContent(),'异常 0正常 1');assert.equal(await page.locator('.mon-count-total,.mon-count-unknown').count(),0);
  await shot('overview');
  const layout=await page.locator('.mon-card').evaluateAll(cards=>cards.map(card=>{const r=card.getBoundingClientRect(),name=card.querySelector('.mon-name').getBoundingClientRect();return {nameWidth:name.width,card:r.toJSON(),within:[...card.querySelectorAll('.mon-name,.mon-counts,button,.mon-target')].every(el=>{const e=el.getBoundingClientRect();return e.left>=r.left&&e.right<=r.right&&e.width>0;}),scroll:card.scrollWidth,client:card.clientWidth};}));assert(layout.every(c=>c.within&&c.scroll<=c.client+1&&c.nameWidth>=Math.min(200,c.card.width-90)),JSON.stringify(layout));

  await page.getByRole('button',{name:'添加监控',exact:true}).click();const dialog=page.locator('.group-dialog');assert.equal(await dialog.getByLabel('监控组名称',{exact:true}).count(),0);await shot('new-solo');
  await page.getByLabel('监控项名称 1',{exact:true}).fill('独立业务 TCP');await page.getByLabel('监控项目标 1',{exact:true}).fill('solo.example:443');
  await page.getByRole('button',{name:'监控组',exact:true}).click();await page.getByLabel('监控组名称',{exact:true}).fill('新业务监控组');await page.getByLabel('监控项名称 1',{exact:true}).fill('组内第一项');await page.getByLabel('监控项目标 1',{exact:true}).fill('group.example:443');await page.getByRole('button',{name:'添加监控项',exact:true}).click();await page.getByLabel('监控项名称 2',{exact:true}).fill('组内第二项');await page.getByLabel('监控项目标 2',{exact:true}).fill('group.example:8443');await dialog.evaluate(el=>el.scrollTop=0);await shot('group-drafts');
  await page.getByRole('button',{name:'独立监控项',exact:true}).click();assert.equal(await page.getByLabel('监控项名称 1',{exact:true}).inputValue(),'独立业务 TCP');assert.equal(await dialog.locator('.draft-item').count(),1);
  await page.getByLabel('监控项目标 1',{exact:true}).fill('1:1');await dialog.locator('[role=alert]').waitFor();await page.getByRole('button',{name:'创建监控',exact:true}).click();assert.equal(soloPosts,0);await shot('invalid-solo');await page.getByLabel('监控项目标 1',{exact:true}).fill('solo.example:443');
  await page.getByRole('button',{name:'创建监控',exact:true}).click();await dialog.getByText(/创建尚未确认/).waitFor();await shot('ack-readback-403');await page.getByRole('button',{name:'重新确认创建结果',exact:true}).click();assert.equal(soloPosts,1);await page.keyboard.press('Escape');assert.equal(await dialog.count(),1);
  await page.locator('a[href="/"]').first().evaluate(el=>el.click());await page.waitForTimeout(50);assert.equal(new URL(page.url()).pathname,'/status');
  if(width===1365){
   await page.locator('.servers-bar button').filter({hasText:/^服务器$/}).evaluate(el=>el.click());await page.waitForTimeout(50);assert.equal(new URL(page.url()).search,'?view=overview');
   let prompted=false;page.once('dialog',async d=>{assert.equal(d.type(),'beforeunload');prompted=true;await d.dismiss();});await page.reload({waitUntil:'domcontentloaded',timeout:3000}).catch(()=>null);assert(prompted);assert.equal(soloPosts,1);assert.equal(await page.getByLabel('监控项名称 1',{exact:true}).inputValue(),'独立业务 TCP');
  }
  failRead=false;await page.getByRole('button',{name:'重新确认创建结果',exact:true}).click();await dialog.waitFor({state:'detached'});assert.equal(soloPosts,1);assert.equal(groups.length,1);
  const solo=page.locator('.mon-card').filter({has:page.locator('.mon-name',{hasText:'独立业务 TCP'})});await solo.waitFor();assert.equal(await solo.locator('.mon-count-down').textContent(),'异常 1');assert.equal(await solo.locator('.mon-count-up').textContent(),'正常 0');assert.equal(await solo.locator('.mon-reason').textContent(),'尚未取得探测结果');await solo.locator('.mon-heading button').click();await page.getByRole('heading',{name:'监控项设置'}).waitFor();await page.getByRole('button',{name:'编辑监控项 独立业务 TCP'}).click();await page.locator('.edit-body').waitFor();await shot('standalone-edit');await page.keyboard.press('Escape');await page.getByRole('button',{name:'关闭监控组设置',exact:true}).click();
  await page.getByRole('button',{name:'添加监控',exact:true}).click();await page.getByRole('button',{name:'监控组',exact:true}).click();await page.getByLabel('监控组名称',{exact:true}).fill('两项业务组');for(const i of [1,2]){if(i===2)await page.getByRole('button',{name:'添加监控项',exact:true}).click();await page.getByLabel('监控项名称 '+i,{exact:true}).fill('业务端口 '+i);await page.getByLabel('监控项目标 '+i,{exact:true}).fill('atomic.example:'+(443+i));}await page.getByRole('button',{name:'创建监控',exact:true}).click();await dialog.waitFor({state:'detached'});assert.equal(groupPosts,1);assert.equal(groups.length,2);
  if(width===390){
   loseAck=true;await page.getByRole('button',{name:'添加监控',exact:true}).click();await page.getByLabel('监控项名称 1',{exact:true}).fill('结果不确定');await page.getByLabel('监控项目标 1',{exact:true}).fill('lost.example:443');await page.getByRole('button',{name:'创建监控',exact:true}).click();await dialog.getByText(/未收到监控项编号/).waitFor();await shot('unknown-post');failRead=false;await page.getByRole('button',{name:'仅重新读取监控项',exact:true}).click();assert.equal(soloPosts,2);assert.equal(await page.getByRole('button',{name:'独立监控项',exact:true}).isDisabled(),true);await page.locator('a[href="/"]').first().evaluate(el=>el.click());await page.waitForTimeout(50);assert.equal(new URL(page.url()).pathname,'/status');
  }
  result.checks.push({width,layout,binaryBusinessCauses:true,defaultStandalone:true,separateDrafts:true,standaloneCreatesNoGroup:true,readback403NoRepost:true,atomicTwoItemGroup:true,standaloneEdit:true,unknownPost:width===390});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify({passed:true,widths:result.checks.map(c=>c.width),screenshots:result.screenshots.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
