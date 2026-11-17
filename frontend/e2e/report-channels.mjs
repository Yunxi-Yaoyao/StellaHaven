// Built App + real router, isolated static server. No backend/proxy/fleet traffic.
import http from 'node:http';
import {readFile,stat,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const root=path.resolve(process.env.STELLA_APP_DIST||'dist'),out=process.env.STELLA_QA_OUTPUT;
assert(out);await mkdir(out,{recursive:true});
const source=await readFile(path.resolve('../agent/stella_agent.py'));
const manifest={version:source.toString('utf8').match(/^AGENT_VERSION\s*=\s*"([^"]+)"/m)[1],sha256:createHash('sha256').update(source).digest('hex'),size:source.length};
let announcement=manifest;const announcementChecks=[];
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.svg':'image/svg+xml','.png':'image/png'};
const unknown=[],errors=[],consoleMessages=[],requests=[],geometry=[],writes=[],blockedQueries=[],blockedWebSockets=[],blockedMethods=[];
let methodProbe=false;
const server=http.createServer(async(req,res)=>{
 let file=path.resolve(root,'.'+new URL(req.url,'http://fixture').pathname);
 if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
 try{if(!(await stat(file)).isFile())throw new Error();}catch{file=path.join(root,'index.html');}
 res.setHeader('Content-Type',types[path.extname(file)]??'application/octet-stream');res.end(await readFile(file));
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
const stamp=new Date().toISOString();
const names=['香港服务器','洛杉矶服务器','测试节点—长名称abcdefghijklmnopabcdefghijklmnop'];
let channel={revision:0,default_entry_id:'public',entries:[{entry_id:'public',origin:'https://stella.example.test'},{entry_id:'private',origin:'https://stella-private-registered-entry-west.example.test'}],nodes:names.map((name,i)=>({node_id:i+1,name,mode:i===1?'auto':'default',entry_id:null,revision:0,state:i===1?'applied':'pending',actual_origin:i===1?'https://stella-private-registered-entry-west.example.test':null,http_ms:null,sampled_at:null,error:null,online:i!==0}))};
let fail=false,readFailure=0,nextReadFailure=0,refreshRejections=0,logins=0;
let sourceFailure=0;
let loginAsOther=false;
let me={id:'fixture-owner',username:'fixture',display_name:'云曦',is_admin:false,email:'',email_verified:false,avatar_url:null,home_bg:null};
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-background-networking']});
try{
 const context=await browser.newContext({serviceWorkers:'block',hasTouch:true});
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!==base.replace('http:','ws:')||u.pathname!=='/ws/notifications'||u.search)unknown.push('WS '+ws.url());blockedWebSockets.push(ws.url());ws.close();});
 await context.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url()),p=u.pathname.replace(/\/$/,'');
  requests.push([r.method(),p]);
  if(u.origin!==base){unknown.push(r.url());return route.abort();}
  if(r.method()!=='GET'&&!(r.method()==='POST'&&['/auth/activity','/auth/refresh','/auth/login'].includes(p))&&!(r.method()==='PUT'&&p==='/nodes/report-channels')){const tag=r.method()+' '+p;if(methodProbe)blockedMethods.push(tag);else unknown.push(tag);return route.fulfill({status:501,body:''});}
  if(u.search && !(p==='/status' && u.search==='?view=nodes')){blockedQueries.push(p+u.search);return route.fulfill({status:501,json:{detail:'Unsupported fixture query'}});}
  let data;
  if(p==='/auth/me'&&r.method()==='GET')data=me;
  else if(p==='/auth/refresh'&&r.method()==='POST'&&readFailure===401){refreshRejections++;return route.fulfill({status:401,json:{detail:'Synthetic expired session'}});}
  else if(p==='/auth/login'&&r.method()==='POST'){logins++;readFailure=0;if(loginAsOther)me={...me,id:'fixture-owner-b'};data=me;}
  else if(p==='/auth/status')data={initialized:true,registration_open:false,email_enabled:false};
  else if(p==='/navigation')data={entries:[],legacy_routes:{}};
  else if(p==='/external-modules')data=[];
  else if(p==='/notifications/unread-count')data={count:0};
  else if(p==='/agent/version')data=announcement;
  else if(p==='/agent/script')return sourceFailure?route.fulfill({status:sourceFailure,json:{detail:'source unavailable'}}):route.fulfill({contentType:'text/plain;charset=utf-8',body:source});
  else if(p==='/nodes')data=names.map((name,i)=>({id:i+1,name,platform:'linux',host:'192.0.2.'+(i+1),status:i?'online':'offline',agent_version:i?'0.6.1':manifest.version,last_seen_at:i?stamp:null,interfaces:{},created_at:stamp,installed:true,net_type:'public'}));
  else if(p==='/nodes/host')data={local_install_supported:false,installed:false,node_id:null};
  else if(p==='/nodes/report-channels'){
   assert(['GET','PUT'].includes(r.method()),'unexpected channel method');
   if(r.method()==='GET'&&readFailure)return route.fulfill({status:readFailure,json:{detail:'Synthetic readback unavailable'}});
   if(r.method()==='PUT'){
    const v=r.postDataJSON();writes.push(v);
    if(fail)return route.fulfill({status:409,json:{detail:'fixture CAS conflict'}});
    assert.deepEqual(v.node_ids,[1]);assert(['auto','default'].includes(v.mode));assert.equal(v.entry_id,null);
    channel={...channel,revision:channel.revision+1,nodes:channel.nodes.map(n=>v.node_ids.includes(n.node_id)?{...n,mode:v.mode,revision:channel.revision+1,state:'pending'}:n)};
    readFailure=nextReadFailure;nextReadFailure=0;
   }
   data=channel;
  }
  else if(p==='/config/public-host')data={value:'https://stella.example.test'};
  else if(p==='/component-installs')data=[];
  else if(p==='/auth/activity')data={ok:true};
  else if(p==='/operations/backups/client-preferences')return route.fulfill({status:404,json:{detail:'No saved fixture preferences'}});
  else if(p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"></svg>'});
  else if(p==='/config/client-preferences')data={revision:0,appearance:{},live2d:{enabled:false}};
  else if(p==='/config/site-background')data={url:null};
  if(data!==undefined)return route.fulfill({json:data});
  if(r.resourceType()==='document' || (['script','stylesheet','font','image'].includes(r.resourceType())&&p.startsWith('/static/')))return route.continue();
  unknown.push(r.method()+' '+p);return route.fulfill({status:501,json:{detail:'Unknown fixture route'}});
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>consoleMessages.push({type:m.type(),text:m.text()}));
 await page.goto(base+'/status?view=nodes');await page.getByRole('button',{name:'Agent 管理',exact:true}).waitFor();
 await page.getByRole('button',{name:'Agent 管理',exact:true}).click();
 await page.locator('.agent-dialog .version').waitFor();assert((await page.locator('.agent-dialog').textContent()).includes(manifest.sha256));
 assert.equal(requests.filter(r=>r[1]==='/agent/script').length,0);
 assert.equal((await page.locator('.node-picker .dd-label').textContent()).trim(),names[0],'new user defaults to first actual node');
 await page.locator('.node-picker .dd-btn').focus();await page.keyboard.press('ArrowDown');
 assert.equal(await page.getByRole('option',{name:names[0],exact:true}).getAttribute('aria-selected'),'true');
 await page.keyboard.press('Escape');assert(await page.locator('.node-picker .dd-btn').evaluate(el=>el===document.activeElement));assert.equal(await page.locator('dialog[open]').count(),1);
 await page.keyboard.press('ArrowDown');await page.keyboard.press('Tab');assert.equal(await page.locator('.node-picker .dd-btn').getAttribute('aria-expanded'),'false');
 await page.keyboard.press('Tab');assert(await page.locator('.agent-dialog').evaluate(el=>el.contains(document.activeElement)));
 await page.locator('.agent-dialog').getByRole('button',{name:'总览',exact:true}).focus();await page.keyboard.press('Escape');assert(await page.getByRole('button',{name:'Agent 管理',exact:true}).evaluate(el=>el===document.activeElement));await page.getByRole('button',{name:'Agent 管理',exact:true}).click();assert.equal(requests.filter(r=>r[1]==='/agent/version').length,1);
 for(const width of [1200,1365,1920,390,320]){
  await page.setViewportSize({width,height:900});await page.mouse.move(0,0);await page.waitForTimeout(180);
  const picker=page.locator('.node-picker .dd-btn');
  await picker.click();await page.keyboard.press('End');await page.keyboard.press('Enter');
  assert(await picker.evaluate(el=>el===document.activeElement),'selection restores picker focus');
  assert.equal(await picker.getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('.node-picker select').count(),0);
  assert((await page.locator('.agent-dialog dl').last().textContent()).includes(names[2]));
  assert((await page.locator('.comparison').textContent()).includes('不同'));
  await page.screenshot({path:path.join(out,`agent-overview-${width}.png`)});
  await picker.click();await page.getByRole('option',{name:names[2],exact:true}).scrollIntoViewIfNeeded();
  const pg=await page.getByRole('option',{name:names[2],exact:true}).boundingBox();const dg=await page.locator('.agent-dialog').boundingBox();assert(pg.x>=dg.x&&pg.x+pg.width<=dg.x+dg.width,'long option inside dialog');
  if(width<=390){assert((await picker.boundingBox()).height>=44);assert(pg.height>=44);}
  await page.mouse.move(0,0);await page.waitForTimeout(180);await page.screenshot({path:path.join(out,`agent-node-dropdown-${width}.png`)});
  await page.keyboard.press('Escape');assert.equal(await picker.getAttribute('aria-expanded'),'false');
  assert(await picker.evaluate(el=>el===document.activeElement));
  await page.locator('.agent-dialog').evaluate(el=>el.scrollTop=0);
 }
 await page.getByRole('button',{name:'源码',exact:true}).click();assert.equal(requests.filter(r=>r[1]==='/agent/script').length,0);
 sourceFailure=503;await page.getByRole('button',{name:'查看源码',exact:true}).click();await page.getByRole('alert').filter({hasText:'读取失败'}).waitFor();
 const failedSourceReads=requests.filter(r=>r[1]==='/agent/script').length;
 await page.getByRole('button',{name:'总览',exact:true}).click();await page.getByRole('button',{name:'源码',exact:true}).click();assert.equal(requests.filter(r=>r[1]==='/agent/script').length,failedSourceReads);
 sourceFailure=0;await page.getByRole('button',{name:'重试读取',exact:true}).click();await page.locator('pre[aria-label="只读 Agent 源码"]').waitFor();
 assert.equal(await page.locator('pre code').textContent(),source.toString('utf8'));assert((await page.locator('.source-check').textContent()).includes('与发行公告一致'));
 // The backend's supported parked rollout deliberately omits a source manifest.
 announcement={version:'0.6.17'};await page.getByRole('button',{name:'总览',exact:true}).click();await page.getByRole('button',{name:'刷新发行',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.agent-dialog .version')?.textContent==='0.6.17');await page.getByRole('button',{name:'源码',exact:true}).click();assert((await page.locator('.source-check').textContent()).includes('发行公告未提供校验信息'));assert.equal(await page.locator('pre code').textContent(),source.toString('utf8'));announcementChecks.push({kind:'parked',announcement,actual:manifest,notClaimedMatching:true});await page.screenshot({path:path.join(out,'agent-parked-announcement.png')});
 announcement={...manifest,version:'0.6.17'};await page.getByRole('button',{name:'总览',exact:true}).click();await page.getByRole('button',{name:'刷新发行',exact:true}).click();await page.waitForFunction(h=>document.querySelector('.agent-dialog dl .hash')?.textContent===h,manifest.sha256);await page.getByRole('button',{name:'源码',exact:true}).click();assert((await page.locator('.source-check').textContent()).includes('与发行公告不一致'));announcementChecks.push({kind:'synthetic-wrong-version-even-with-same-hash',notClaimedMatching:true});await page.screenshot({path:path.join(out,'agent-wrong-version-negative.png')});
 announcement=manifest;await page.getByRole('button',{name:'总览',exact:true}).click();await page.getByRole('button',{name:'刷新发行',exact:true}).click();await page.waitForFunction(v=>document.querySelector('.agent-dialog .version')?.textContent===v,manifest.version);await page.getByRole('button',{name:'源码',exact:true}).click();assert((await page.locator('.source-check').textContent()).includes('与发行公告一致'));
 assert.equal(await page.getByRole('tooltip').count(),0);await page.getByRole('button',{name:'查看源码说明',exact:true}).click();await page.getByRole('tooltip').waitFor();assert((await page.getByRole('tooltip').textContent()).includes('仅查看，不执行'));assert(await page.getByRole('tooltip').evaluate(el=>!!el.closest('dialog')));
 await page.getByRole('button',{name:'重新读取',exact:true}).focus();await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),1,'first Escape dismisses help, not management');
 await context.grantPermissions(['clipboard-read','clipboard-write'],{origin:base});await page.getByRole('button',{name:'复制源码',exact:true}).click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),source.toString('utf8'));
 const downloading=page.waitForEvent('download');await page.getByRole('link',{name:'下载源码',exact:true}).click();const downloaded=await downloading;assert.equal(downloaded.suggestedFilename(),'stella_agent.py');assert.deepEqual(await readFile(await downloaded.path()),source);
 for(const width of [1200,1365,1920,390,320]){
  await page.setViewportSize({width,height:900});await page.mouse.move(0,0);await page.waitForTimeout(180);
  const g=await page.locator('pre').evaluate(el=>{const p=el.closest('dialog'),r=el.getBoundingClientRect(),b=p.getBoundingClientRect();return {left:r.left,right:r.right,parentLeft:b.left,parentRight:b.right,scroll:el.scrollHeight,client:el.clientHeight,outerScroll:p.scrollWidth,outerClient:p.clientWidth};});
  assert(g.left>=g.parentLeft&&g.right<=g.parentRight&&g.scroll>g.client&&g.outerScroll<=g.outerClient+1);geometry.push({sourceWidth:width,...g});
  if(width<=390){assert(g.outerScroll<=g.outerClient+1);const codeTop=(await page.locator('pre').boundingBox()).y;assert(codeTop<540,'compact source puts code in view without scrolling at 900h');}
  await page.screenshot({path:path.join(out,`agent-source-${width}.png`)});
  await page.locator('.source-hash summary').click();assert.equal(await page.locator('.source-hash code').textContent(),manifest.sha256);await page.getByRole('button',{name:'复制校验值',exact:true}).click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),manifest.sha256);
  await page.screenshot({path:path.join(out,`agent-source-hash-${width}.png`)});await page.locator('.source-hash summary').click();
 }
 await page.locator('pre').hover();await page.mouse.wheel(0,600);await page.waitForTimeout(100);assert(await page.locator('pre').evaluate(el=>el.scrollTop>0));
 await page.setViewportSize({width:390,height:500});await page.locator('.agent-dialog').evaluate(el=>el.scrollTop=el.scrollHeight);await page.waitForTimeout(100);
 const closeRect=await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).boundingBox();assert(closeRect.y>=0&&closeRect.y+closeRect.height<=500,'short-height close must remain reachable');
 await page.screenshot({path:path.join(out,'agent-source-short-height.png')});
 await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).click();await page.getByRole('button',{name:'Agent 管理',exact:true}).click();assert.equal(requests.filter(r=>r[1]==='/agent/script').length,failedSourceReads+1);
 await page.setViewportSize({width:1365,height:900});
 await page.getByRole('button',{name:'上报通道',exact:true}).click();await page.locator('.channel-row').first().waitFor();
 await page.getByRole('button',{name:'批量设置',exact:true}).click();
 assert.equal(await page.locator('dialog[open]').count(),1);
 for(const width of [1200,1365,1920,320,390]){
  await page.setViewportSize({width,height:900});await page.mouse.move(0,0);
  await page.waitForTimeout(180);
  const g=await page.locator('.agent-dialog').evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,client:el.clientWidth,scroll:el.scrollWidth,viewport:innerWidth};});
  geometry.push({width,...g});assert(g.left>=0&&g.right<=width+1&&g.scroll<=g.client+1,JSON.stringify(g));
  if(width>700){const columns=await page.locator('.column-head').evaluate(el=>({head:[...el.children].map(c=>c.getBoundingClientRect().x),rows:[...el.parentElement.querySelectorAll('.channel-row')].map(r=>[...r.children].slice(0,5).map(c=>c.getBoundingClientRect().x))}));for(const row of columns.rows)row.forEach((x,i)=>assert(Math.abs(x-columns.head[i])<1,'header and every row share column tracks'));geometry.push({width,columns});}
  else{const label=page.locator('.node-check').first(),box=await label.boundingBox();assert(box.width>=44&&box.height>=44,'actual independent checkbox label must be 44px');const check=page.getByRole('checkbox',{name:'选择 香港服务器',exact:true});await page.touchscreen.tap(box.x+2,box.y+2);assert(await check.isChecked(),'edge of actual label toggles checkbox');await page.locator('.node-name').first().click();assert(await check.isChecked(),'name opens detail without toggling selection');assert.equal(await page.locator('.row-detail').count(),1);await page.locator('.node-name').first().click();await label.click({position:{x:2,y:2}});assert(!await check.isChecked());for(const selector of ['.node-name','.origin .name-button','.header-buttons button','.row-edit']){for(const b of await page.locator(selector).all())assert((await b.boundingBox()).height>=44,selector+' touch height');}geometry.push({width,label:box});}
  await page.screenshot({path:path.join(out,`channels-${width}.png`)});
 }
 await page.setViewportSize({width:320,height:500});await page.locator('.channel-row').first().hover();await page.mouse.wheel(0,850);await page.waitForTimeout(180);assert(await page.locator('.agent-dialog').evaluate(el=>el.scrollTop>0));const channelClose=await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).boundingBox();assert(channelClose.y>=0&&channelClose.y+channelClose.height<=500);await page.screenshot({path:path.join(out,'channels-short-height-320.png')});await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).click();await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.setViewportSize({width:390,height:900});await page.locator('.agent-dialog').evaluate(el=>el.scrollTop=0);
 await page.locator('.node-name').nth(2).click();
 assert((await page.getByRole('region').last().textContent()).includes(names[2]));
 await page.screenshot({path:path.join(out,'channels-long-name-390.png')});
 await page.getByRole('button',{name:'查看 洛杉矶服务器 实际入口',exact:true}).click();
 assert((await page.getByRole('region').last().textContent()).includes(channel.nodes[1].actual_origin));
 await page.screenshot({path:path.join(out,'channels-full-origin-390.png')});
 await page.getByRole('button',{name:'查看 洛杉矶服务器 实际入口',exact:true}).click();
 await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).check();
 await page.getByRole('button',{name:'取消选择',exact:true}).click();
 assert.equal(writes.length,0);assert(!await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).isChecked());
 await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).check();
 await page.locator('.selector button.dd-btn').click();await page.mouse.move(0,0);await page.waitForTimeout(180);await page.screenshot({path:path.join(out,'channels-dropdown-390.png')});await page.getByRole('option',{name:'自动选择',exact:true}).click();
 await page.getByRole('button',{name:'应用到所选',exact:true}).click();await page.getByRole('status').filter({hasText:'策略已保存'}).waitFor();
 assert.equal(writes.length,1);assert.equal(channel.nodes[1].mode,'auto');
 assert((await page.locator('.channel-row').first().textContent()).includes('离线 · 待应用'));
 for(const status of [503,401]){
  await page.locator('.selector button.dd-btn').click();
  await page.getByRole('option',{name:status===503?'默认入口':'自动选择',exact:true}).click();
  nextReadFailure=status;
  const count=writes.length;
  await page.getByRole('button',{name:'应用到所选',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.channel-dialog .error')?.textContent?.includes('状态读取失败'));
  assert.equal(writes.length,count+1);
  assert((await page.locator('.channel-dialog .notice').textContent()).includes('策略已保存'));
  assert((await page.locator('.channel-row .state').first().textContent()).includes('待应用'));
  assert(await page.locator('[aria-label="选择 香港服务器"]').isChecked());
  await page.screenshot({path:path.join(out,`channels-readback-${status}.png`)});
  if(status===401){
   await page.getByRole('dialog',{name:'Stella 登录'}).waitFor();
   assert.equal(refreshRejections,2);
   await page.getByPlaceholder('用户名 / 昵称 / 邮箱').fill('fixture',{timeout:2500});
   await page.locator('.auth input[type="password"]').fill('synthetic-local-only',{timeout:2500});
   await page.getByRole('button',{name:'回港',exact:true}).click({timeout:2500});
   await page.getByRole('dialog',{name:'Stella 登录'}).waitFor({state:'detached'});
   assert.equal(logins,1);
  }else{
   for(let i=0;i<2;i++){
    await page.getByRole('button',{name:'重读状态',exact:true}).click();
    await page.getByRole('button',{name:'刷新',exact:true}).click();
   }
   readFailure=0;
  }
  await page.getByRole('button',{name:'刷新',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.channel-dialog .error'));
  assert.equal(writes.length,count+1);
  assert(await page.getByRole('button',{name:'应用到所选',exact:true}).isDisabled());
  assert((await page.locator('.channel-row .state').first().textContent()).includes('待应用'));
 }
 // A genuine new dirty draft still exercises the original 409 preservation case.
 await page.locator('.selector button.dd-btn').click();await page.getByRole('option',{name:'默认入口',exact:true}).click();
 fail=true;await page.getByRole('button',{name:'应用到所选',exact:true}).click();await page.getByRole('alert').filter({hasText:'配置已变化'}).waitFor();
 assert(await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).isChecked());
 await page.screenshot({path:path.join(out,'channels-cas-390.png')});
 await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).click();
 assert(await page.getByRole('button',{name:'Agent 管理',exact:true}).evaluate(el=>el===document.activeElement));
 const savedWrites=writes.length;
 await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.locator('.channel-row').first().waitFor();
 assert((await page.locator('.channel-row .state').first().textContent()).includes('待应用'));
 assert.equal(await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).isChecked(),true);
 await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).click();
 await page.reload();await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.getByRole('button',{name:'上报通道',exact:true}).click();await page.locator('.channel-row').first().waitFor();
 await page.getByRole('button',{name:'批量设置',exact:true}).click();
 assert((await page.locator('.channel-row .state').first().textContent()).includes('待应用'));
 assert.equal(writes.length,savedWrites);
 await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).check();
 await page.getByRole('button',{name:'总览',exact:true}).click();await page.getByRole('button',{name:'上报通道',exact:true}).click();assert(await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).isChecked());
 loginAsOther=true;readFailure=401;await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByRole('dialog',{name:'Stella 登录'}).waitFor();
 await page.getByPlaceholder('用户名 / 昵称 / 邮箱').fill('fixture');await page.locator('.auth input[type="password"]').fill('synthetic-local-only');await page.getByRole('button',{name:'回港',exact:true}).click();await page.getByRole('dialog',{name:'Stella 登录'}).waitFor({state:'detached'});
 await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.getByRole('button',{name:'上报通道',exact:true}).click();await page.locator('.channel-row').first().waitFor();
 assert.equal(await page.locator('.bulk-tools').count(),0);await page.getByRole('button',{name:'批量设置',exact:true}).click();
 assert.equal(await page.getByRole('checkbox',{name:'选择 香港服务器',exact:true}).isChecked(),false);assert.equal(writes.length,savedWrites);assert.equal(logins,2);assert.equal(refreshRejections,4);
 await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).click();
 assert.deepEqual(unknown,[]);assert.deepEqual(errors,[]);
 assert.deepEqual(consoleMessages.filter(m=>m.type==='error'&&!m.text.startsWith('Failed to load resource:')),[]);
 const rejectedQuery=await page.evaluate(()=>fetch('/nodes/report-channels?unknown=1').then(r=>r.status));assert.equal(rejectedQuery,501);
 methodProbe=true;const rejectedMethod=await page.evaluate(()=>fetch('/nodes/report-channels',{method:'HEAD'}).then(r=>r.status));methodProbe=false;assert.equal(rejectedMethod,501);assert.deepEqual(blockedMethods,['HEAD /nodes/report-channels']);
 assert.deepEqual(blockedQueries,['/nodes/report-channels?unknown=1']);assert(blockedWebSockets.length>0);
 console.log(JSON.stringify({status:'passed',manifest,geometry,writes,unknown,errors,blockedQueries,blockedWebSockets,refreshRejections,logins},null,2));
}finally{
 await writeFile(path.join(out,'browser-result.json'),JSON.stringify({manifest,announcementChecks,geometry,writes,unknown,errors,consoleMessages,requests,blockedQueries,blockedWebSockets,blockedMethods,refreshRejections,logins},null,2));
 await browser.close();await new Promise(r=>server.close(r));
}
