// Actual production-built App/router. All auth, node and monitoring HTTP is synthetic.
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
const server=await preview({configFile:false,envDir:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'actual production-built App + synthetic HTTP; not live Agent or PG acceptance',checks:[],screenshots:[],writes:[],errors:[],console:[],unknown:[],boundaryProbes:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 for(const width of [1365,1920,320,390,746]){
  const context=await browser.newContext({viewport:{width,height:width<500?900:1080},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(12000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));
  page.on('console',m=>result.console.push({width,type:m.type(),text:m.text()}));
  const now=new Date().toISOString(),long='独立测试样本 · 同目标双节点多类型-LongUnbrokenMonitorGroupNameForOverflow';
  const monitor=(id,name,status,reason)=>({id,name,node_id:id===11?8:id===12?9:7,type:'ping',target:id===13?'other.example':'main.example',interval:60,timeout:1,status,status_reason:reason,last_check_at:status==='unknown'?null:now,last_latency_ms:status==='up'?1.2:null,management:'entry_icmp'});
  const monitors=[monitor(10,'节点A → 默认入口','up','healthy'),monitor(11,'节点B → 默认入口','down','failure'),monitor(12,'节点C → 默认入口','unknown','dns_error'),monitor(13,'节点A → 内网入口','unknown','pending')];
  const groups=[{id:4,name:long,child_ids:[10,11,12],failure_policy:'any',rotation_seconds:0,status:'down',down_count:1,unknown_count:1,up_count:1,automatic:true},{id:5,name:'内网入口探测',child_ids:[13],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:1,up_count:0,automatic:true},{id:6,name:'EMPTY must be hidden',child_ids:[],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:0}];
  const nodes=[7,8,9].map((id,i)=>({id,name:'节点'+['A','B','C'][i],host:'192.0.2.'+id,platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['ping']}}}));
  // Honest per-monitor history: pending/DNS-without-a-prior-sample have none.
  // The down item's newest sample is a real failure, not another success.
  const history=id=>id!==10&&id!==11?[]:Array.from({length:12},(_,i)=>({ts:new Date(Date.parse(now)-(11-i)*60000).toISOString(),success:id===10||i<11,latency_ms:id===11&&i===11?null:1+(i%4)*0.2,loss_pct:id===11&&i===11?100:0,sample_count:1,success_count:id===11&&i===11?0:1,latency_count:id===11&&i===11?0:1,loss_count:1}));
  let nextId=20,newPosts=0,failRead=false,unknownPost=false,receipt=null,probing=false;
  const rejects=[];const reject=tag=>probing?rejects.push(tag):result.unknown.push(tag);
  await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications'&&!u.search)return;reject('WS '+u.pathname+u.search);ws.close();});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),b=req.postDataJSON();const json=(body,status=200)=>route.fulfill({status,...(status===204?{body:''}:{json:body})});
   if(u.origin!==origin){reject(m+' '+req.url());return route.abort('blockedbyclient');}
   if(m==='GET'&&(req.isNavigationRequest()||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
   const pref=prefs.respond(m,p+u.search,b);if(pref)return route.fulfill(pref);
   if(u.search&&!(m==='GET'&&((/^\/monitors\/\d+\/series$/.test(p)&&[...u.searchParams.keys()].every(k=>['start','end','step','limit'].includes(k)))||(p==='/alerts/incidents'&&u.search==='?limit=5&offset=0&status=unresolved')))){reject(m+' '+p+u.search);return route.abort('blockedbyclient');}
   if(m==='GET'&&p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
   if(m==='GET'&&p==='/maps/world.geo.json')return json({type:'FeatureCollection',features:[{type:'Feature',properties:{name:'bounded geometry'},geometry:{type:'Polygon',coordinates:[[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]]]}}]});
   if(m==='GET'&&p==='/auth/me')return json({id:'fixture-owner',username:'fixture',display_name:'隔离监控用户',email:'fixture@example.test',email_verified:true,is_admin:false,home_bg:'',avatar_url:''});
   if(m==='GET'&&p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
   if(m==='GET'&&p==='/auth/security')return json({enabled:true,configured:true,elevated:true,expires_at:null,single_user:true,setup_required:false});
   if(m==='POST'&&p==='/auth/activity')return json({ok:true});
   if(m==='GET'&&p==='/navigation')return json({entries:[{id:'home',title:'首页'},{id:'settings',title:'设置'},{id:'status',title:'服务器'}],legacy_routes:{}});
   if(m==='GET'&&p==='/notifications/unread-count')return json({count:0});
   if(m==='GET'&&p==='/external-modules')return json([]);
   if(m==='GET'&&p==='/nodes/host')return json({installed:true});
   if(m==='GET'&&p==='/nodes/')return json(nodes);
   if(m==='GET'&&/^\/nodes\/(7|8|9)$/.test(p))return json({...nodes.find(n=>n.id===+p.split('/')[2]),latest_metrics:[],latest_sys_metric:null});
   if(m==='GET'&&p==='/nodes/map-topology')return json({generated_at:now,nodes:[],links:[],stats:{located:0,unknown:0,links:0}});
   if(m==='GET'&&p==='/monitors/')return json(monitors);
   if(m==='GET'&&p==='/monitors/groups')return failRead?json({detail:'Synthetic readback forbidden'},403):json(groups);
   if(m==='GET'&&/^\/monitors\/\d+\/series$/.test(p))return json(history(+p.split('/')[2]));
   if(m==='GET'&&/^\/monitors\/\d+\/mtr$/.test(p))return json([]);
   if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
   if(m==='GET'&&p.startsWith('/monitors/groups/receipts/'))return receipt?json(receipt):json({detail:'inconclusive'},404);
   if(m==='POST'&&p==='/monitors/groups'){
    newPosts++;assert(!('child_ids' in b)&&b.items.length>=1);const ids=[];
    for(const item of b.items){const mid=nextId++;ids.push(mid);monitors.push({...item,id:mid,status:'unknown',status_reason:'pending',last_check_at:null,last_latency_ms:null});}
    const group={id:8+newPosts,name:b.name,child_ids:ids,failure_policy:b.failure_policy,rotation_seconds:b.rotation_seconds,status:'unknown',down_count:0,up_count:0,unknown_count:ids.length};groups.push(group);receipt={group_id:group.id,monitor_ids:ids};result.writes.push({width,m,p,b});failRead=true;if(unknownPost)return route.abort('failed');return json(group,201);
   }
   if(m==='POST'&&p==='/monitors/groups/4/children'){
    const child={...b,id:nextId++,status:'unknown',status_reason:'pending',last_check_at:null,last_latency_ms:null};monitors.push(child);groups[0].child_ids.push(child.id);result.writes.push({width,m,p,b});return json(child,201);
   }
   if(m==='PATCH'&&/^\/monitors\/\d+$/.test(p)){const item=monitors.find(item=>item.id===+p.split('/').at(-1));Object.assign(item,b);result.writes.push({width,m,p,b});return json(item);}
   if(m==='DELETE'&&/^\/monitors\/\d+$/.test(p)){const mid=+p.split('/').at(-1);monitors.splice(monitors.findIndex(item=>item.id===mid),1);groups.forEach(g=>g.child_ids=g.child_ids.filter(id=>id!==mid));result.writes.push({width,m,p});return json(null,204);}
   if(m==='PUT'&&p==='/monitors/groups/4'){Object.assign(groups[0],b);result.writes.push({width,m,p,b});return json(groups[0]);}
   reject(m+' '+p);return route.abort('blockedbyclient');
  });
  const shot=async name=>{const file=path.join(out,`${name}-${width}.png`);await page.screenshot({path:file});result.screenshots.push(file);};
  await page.goto(origin+'/status?view=overview#service-monitors');await page.getByText(long,{exact:true}).waitFor();await page.locator('#service-monitors').scrollIntoViewIfNeeded();await page.mouse.move(0,0);
  probing=true;const boundary=await page.evaluate(async()=>{const denied=[];for(const [url,method] of [['/monitors/groups','HEAD'],['/monitors/groups?unexpected=1','GET']]){try{await fetch(url,{method});denied.push(false);}catch{denied.push(true);}}denied.push(await new Promise(resolve=>{const ws=new WebSocket(location.origin.replace('http:','ws:')+'/ws/unknown-fixture');ws.onclose=()=>resolve(true);ws.onerror=()=>resolve(false);}));return denied;});probing=false;assert.deepEqual(boundary,[true,true,true]);assert.equal(rejects.length,3);result.boundaryProbes.push({width,rejects});
  assert.equal(await page.locator('.mon-card').count(),2);assert.equal(await page.getByText('EMPTY must be hidden').count(),0);
  const layout=await page.locator('.mon-card').evaluateAll(cards=>cards.map(card=>{const r=card.getBoundingClientRect(),pane=card.closest('.overview').getBoundingClientRect(),head=card.querySelector('.mon-heading'),title=head.querySelector('.mon-name').getBoundingClientRect(),counts=head.querySelector('.mon-counts').getBoundingClientRect(),action=head.querySelector('button').getBoundingClientRect();return {left:r.left,right:r.right,paneLeft:pane.left,paneRight:pane.right,scroll:card.scrollWidth,client:card.clientWidth,title:title.toJSON(),counts:counts.toJSON(),action:action.toJSON(),actions:head.querySelectorAll('button').length,within:[...card.querySelectorAll('.mon-name,.mon-counts,button,.mon-target')].every(el=>{const e=el.getBoundingClientRect();return e.left>=r.left&&e.right<=r.right;})};}));
  assert(layout.every(c=>c.left>=c.paneLeft&&c.right<=c.paneRight&&c.scroll<=c.client+1&&c.actions===1&&c.within),JSON.stringify(layout));
  assert(layout.every(c=>width<=600?c.counts.top>=c.title.bottom-1:Math.abs(c.title.top-c.counts.top)<10),JSON.stringify(layout));
  const pendingCard=page.locator('.mon-card').nth(1);
  await pendingCard.getByText('待首次检测',{exact:true}).waitFor();
  await pendingCard.getByText('可用率 暂无数据',{exact:true}).waitFor();
  // Wait for populated positive control too, so this cannot pass before loading.
  await page.locator('.mon-card').first().getByText('可用率 100.0%',{exact:true}).waitFor();
  assert.equal(await pendingCard.locator('.mon-loss').count(),0);
  assert.equal(await pendingCard.locator('.spark canvas,.spark svg').count(),0);
  assert((await pendingCard.locator('.mon-current').textContent()).includes('当前 —'));
  await shot('overview');const card=page.locator('.mon-card').first();assert((await card.locator('.mon-counts').textContent()).includes('异常 1正常 1'));
  await card.locator('.mon-child-trigger').click();await page.getByRole('option').filter({hasText:'节点C → 默认入口'}).click();await card.getByText('域名解析失败',{exact:true}).waitFor();assert.equal(await card.getByText('未知',{exact:true}).count(),0);await shot('dns-failure');
  await card.locator('.mon-heading button').click();await page.getByRole('heading',{name:'监控组设置'}).waitFor();const listBounds=await page.locator('.group-dialog .child-row').last().evaluate(el=>{const list=el.closest('fieldset').getBoundingClientRect(),buttons=[...el.querySelectorAll('button')].map(b=>b.getBoundingClientRect());return buttons.every(b=>b.bottom<=list.bottom&&b.top>=list.top);});assert(listBounds,'ordinary three-item settings must not crop its final edit/delete actions in a nested scrollbox');await shot('group-settings');assert.equal(await page.locator('.group-dialog input[type=checkbox]').count(),0);assert.equal(await page.getByText('节点A → 内网入口',{exact:true}).count(),1);assert.equal(await page.locator('.group-dialog').getByText('节点A → 内网入口',{exact:true}).count(),0);
  await page.getByRole('button',{name:'新建监控项',exact:true}).click();await page.getByLabel('监控项名称',{exact:true}).fill('附加 TCP');await page.getByLabel('监控项目标',{exact:true}).fill('owned.example:443');await page.getByRole('button',{name:'创建并加入',exact:true}).click();await page.getByRole('button',{name:'编辑监控项 附加 TCP',exact:true}).click();await page.locator('.edit-body input').first().fill('改名 TCP');await shot('item-edit');await page.locator('.edit-body').getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('button',{name:'永久删除监控项 改名 TCP',exact:true}).click();await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await page.getByRole('button',{name:'永久删除监控项 改名 TCP',exact:true}).waitFor({state:'detached'});await page.getByRole('button',{name:'关闭监控组设置',exact:true}).click();
  await page.getByRole('button',{name:'添加监控',exact:true}).click();await page.getByLabel('监控组名称',{exact:true}).fill('全新业务探测');await page.getByLabel('监控项名称 1',{exact:true}).fill('新监控项');await page.getByLabel('监控项目标 1',{exact:true}).fill('new.example:443');if(width===1365){await page.getByRole('button',{name:'添加监控项',exact:true}).click();await page.getByLabel('监控项名称 2',{exact:true}).fill('第二个新监控项');await page.getByLabel('监控项目标 2',{exact:true}).fill('new.example:8443');}
  assert.equal(await page.locator('.group-dialog input[type=checkbox]').count(),0);assert(!(await page.locator('.group-dialog').textContent()).includes('编辑对象'));assert.equal(await page.locator('.group-dialog .child-row').count(),0);
  await page.locator('.group-dialog').evaluate(el=>el.scrollTop=0);await shot('new-dialog');
  await page.getByRole('button',{name:'创建监控',exact:true}).click();await page.locator('.group-dialog [role=alert]').waitFor();await shot('unconfirmed-create');const retry=page.getByRole('button',{name:'重新确认创建结果',exact:true});await retry.click();assert.equal(newPosts,1);await page.keyboard.press('Escape');assert.equal(await page.locator('.group-dialog').count(),1);
  if(width===1365){
   await page.locator('a[href="/"]').first().evaluate(el=>el.click());await page.waitForTimeout(30);assert.equal(new URL(page.url()).pathname,'/status');
   await page.locator('.servers-bar button').filter({hasText:/^服务器$/}).evaluate(el=>el.click());await page.waitForTimeout(30);assert.equal(new URL(page.url()).search,'?view=overview');
   let prompted=false;page.once('dialog',async dialog=>{assert.equal(dialog.type(),'beforeunload');prompted=true;await dialog.dismiss();});
   await page.reload({waitUntil:'domcontentloaded',timeout:3000}).catch(()=>null);assert(prompted,'native beforeunload must be observed');assert.equal(await page.getByLabel('监控组名称',{exact:true}).inputValue(),'全新业务探测');assert.equal(newPosts,1);
  }
  failRead=false;await retry.click();await page.locator('.group-dialog').waitFor({state:'detached'});assert.equal(newPosts,1);
  if(width===390){unknownPost=true;await page.getByRole('button',{name:'添加监控',exact:true}).click();await page.getByLabel('监控组名称',{exact:true}).fill('响应丢失收据');await page.getByLabel('监控项名称 1',{exact:true}).fill('不能重复');await page.getByLabel('监控项目标 1',{exact:true}).fill('receipt.example:443');await page.getByRole('button',{name:'创建监控',exact:true}).click();await page.locator('.group-dialog [role=alert]').waitFor();failRead=false;await page.getByRole('button',{name:'重新确认创建结果',exact:true}).click();await page.locator('.group-dialog').waitFor({state:'detached'});assert.equal(newPosts,2);}
  result.checks.push({width,layout,pendingHasNoHistoryMetricsOrCurve:true,scopedSettings:true,childCRUD:true,atomicNewGroup:true,committed403GetOnly:true,unknownReceipt:width===390});await context.close();
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.unknown,[]);result.passed=true;console.log(JSON.stringify({passed:true,widths:result.checks.map(c=>c.width),screenshots:result.screenshots.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
