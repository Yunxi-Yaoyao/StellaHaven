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
 for(const width of [1365,390,320]){
  const context=await browser.newContext({viewport:{width,height:width<500?820:900},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(12000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));page.on('console',m=>result.console.push({width,type:m.type(),text:m.text()}));
  const now=new Date().toISOString();
  const monitor=(id,status,reason)=>({id,name:`业务探测 ${id}`,node_id:7,type:'ping',target:'owned.example',interval:60,timeout:5,status,status_reason:reason,last_check_at:now,last_latency_ms:2,management:null});
  const monitors=[{...monitor(1,'up','healthy'),name:'业务探测VeryLongUnbrokenMonitorNameForEllipsis',target:'very-long-owned-monitor-target.example.test:443',type:'tcp',visible:true,enabled:true,last_latency_ms:0},{...monitor(2,'down','failure'),name:'关闭端口探测',type:'tcp',target:'owned.example:8443',visible:true,enabled:true},{...monitor(3,'down','pending'),last_check_at:null,last_latency_ms:null,name:'等待首次探测'}];
  const groups=[{id:1,name:'默认入口探测 · LongUnbrokenMonitorGroupNameForOverflow',child_ids:[1,2],eligible_child_ids:[1,2],visible:true,enabled:true,failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,unknown_count:0,up_count:1,automatic:true}];
  const nodes=[{id:7,name:'探测节点',host:'192.0.2.7',platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['tcp','ping']}}}];
  let nextId=20,soloPosts=0,groupPosts=0,failRead=false,loseAck=false,receipt=null;
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
  await page.waitForFunction(()=>document.querySelector('.mon-availability')?.textContent?.includes('100.0%'));
  assert.equal(await page.locator('.mon-card').count(),2);assert.equal(await card.locator('.mon-counts').textContent(),'异常 1正常 1');
  assert.equal(await card.locator('.mon-latency').textContent(),'0.0 ms');
  assert.match(await page.locator('.mon-card').nth(1).locator('.mon-metrics').textContent(),/暂无数据/);
  const layout=await page.locator('.mon-card').evaluateAll(cards=>cards.map(card=>{const r=card.getBoundingClientRect();const metrics=card.querySelector('.mon-metrics'),parts=[...metrics.children].map(e=>e.getBoundingClientRect().toJSON());const target=card.querySelector('.mon-target');return {card:r.toJSON(),parts,targetHeight:target.getBoundingClientRect().height,targetLine:parseFloat(getComputedStyle(target).lineHeight),targetWhiteSpace:getComputedStyle(target).whiteSpace,within:[...card.querySelectorAll('.mon-name,.mon-counts,.mon-target,.mon-current,.mon-metrics')].every(el=>{const e=el.getBoundingClientRect();return e.left>=r.left&&e.right<=r.right&&e.width>0;}),scroll:card.scrollWidth,client:card.clientWidth};}));
  for(const l of layout){assert(l.within&&l.scroll<=l.client+1,JSON.stringify(l));assert.equal(l.targetWhiteSpace,'nowrap');if(l.card.width-30>250)assert(l.parts.every(p=>Math.abs(p.top-l.parts[0].top)<2),'metrics must share one row');else{assert(l.parts[1].top>l.parts[0].top);assert.equal(l.parts[1].top,l.parts[2].top);}}
  assert.equal(await card.locator('.mon-current .mon-child-picker').count(),1);
  const currentRows=await page.locator('.mon-current').evaluateAll(rows=>rows.map(row=>[...row.children].map(el=>{const r=el.getBoundingClientRect();return r.top+r.height/2;})));for(const centers of currentRows)assert(Math.max(...centers)-Math.min(...centers)<2,'current item/status/latency must be one row');
  await shot('overview');
  await card.locator('.mon-child-trigger').click();await page.getByRole('listbox').waitFor();assert.match(await page.getByRole('listbox').textContent(),/异常.*探测失败/);await shot('picker-status');await page.getByRole('option',{name:/关闭端口探测/}).click();await page.waitForFunction(()=>document.querySelector('.mon-card .mon-current')?.textContent?.includes('异常'));assert.equal(await card.locator('.mon-latency').textContent(),'— ms');await card.locator('.mon-child-trigger').click();await page.getByRole('option',{name:/业务探测/}).click();await page.waitForFunction(()=>document.querySelector('.mon-card .mon-current')?.textContent?.includes('0.0 ms'));await page.waitForFunction(()=>document.querySelector('.mon-card')?.querySelectorAll('.mon-child-content').length===1);
  // Same desktop viewport, different card widths: container queries, not random wrapping.
  if(width===1365){for(const columns of [2,3]){await page.locator('.mon-grid').evaluate((el,n)=>el.style.gridTemplateColumns=`repeat(${n},minmax(0,1fr))`,columns);await page.waitForFunction(()=>[...document.querySelectorAll('.mon-card')].every(c=>c.scrollWidth<=c.clientWidth+1));const widths=await page.locator('.mon-card').evaluateAll(cards=>cards.map(c=>({width:c.clientWidth,metrics:[...c.querySelector('.mon-metrics').children].map(e=>e.getBoundingClientRect().top),overflow:c.scrollWidth>c.clientWidth+1})));for(const c of widths){assert(!c.overflow);if(c.width-28>250)assert(c.metrics.every(y=>Math.abs(y-c.metrics[0])<2));else{assert(c.metrics[1]>c.metrics[0]);assert.equal(c.metrics[1],c.metrics[2]);}}result.checks.push({desktopColumns:columns,widths});await shot('desktop-'+columns+'-columns');}await page.locator('.mon-grid').evaluate(el=>el.style.removeProperty('grid-template-columns'));}
  await card.locator('.mon-inspect summary').click();assert.equal(await card.locator('.mon-inspect').getAttribute('open'),'');assert.match(await card.locator('.mon-inspect').textContent(),/very-long-owned-monitor-target.example.test:443/);await shot('target-details');await card.locator('.mon-inspect summary').click();
  await page.getByRole('button',{name:'简易',exact:true}).click();assert.equal(await card.locator('.blk').count(),24);await shot('simple-history');await page.getByRole('button',{name:'图表',exact:true}).click();await card.locator('.spark canvas').waitFor();
  await card.locator('.mon-heading button').click();const dialog=page.locator('.group-dialog');await dialog.waitFor();assert.equal(await dialog.locator('.child-row').count(),2);assert.match(await dialog.locator('.child-row').nth(1).textContent(),/异常/);assert.match(await dialog.locator('.child-row').nth(1).textContent(),/探测失败/);await shot('group-settings');
  await dialog.locator('.member-sampling summary').first().click();assert.match(await dialog.locator('.member-sampling').first().textContent(),/60 秒一次/);await shot('member-sampling');
  await dialog.getByRole('switch',{name:'显示 关闭端口探测',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="显示 关闭端口探测"]')?.getAttribute('aria-checked')==='false');
  await dialog.getByRole('switch',{name:'显示 关闭端口探测',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="显示 关闭端口探测"]')?.getAttribute('aria-checked')==='true');
  await dialog.getByRole('switch',{name:'启用 关闭端口探测',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="启用 关闭端口探测"]')?.getAttribute('aria-checked')==='false');
  await dialog.getByRole('switch',{name:'启用 关闭端口探测',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="启用 关闭端口探测"]')?.getAttribute('aria-checked')==='true');
  await dialog.getByRole('button',{name:'编辑监控项 关闭端口探测',exact:true}).click();await page.locator('.edit-body').waitFor();await shot('member-edit');await page.keyboard.press('Escape');
  await dialog.getByRole('button',{name:'移出监控组 关闭端口探测',exact:true}).click();assert.equal(await dialog.locator('.child-row').count(),1);await dialog.getByRole('button',{name:'保存设置',exact:true}).click();await dialog.waitFor({state:'detached'});assert.deepEqual(groups[0].child_ids,[1]);assert.equal(monitors.length,3);
  await card.locator('.mon-heading button').click();await dialog.waitFor();await dialog.getByRole('switch',{name:'显示监控组',exact:true}).click();await dialog.getByRole('switch',{name:'启用监控组',exact:true}).click();await dialog.getByRole('button',{name:'保存设置',exact:true}).click();await dialog.waitFor({state:'detached'});assert.equal(groups[0].visible,false);assert.equal(groups[0].enabled,false);await page.waitForFunction(()=>document.querySelectorAll('.mon-card').length===2);
  assert(!result.writes.some(w=>w.m==='DELETE'));
  result.checks.push({width,layout,targetSingleLine:true,targetFullDetails:true,currentStatusLatencySameRow:true,zeroVsNull:true,history24Blocks:true,switchReadback:true,membershipNotDeletion:true});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify({passed:true,widths:result.checks.filter(c=>c.width).map(c=>c.width),screenshots:result.screenshots.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
