// Owned production App, router and shared CSS. No backend, credentials or database.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.STELLA_PICKER_EVIDENCE,dist=process.env.STELLA_APP_DIST;
assert(out&&path.isAbsolute(out)&&dist&&path.isAbsolute(dist));
fs.mkdirSync(out,{recursive:true});assert(!fs.existsSync(path.join(out,'browser-result.json')),'fresh output required');
const bundle=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const server=await preview({configFile:false,envDir:false,root:process.cwd(),build:{outDir:dist},preview:{host:'127.0.0.1',port:0,strictPort:true,proxy:{}}});
const origin=server.resolvedUrls.local[0].replace(/\/$/,'');
const result={kind:'production built actual App/router/shared CSS; synthetic exact HTTP; no backend/PG/Agent',origin,checks:[],observations:[],screenshots:[],unknown:[],errors:[],console:[]};let browser;
try{
 browser=await chromium.launch({headless:true});
 const widths=process.env.STELLA_PICKER_WIDTHS?JSON.parse(process.env.STELLA_PICKER_WIDTHS):[1365,1920,390,320];
 const zooms=process.env.STELLA_PICKER_ZOOMS?JSON.parse(process.env.STELLA_PICKER_ZOOMS):[1,.8,1.25];
 for(const width of widths)for(const zoom of zooms){
  console.log(JSON.stringify({step:'begin',width,zoom}));
  const height=width<500?820:900;
  const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(10000);
  const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
  await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
  page.on('pageerror',e=>result.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')result.console.push(m.text());});
  const now=new Date().toISOString();
  const monitors=Array.from({length:288},(_,i)=>({id:i+1,name:i%12===0?`当前探测 ${i+1}`:`${i+1} 业务端口 · LongUnbrokenMonitorNameForViewportAndClippingABCDEFGHIJKLMNOPQRSTUVWXYZ`,node_id:7,type:'ping',target:'owned.example',interval:60,timeout:5,status:i%3?'up':'down',status_reason:i%3?'healthy':i%12===3?'pending':'dns_error',last_check_at:i%12===3?null:now,last_latency_ms:i%3?2:null,management:null}));
  const groups=Array.from({length:24},(_,i)=>({id:i+1,name:`业务组 ${i+1}`,child_ids:monitors.slice(i*12,(i+1)*12).map(m=>m.id),failure_policy:'any',rotation_seconds:0,status:'down',down_count:4,up_count:8,unknown_count:0}));
  const nodes=[{id:7,name:'探测节点',host:'192.0.2.7',platform:'linux',status:'online',last_seen_at:now,components:{monitoring:{ready:true,types:['ping']}}}];
  const history=id=>{const m=monitors[id-1];return !m?.last_check_at?[]:[{ts:now,success:m.status==='up',latency_ms:m.last_latency_ms,loss_pct:m.status==='up'?0:100,sample_count:1,success_count:m.status==='up'?1:0,latency_count:m.status==='up'?1:0,loss_count:1}];};
  await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin===origin.replace('http:','ws:')&&u.pathname==='/ws/notifications'&&!u.search)return;result.unknown.push('WS '+u.href);ws.close();});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();const json=body=>route.fulfill({json:body});
   if(u.origin!==origin){result.unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
   if(m==='GET'&&!u.search&&(p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
   if(m==='GET'&&p==='/status'&&u.search==='?view=overview')return route.continue();
   const pref=prefs.respond(m,p+u.search,req.postDataJSON());if(pref)return route.fulfill(pref);
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
   if(m==='GET'&&p==='/monitors/')return json(monitors);
   if(m==='GET'&&p==='/monitors/groups')return json(groups);
   if(m==='GET'&&/^\/monitors\/\d+\/series$/.test(p))return json(history(+p.split('/')[2]));
   if(m==='GET'&&/^\/monitors\/\d+\/mtr$/.test(p))return json([]);
   if(m==='GET'&&p==='/alerts/incidents')return json({items:[],total:0,limit:5,offset:0,untracked:[]});
   result.unknown.push(m+' '+p);return route.abort('blockedbyclient');
  });
  const shot=async name=>{await page.mouse.move(width-1,0);const file=path.join(out,`${name}-${width}-z${zoom}.png`);await page.screenshot({path:file});result.screenshots.push(path.basename(file));};
  // Install before mount so every rotation timeout belongs to the same clock.
  await page.clock.install({time:new Date('2026-10-21T00:00:00Z')});
  await page.clock.pauseAt(new Date('2026-10-21T00:00:01Z'));
  await page.goto(origin+'/status?view=overview');await page.locator('.mon-card').first().waitFor();
  await page.evaluate(z=>document.body.style.zoom=String(z),zoom);
  const cards=page.locator('.mon-card'),triggers=page.locator('.mon-child-trigger');
  const ready=async()=>{for(let i=0;i<100;i++){if(await page.evaluate(()=>document.querySelectorAll('.mon-child-trigger').length===24&&document.querySelectorAll('.mon-card').length===24))return;await page.clock.runFor(50);}throw new Error('actual grouped cards did not finish loading');};
  await ready();assert.equal(await cards.count(),24);
  await page.evaluate(()=>document.fonts.ready);await page.clock.runFor(220);

  const columns=await cards.evaluateAll(cards=>{const top=cards[0].getBoundingClientRect().top;return cards.filter(c=>Math.abs(c.getBoundingClientRect().top-top)<2).length;});
  if(width>=1365&&zoom<=1)assert(columns>=2);
  // Exercise the actual API-loaded cadence on the tested groups; unrelated
  // cards remain static so advancing time does not benchmark 24 ECharts trees.
  for(const index of new Set([columns*2,columns*3-1]))groups[index].rotation_seconds=2;
  await page.reload();await ready();await page.evaluate(z=>document.body.style.zoom=String(z),zoom);
  await page.evaluate(()=>document.fonts.ready);await page.clock.runFor(220);
  const positions=[];
  for(const index of [...new Set([columns*2,columns*3-1])])for(const edge of ['top','bottom']){
   console.log(JSON.stringify({step:'position',width,zoom,index,edge}));
   const trigger=triggers.nth(index);
   await trigger.evaluate((el,{edge,height})=>{const pane=document.querySelector('.overview');const scale=pane.getBoundingClientRect().height/pane.offsetHeight;pane.scrollTop+=(el.getBoundingClientRect().top-(edge==='top'?100:height-95))/scale;},{edge,height});
   await page.clock.runFor(30);
   await trigger.click();await page.clock.runFor(220);
   const list=page.getByRole('listbox');await list.waitFor();
   const geometry=await list.evaluate(el=>{const r=el.getBoundingClientRect();return {rect:r.toJSON(),client:el.clientHeight,scroll:el.scrollHeight,hit:[[r.left+12,r.top+12],[r.right-12,r.top+12],[r.left+12,r.bottom-12],[r.right-12,r.bottom-12],[r.left+r.width/2,r.top+25],[r.left+2,r.top+r.height/2],[r.right-2,r.top+r.height/2]].map(([x,y])=>el.contains(document.elementFromPoint(x,y))),withinCard:!!el.closest('.mon-card'),text:el.textContent};});
   const anchor=await trigger.boundingBox();positions.push({index,edge,anchor,...geometry});result.observations.push({width,zoom,index,edge,anchor,...geometry});
   if(zoom===1||index===columns*2&&edge==='bottom')await shot(`menu-${index}-${edge}`);
   assert(geometry.rect.left>=7&&geometry.rect.right<=width-7&&geometry.rect.top>=7&&geometry.rect.bottom<=height-7,JSON.stringify({width,zoom,index,edge,geometry}));
   assert(geometry.hit.every(Boolean),'visible menu must win real elementFromPoint hits');
   assert(!geometry.withinCard,'menu must not remain inside clipping/stacking card');
   if(edge==='bottom')assert(geometry.rect.bottom<=anchor.y+1,'bottom trigger must flip above');
   else assert(geometry.rect.top>=anchor.y+anchor.height-1,'top trigger must open below');
   assert(geometry.scroll>geometry.client,'long menu must scroll');
   assert(geometry.text.includes('正常')&&geometry.text.includes('异常')&&geometry.text.includes('域名解析失败')&&geometry.text.includes('尚未取得探测结果'));
   await page.evaluate(()=>{window.__pickerEvents=[];for(const type of ['scroll','focusout'])document.addEventListener(type,e=>window.__pickerEvents.push({time:Date.now(),type,target:e.target?.className,related:e.relatedTarget?.className}),{capture:true});});
   const before=await trigger.textContent();await page.clock.fastForward(22000);assert.equal(await trigger.getAttribute('aria-expanded'),'true','menu remains open: '+JSON.stringify(await page.evaluate(()=>window.__pickerEvents)));assert.equal(await trigger.textContent(),before,'open menu pauses rotation');
   console.log(JSON.stringify({step:'idle-checked',width,zoom,index,edge}));
   await list.evaluate(el=>el.scrollTop=el.scrollHeight);await page.clock.runFor(30);assert.equal(await list.count(),1,'internal scroll must not close menu');
   const option=list.getByRole('option').last(),chosen=await option.getAttribute('title');await option.click();await page.clock.runFor(220);assert.equal(await page.getByRole('listbox').count(),0);assert((await trigger.textContent()).includes(chosen),'real pointer click must select exact item');assert(await trigger.evaluate(el=>el===document.activeElement));
   assert.equal(await page.locator('.mask').count(),0,'option click must not open card detail');
   await page.clock.fastForward(9779);assert((await trigger.textContent()).includes(chosen));
   await page.clock.fastForward(2100);await page.clock.runFor(220);assert(!(await trigger.textContent()).includes(chosen),'rotation resumes after idle hold');
   console.log(JSON.stringify({step:'rotation-checked',width,zoom,index,edge}));
  }
  // Real keyboard and outside-pointer paths after portal move.
  const trigger=triggers.nth(columns*2);await trigger.click();await page.clock.runFor(220);
  await page.keyboard.press('End');const last=await page.evaluate(()=>document.activeElement?.getAttribute('data-child-id'));
  assert(await page.evaluate(()=>{const item=document.activeElement.getBoundingClientRect(),menu=document.querySelector('.mon-child-menu').getBoundingClientRect();return item.top>=menu.top&&item.bottom<=menu.bottom+1;}),'keyboard focus must be visible inside scrolling list');
  await page.keyboard.press('Home');assert.notEqual(await page.evaluate(()=>document.activeElement?.getAttribute('data-child-id')),last);
  await page.keyboard.press('ArrowUp');assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('data-child-id')),last);await page.keyboard.press('ArrowDown');assert.notEqual(await page.evaluate(()=>document.activeElement?.getAttribute('data-child-id')),last);
  await page.keyboard.press('Escape');await page.clock.runFor(220);assert(await trigger.evaluate(el=>el===document.activeElement));
  await trigger.click();await page.keyboard.press('Tab');await page.clock.runFor(220);assert.equal(await page.getByRole('listbox').count(),0);assert(await page.evaluate(()=>document.activeElement?.tagName==='BUTTON'&&!document.activeElement.closest('.mon-child-menu')));
  await trigger.click();await page.keyboard.press('Shift+Tab');await page.clock.runFor(220);assert(await trigger.evaluate(el=>el===document.activeElement));
  await trigger.click();await page.mouse.click(width-2,height-2);await page.clock.runFor(220);assert.equal(await page.getByRole('listbox').count(),0);assert(await trigger.evaluate(el=>el===document.activeElement));
  await trigger.click();await page.locator('.overview').evaluate(el=>el.scrollTop+=20);await page.clock.runFor(220);assert.equal(await page.getByRole('listbox').count(),0,'ancestor scroll closes detached list');
  // Resize an open menu and validate its new physical viewport boundary.
  await trigger.click();await page.setViewportSize({width:width-20,height:height-50});await page.clock.runFor(250);
  const resizeClosedOnScroll=await trigger.getAttribute('aria-expanded')==='false';
  // A responsive reflow may scroll the real overview ancestor: that preserves
  // the existing close-on-scroll contract rather than leaving a stale portal.
  if(resizeClosedOnScroll){assert.equal(await page.getByRole('listbox').count(),0);await trigger.scrollIntoViewIfNeeded();await page.clock.runFor(220);await trigger.click();await page.clock.runFor(220);}
  const resized=await page.getByRole('listbox').boundingBox();assert(resized&&resized.x>=7&&resized.x+resized.width<=width-27&&resized.y>=7&&resized.y+resized.height<=height-57);
  await page.keyboard.press('Escape');
  result.checks.push({width,zoom,columns,positions,keyboard:true,realClick:true,idleRotation:true,ancestorScroll:true,resize:true,resizeClosedOnScroll});console.log(JSON.stringify({width,zoom,positions:positions.length,passed:true}));await context.close();
 }
 assert.deepEqual(result.unknown,[]);assert.deepEqual(result.errors,[]);assert.deepEqual(result.console,[]);result.passed=true;
 console.log(JSON.stringify({passed:true,scenarios:result.checks.length,screenshots:result.screenshots.length}));
}catch(e){result.failure={message:e.message,stack:e.stack};throw e;}finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();await new Promise(resolve=>server.httpServer.close(resolve));}
