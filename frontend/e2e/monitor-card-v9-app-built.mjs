// Full production-built App/router/shared CSS; bounded synthetic HTTP only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.STELLA_CARD_EVIDENCE,dist=process.env.STELLA_APP_DIST;
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
  const monitors=[{...monitor(1,'up','healthy'),name:'节点A业务探测VeryLongUnbrokenMonitorNameForEllipsis',target:'very-long-owned-monitor-target.example.test:443',type:'tcp',visible:true,enabled:true,last_latency_ms:999999.9},{...monitor(2,'down','failure'),name:'关闭端口探测',type:'tcp',target:'owned.example:8443',visible:true,enabled:true},{...monitor(3,'down','pending'),last_check_at:null,last_latency_ms:null,name:'等待首次探测',visible:true,enabled:true}];
  monitors.push({...monitors[0],id:4,name:'hidden member',visible:false},{...monitors[0],id:5,name:'disabled solo',enabled:false});
  const groups=[{id:1,name:'默认入口探测 · LongUnbrokenMonitorGroupNameForOverflow',child_ids:[1,2,4],eligible_child_ids:[1,2],visible:true,enabled:true,failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,unknown_count:0,up_count:1,automatic:true}];
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
  assert.equal(await page.locator('.mon-card').count(),2,'hidden and disabled items stay hidden');
  const inspect=async()=>await card.evaluate(card=>{
   const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
   const c=box(card),selectors=['.mon-name','.mon-counts','.mon-op','.mon-child-trigger','.mon-latency'];
   const parts=Object.fromEntries(selectors.map(s=>[s,box(card.querySelector(s))]));
   const visible=e=>getComputedStyle(e).display!=='none';
   return {c,parts,overflow:card.scrollWidth>card.clientWidth+1,target:visible(card.querySelector('.mon-target')),metrics:visible(card.querySelector('.mon-metrics')),line:box(card.querySelector('.mon-current')),heading:box(card.querySelector('.mon-heading')),extra:card.querySelectorAll('.mon-inspect,.mon-diagnosis').length};
  });
  for(const cardWidth of width===1365?[480,460,420,380,340,320,300]:[null]){
   if(cardWidth)await page.locator('.mon-grid').evaluate((el,w)=>el.style.gridTemplateColumns=`${w}px`,cardWidth);
   await page.mouse.move(0,0);await page.waitForTimeout(240);
   const l=await inspect();result.checks.push({width,cardWidth,layout:l});
   assert(!l.overflow,JSON.stringify(l));assert.equal(l.extra,0,'no permanent sampling/diagnostic rows');
   for(const [name,p]of Object.entries(l.parts))assert(p.x>=l.c.x&&p.right<=l.c.right&&p.width>0, name+JSON.stringify(l));
   assert(l.parts['.mon-name'].right<=l.parts['.mon-counts'].x,'heading must not overlap counts');
   assert(l.parts['.mon-counts'].right<=l.parts['.mon-op'].x,'counts must not overlap operation');
   assert(l.heading.height<=30,'header is exactly one line');assert(l.line.height<=34,'current item is exactly one line');
   assert(l.parts['.mon-child-trigger'].width>=56,'current item retains identifiable width');
   assert(l.parts['.mon-child-trigger'].right<=l.parts['.mon-latency'].x,'selector cannot cover latency');
   if(l.metrics){const positions=await card.evaluate(c=>({lat:c.querySelector('.mon-latency').getBoundingClientRect().right,metrics:c.querySelector('.mon-metrics').getBoundingClientRect().left}));assert(positions.lat<=positions.metrics,'latency must not cover metrics');}
   assert.equal(l.target,l.c.width-32>=440);assert.equal(l.metrics,l.target);
   if(cardWidth===480||!cardWidth)await shot(cardWidth?'card-480':'overview');
  }
  if(width===1365)for(const columns of [2,3]){await page.locator('.mon-grid').evaluate((el,n)=>el.style.gridTemplateColumns=`repeat(${n},minmax(0,1fr))`,columns);await page.waitForTimeout(240);assert(!(await inspect()).overflow,'same viewport column reflow');}
  await page.locator('.mon-grid').evaluate(el=>el.style.removeProperty('grid-template-columns'));
  await card.locator('.mon-child-trigger').click();await page.getByRole('listbox').waitFor();assert.equal(await page.locator('.mask').count(),0);
  await page.getByRole('option',{name:/关闭端口探测/}).click();await page.waitForTimeout(240);
  assert.equal(await card.locator('.mon-latency').textContent(),'— ms');assert.match(await card.locator('.mon-metrics').textContent(),/100.0%/);
  await card.locator('.mon-child-trigger').focus();await page.keyboard.press('ArrowDown');await page.getByRole('listbox').waitFor();await page.keyboard.press('Escape');assert(await card.locator('.mon-child-trigger').evaluate(el=>el===document.activeElement));
  await card.locator('.mon-heading').click();await page.locator('.mask .mdl').waitFor();assert.match(await page.locator('.mask .mdl').textContent(),/owned.example:8443/);assert.match(await page.locator('.mask .mdl [data-sampling-meta]').textContent(),/60 秒.*5 秒/);assert.match(await page.locator('.mask .mdl [data-monitor-cause]').textContent(),/目标探测失败/);await shot('real-detail');await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'简易',exact:true}).click();assert.equal(await card.locator('.blk').count(),24);
  monitors[0].last_latency_ms=0;await page.reload();await card.waitFor();await page.waitForFunction(()=>document.querySelector('.mon-card .mon-latency')?.textContent==='0.0 ms');
  assert.equal(await card.locator('.mon-child-trigger').getAttribute('title'),monitors[0].name,'production names stay unchanged');
  await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify({passed:true,geometryCases:result.checks.length,screenshots:result.screenshots.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
