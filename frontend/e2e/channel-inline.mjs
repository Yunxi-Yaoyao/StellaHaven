// Actual built App/router/shared CSS. Isolated allowlisted HTTP fixtures only.
import http from 'node:http';
import {readFile,stat,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const root=path.resolve(process.env.STELLA_APP_DIST||'dist'),out=process.env.STELLA_QA_OUTPUT;assert(out);await mkdir(out,{recursive:true});
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.svg':'image/svg+xml','.png':'image/png'};
const unknown=[],errors=[],requests=[],writes=[],geometry=[],screenshots=[];let readFailure=0,nextReadFailure=0,conflict=false,logins=0,refreshRejections=0,otherOwner=false;
let owner={id:'local-fixture-owner',username:'fixture',display_name:'云曦',is_admin:false,email:'',email_verified:false,avatar_url:null,home_bg:null};
const names=['香港服务器','超长节点名称abcdefghijklmnopabcdefghijklmnopabcdefghijklmnopabcdefghijklmnop'];
let channel={revision:0,default_entry_id:'public',entries:[{entry_id:'public',origin:'https://stella.example.test'},{entry_id:'private',origin:'https://very-long-registered-private-entry-west.example.test'}],nodes:names.map((name,i)=>({node_id:i+1,name,mode:'default',entry_id:null,revision:0,state:'pending',actual_origin:null,http_ms:null,http_origin:null,http_status:null,sampled_at:null,error:null,online:i===0}))};
const server=http.createServer(async(req,res)=>{let file=path.resolve(root,'.'+new URL(req.url,'http://fixture').pathname);if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{if(!(await stat(file)).isFile())throw Error();}catch{file=path.join(root,'index.html');}res.setHeader('Content-Type',types[path.extname(file)]??'application/octet-stream');res.end(await readFile(file));});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-background-networking']});
let result='failed';
try{
 const context=await browser.newContext({serviceWorkers:'block',hasTouch:true});
 await context.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!==base.replace('http:','ws:')||u.pathname!=='/ws/notifications'||u.search)unknown.push('WS '+ws.url());ws.close();});
 await context.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url()),p=u.pathname.replace(/\/$/,'');requests.push([r.method(),p]);
  if(u.origin!==base||u.search&&!(p==='/status'&&u.search==='?view=nodes')){unknown.push(r.url());return route.abort();}
  const allowed=r.method()==='GET'||r.method()==='POST'&&['/auth/login','/auth/refresh','/auth/activity'].includes(p)||r.method()==='PUT'&&p==='/nodes/report-channels';
  if(!allowed){unknown.push(r.method()+' '+p);return route.abort();}
  let data;
  if(p==='/auth/me')data=owner;
  else if(p==='/auth/refresh'&&readFailure===401){refreshRejections++;return route.fulfill({status:401,json:{detail:'Local expired fixture'}});}
  else if(p==='/auth/login'){logins++;readFailure=0;if(otherOwner)owner={...owner,id:'other-fixture-owner'};data=owner;}
  else if(p==='/auth/status')data={initialized:true,registration_open:false,email_enabled:false};
  else if(p==='/navigation')data={entries:[],legacy_routes:{}};
  else if(p==='/external-modules'||p==='/component-installs')data=[];
  else if(p==='/notifications/unread-count')data={count:0};
  else if(p==='/agent/version')data={version:'fixture-only'};
  else if(p==='/nodes')data=names.map((name,i)=>({id:i+1,name,platform:'linux',host:'192.0.2.'+(i+1),status:i?'offline':'online',agent_version:'fixture-only',last_seen_at:null,interfaces:{},created_at:new Date().toISOString(),installed:true,net_type:'public'}));
  else if(p==='/nodes/host')data={local_install_supported:false,installed:false,node_id:null};
  else if(p==='/nodes/report-channels'){
   if(r.method()==='GET'&&readFailure)return route.fulfill({status:readFailure,json:{detail:'Local ACK read unavailable'}});
   if(r.method()==='PUT'){
    const v=r.postDataJSON();writes.push(v);if(conflict)return route.fulfill({status:409,json:{detail:'Local CAS conflict'}});
    assert.equal(v.revision,channel.revision);assert.deepEqual(v.node_ids,[1]);assert(['auto','default','fixed'].includes(v.mode));assert.equal(v.entry_id,v.mode==='fixed'?'private':null);
    channel={...channel,revision:channel.revision+1,nodes:channel.nodes.map(n=>v.node_ids.includes(n.node_id)?{...n,mode:v.mode,entry_id:v.entry_id,revision:channel.revision+1,state:'pending'}:n)};readFailure=nextReadFailure;nextReadFailure=0;
   }data=channel;
  }
  else if(p==='/config/public-host')data={value:channel.entries[0].origin};
  else if(p==='/config/client-preferences')data={revision:0,appearance:{},live2d:{enabled:false}};
  else if(p==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"></svg>'});
  else if(p==='/config/site-background')data={url:null};
  else if(p==='/auth/activity')data={ok:true};
  else if(p==='/operations/backups/client-preferences')return route.fulfill({status:404,json:{detail:'No fixture preferences'}});
  if(data!==undefined)return route.fulfill({json:data});
  if(r.resourceType()==='document'||['script','stylesheet','font','image'].includes(r.resourceType())&&p.startsWith('/static/'))return route.continue();
  unknown.push(r.method()+' '+p);return route.fulfill({status:501,json:{detail:'Unknown fixture route'}});
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 const edit=()=>page.getByRole('button',{name:'设置 '+names[0]+' 上报通道',exact:true});
 async function pick(name){await page.locator('.row-editor .dd-btn').click();await page.getByRole('option',{name,exact:true}).click();}
 async function shot(name){await page.mouse.move(0,0);await page.waitForTimeout(180);const file=name+'.png';await page.screenshot({path:path.join(out,file)});screenshots.push(file);}
 await page.goto(base+'/status?view=nodes');await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.getByRole('button',{name:'上报通道',exact:true}).click();await page.locator('.channel-row').first().waitFor();
 for(const width of [1365,390,320]){
  await page.setViewportSize({width,height:900});await edit().click();await edit().click();assert.equal(await page.locator('.row-editor').count(),1);assert.equal(await page.locator('.bulk-tools').count(),0);
  await page.locator('.row-editor .dd-btn').click();await page.getByRole('option',{name:'自动选择',exact:true}).scrollIntoViewIfNeeded();
  const g=await page.locator('.row-editor .dd-menu').evaluate(el=>{const r=el.getBoundingClientRect(),d=el.closest('dialog'),b=d.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,parentLeft:b.left,parentRight:b.right,inDialog:!!d,position:getComputedStyle(el).position,visible:[...el.querySelectorAll('button')].every(o=>{const x=o.getBoundingClientRect();return document.elementFromPoint(x.x+x.width/2,x.y+x.height/2)?.closest('[role="option"]')===o;}),scroll:d.scrollWidth,client:d.clientWidth};});
  assert(g.inDialog&&g.visible&&g.left>=g.parentLeft&&g.right<=g.parentRight&&g.scroll<=g.client+1,JSON.stringify(g));geometry.push({width,...g});assert.equal(await page.locator('dialog[open]').count(),1);
  if(width<=390)assert.equal(await page.locator('.row-editor .selector').evaluate(el=>getComputedStyle(el).order),'0','mobile keeps selector before confirmation actions');
  await shot('inline-double-entry-'+width);await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),1);await page.locator('.row-editor').getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'设置 '+names[1]+' 上报通道',exact:true}).click();await shot('inline-long-name-'+width);await page.locator('.row-editor').getByRole('button',{name:'取消',exact:true}).click();
 }
 assert.equal(writes.length,0);
 await edit().click();await pick('自动选择');await edit().click();assert((await page.locator('.row-editor .dd-btn').textContent()).includes('自动选择'));
 // Bulk and row drafts do not copy into one another.
 await page.getByRole('button',{name:'批量设置',exact:true}).click();await page.getByRole('checkbox',{name:'选择 '+names[1],exact:true}).check();await edit().click();assert((await page.locator('.row-editor .dd-btn').textContent()).includes('自动选择'));
 await page.getByRole('button',{name:'批量设置',exact:true}).click();assert(await page.getByRole('checkbox',{name:'选择 '+names[1],exact:true}).isChecked());assert((await page.locator('.bulk-tools .dd-btn').textContent()).includes('默认入口'));await edit().click();
 await page.getByRole('button',{name:'应用此节点',exact:true}).click();await page.locator('.row-editor [role="status"]').waitFor();assert.equal(writes.length,1);assert((await page.locator('.channel-row .state').first().textContent()).includes('待 Agent 确认'));
 channel={...channel,nodes:channel.nodes.map(n=>n.node_id===1?{...n,state:'applied',actual_origin:channel.entries[1].origin}:n)};await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.row-editor .notice')?.textContent.includes('Agent 已确认'));await shot('inline-applied-320');
 for(const status of [503,401]){
  await pick(status===503?'默认入口':'自动选择');nextReadFailure=status;const count=writes.length;await page.getByRole('button',{name:'应用此节点',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.channel-dialog .error')?.textContent.includes('状态读取失败'));assert.equal(writes.length,count+1);
  await shot('inline-readback-failure-'+status);
  if(status===401){await page.getByRole('dialog',{name:'Stella 登录'}).waitFor();await page.getByPlaceholder('用户名 / 昵称 / 邮箱').fill('fixture');await page.locator('.auth input[type="password"]').fill('synthetic-local-only');await page.getByRole('button',{name:'回港',exact:true}).click();await page.getByRole('dialog',{name:'Stella 登录'}).waitFor({state:'detached'});}else{await page.getByRole('button',{name:'重读状态',exact:true}).click();readFailure=0;}
  await page.getByRole('button',{name:'刷新',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('.channel-dialog .error'));assert.equal(writes.length,count+1);assert(await page.getByRole('button',{name:'应用此节点',exact:true}).isDisabled());await shot('inline-readback-'+status);
 }
 await pick('固定入口 · very-long-registered-private-entry-west.example.test');conflict=true;await page.getByRole('button',{name:'应用此节点',exact:true}).click();await page.getByRole('alert').filter({hasText:'配置已变化'}).waitFor();await shot('inline-cas-320');const count=writes.length;
 await page.getByRole('button',{name:'总览',exact:true}).click();const reads=requests.filter(r=>r[1]==='/nodes/report-channels').length;await page.waitForTimeout(5200);assert.equal(requests.filter(r=>r[1]==='/nodes/report-channels').length,reads,'inactive channels stop polling');await page.getByRole('button',{name:'上报通道',exact:true}).click();assert((await page.locator('.row-editor .dd-btn').textContent()).includes('private-entry'));
 await page.getByRole('button',{name:'关闭 Agent 管理',exact:true}).click();await page.getByRole('button',{name:'Agent 管理',exact:true}).click();assert((await page.locator('.row-editor .dd-btn').textContent()).includes('private-entry'));assert.equal(writes.length,count);
 // One real registry entry: no invented alternatives; retain unavailable draft.
 channel={...channel,entries:channel.entries.slice(0,1)};await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByRole('alert').filter({hasText:'草稿入口已不可用'}).waitFor();assert(await page.getByRole('button',{name:'应用此节点',exact:true}).isDisabled());assert.equal(await page.getByRole('link',{name:'站点设置',exact:true}).getAttribute('href'),'/settings?section=services');
 for(const width of [1365,390,320]){await page.setViewportSize({width,height:900});await page.locator('.row-editor .dd-btn').click();assert.equal(await page.getByRole('option').count(),1);await shot('inline-single-entry-'+width);await page.keyboard.press('Escape');}
 // Different authenticated owner must not inherit retained row/bulk drafts.
 otherOwner=true;readFailure=401;await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByRole('dialog',{name:'Stella 登录'}).waitFor();await page.getByPlaceholder('用户名 / 昵称 / 邮箱').fill('fixture');await page.locator('.auth input[type="password"]').fill('synthetic-local-only');await page.getByRole('button',{name:'回港',exact:true}).click();await page.getByRole('dialog',{name:'Stella 登录'}).waitFor({state:'detached'});await page.getByRole('button',{name:'Agent 管理',exact:true}).click();await page.getByRole('button',{name:'上报通道',exact:true}).click();await page.locator('.channel-row').first().waitFor();assert.equal(await page.locator('.row-editor').count(),0);assert.equal(await page.locator('.bulk-tools').count(),0);assert.equal(writes.length,count);
 assert.deepEqual(unknown,[]);assert.deepEqual(errors,[]);assert.equal(logins,2);result='passed';
}finally{await writeFile(path.join(out,'browser-result.json'),JSON.stringify({result,kind:'isolated built actual App; synthetic API, not deployed',geometry,writes,requests,unknown,errors,screenshots,logins,refreshRejections},null,2));await browser.close();await new Promise(r=>server.close(r));}
console.log(JSON.stringify({result,geometry,writes,unknown,errors,screenshots,logins,refreshRejections},null,2));
