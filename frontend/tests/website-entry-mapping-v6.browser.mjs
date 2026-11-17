// Full production-built App + shared CSS + real isolated SQLite website routers.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
import {chromium} from 'playwright';
import {build} from 'esbuild';
const out=process.env.V6_EVIDENCE,dist=process.env.V6_BUILD;
assert.ok(out&&dist&&path.isAbsolute(out)&&path.isAbsolute(dist));fs.mkdirSync(out,{recursive:true});fs.mkdirSync(path.join(out,'screenshots'),{recursive:true});
const cert=path.join(out,'fixture.crt'),key=path.join(out,'fixture.key');
const openssl=spawnSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',key,'-out',cert,'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,DNS:*.fixture.test,IP:127.0.0.1'],{encoding:'utf8'});assert.equal(openssl.status,0);fs.chmodSync(key,0o600);
fs.rmSync(path.join(out,'server.json'),{force:true});
const python='/opt/hermes-workstation/stella-production-closure-20261017/.venv/bin/python',root=path.resolve('..');
const log=fs.openSync(path.join(out,'server.log'),'w');
const child=spawn(python,[path.join(root,'tests_website_settings/v6_browser_server.py')],{cwd:out,env:{PATH:'/usr/bin:/bin',HOME:out,TMPDIR:process.env.TMPDIR,PYTHONPATH:root,V6_EVIDENCE:out,V6_BUILD:dist,V6_CERT:cert,V6_KEY:key},stdio:['ignore',log,log]});
const result={checks:[],screenshots:[],unknown:[],errors:[],requests:[],geometry:[]};let browser;
try{
 for(let n=0;n<100&&!fs.existsSync(path.join(out,'server.json'));n++){assert.equal(child.exitCode,null);await new Promise(r=>setTimeout(r,100));}
 const fixture=JSON.parse(fs.readFileSync(path.join(out,'server.json'),'utf8'));
 browser=await chromium.launch({headless:true,executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox','--no-proxy-server','--host-resolver-rules=MAP *.fixture.test 127.0.0.1']});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1365,height:900},serviceWorkers:'block'}),page=await context.newPage();
 const bundled=await build({entryPoints:['tests/fixtures/clientPreferences.ts'],bundle:true,write:false,platform:'node',format:'esm'});
 const {createClientPreferencesFixture}=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_home_particles:'off'},allowWrite:true});
 let failRead=false,corruptMapping=false,holdCheck=false,checkRelease,checkHeld=false;
 await context.addInitScript(()=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');});
 page.on('pageerror',e=>result.errors.push(e.message));
 await context.routeWebSocket('**/*',ws=>{const url=new URL(ws.url());if(url.hostname.endsWith('.fixture.test')&&Number(url.port)===fixture.port&&url.pathname==='/ws/notifications'){ws.close();return;}result.unknown.push('WS '+ws.url());ws.close();});
 await context.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(!(url.hostname.endsWith('.fixture.test')&&Number(url.port)===fixture.port)&&!fixture.upstreams.some(v=>new URL(v).origin===url.origin)){result.unknown.push(request.url());return route.abort('blockedbyclient');}
  if(request.method()==='GET'&&url.pathname==='/avatar.png')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b49bd5"/></svg>'});
  const pref=preferences.respond(request.method(),url.pathname+url.search,request.postDataJSON());if(pref)return route.fulfill(pref);
  if(url.pathname.startsWith('/website-settings')||url.pathname.startsWith('/external-modules'))result.requests.push({method:request.method(),path:url.pathname,body:request.postDataJSON()});
  if(failRead&&request.method()==='GET'&&/^\/external-modules\/[^/]+$/.test(url.pathname))return route.fulfill({status:403,json:{detail:'synthetic readback failure'}});
  if(corruptMapping&&(request.method()==='PATCH'&&url.pathname.startsWith('/website-settings/')||request.method()==='GET'&&/^\/external-modules\/[^/]+$/.test(url.pathname))){
   const response=await route.fetch({url:'https://127.0.0.1:'+fixture.port+url.pathname,headers:{...request.headers(),host:url.host}}),value=await response.json();
   return route.fulfill({response,json:{...value,alternate_address:null}});
  }
  if(holdCheck&&url.pathname==='/website-settings/check'){
   const response=await route.fetch({url:'https://127.0.0.1:'+fixture.port+url.pathname,headers:{...request.headers(),host:url.host}});checkHeld=true;await new Promise(resolve=>{checkRelease=resolve;});return route.fulfill({response});
  }
  return route.continue();
 });
 await page.goto(fixture.main+'/settings?section=navigation');await page.locator('.nav-settings').waitFor();
 await page.getByRole('button',{name:'＋ 添加网站',exact:true}).click();
 await page.getByRole('button',{name:'域名',exact:true}).waitFor({timeout:3000});
 await page.getByLabel('其他入口地址',{exact:true}).waitFor({timeout:3000});
 result.checks.push('Website editor exposes actual mode plus two distinct upstream inputs');
 const shot=async name=>{const file=path.join(out,'screenshots',name+'.png');await page.screenshot({path:file});result.screenshots.push(file);};
 const get=async p=>page.evaluate(async p=>{const response=await fetch(p);if(!response.ok)throw new Error('GET '+response.status);return response.json();},p);
 const save=async()=>{await page.getByRole('button',{name:'保存',exact:true}).click();await page.locator('.inline-editor').waitFor({state:'detached'});};
 const open=async name=>{await page.getByRole('button',{name:'编辑 '+name,exact:true}).click();await page.locator('.inline-editor fieldset:not(:disabled)').waitFor();};
 const settings=async()=>{await page.goto(fixture.main+'/settings?section=navigation');await page.locator('.nav-settings').waitFor();};
 const visit=async(parent,item,expectedPort,expectedPath,hasCode=false)=>{
  await page.goto(parent+'/apps/'+item.id);
  const frame=page.frameLocator('iframe[title="'+item.name+'"]');await frame.getByRole('heading',{name:'上游 '+expectedPort,exact:true}).waitFor();
  assert.equal(await frame.locator('#path').innerText(),expectedPath);
  if(hasCode){assert.equal(await frame.locator('body').getAttribute('data-v6-code'),'executed');assert.equal(await frame.locator('h1').evaluate(e=>getComputedStyle(e).color),'rgb(39, 78, 123)');}
  await shot('site-'+item.name+'-'+new URL(parent).hostname.split('.')[0]+'-'+(hasCode?'code':'plain')+'-'+expectedPort+'-'+result.screenshots.length);
 };
 await page.getByRole('button',{name:'域名',exact:true}).click();await page.getByRole('option',{name:'私网 IP / 端口',exact:true}).click();
 await page.getByLabel('网站地址',{exact:true}).fill(fixture.upstreams[0]+'/first?q=a%2Fb#one');await page.getByLabel('显示名称',{exact:true}).fill('映射网站');
 await page.getByRole('button',{name:'检测',exact:true}).click();await page.getByLabel('检测结果').waitFor();
 await shot('new-ip-single');await save();
 let item=(await get('/external-modules'))[0];assert.equal(item.mode,'isolated_proxy');assert.equal(item.alternate_address,null);assert.equal(item.mapping_configured,true);
 await open(item.name);assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),'');assert.equal(await page.getByRole('button',{name:'私网 IP / 端口',exact:true}).count(),1);
 await page.getByRole('button',{name:'取消',exact:true}).click();
 await visit(fixture.main,item,new URL(fixture.upstreams[0]).port,'/first?q=a%2Fb');await visit(fixture.other,item,new URL(fixture.upstreams[0]).port,'/first?q=a%2Fb');
 result.checks.push('Create/check/save/reopen real IP HTTP site; both registered HTTPS proxy lanes use the single upstream');
 await settings();await open(item.name);
 const second=fixture.upstreams[1]+'/second?q=x%2Fy#two';await page.getByLabel('其他入口地址',{exact:true}).fill(second);
 await page.locator('details.custom>summary').click();await page.getByLabel('自定义 CSS',{exact:true}).fill('h1{color:rgb(39,78,123)}');await page.getByLabel('自定义 JavaScript',{exact:true}).fill('document.body.dataset.v6Code="executed";');await page.getByLabel('启用自定义代码',{exact:true}).check();
 await save();item=(await get('/external-modules'))[0];assert.equal(item.alternate_address,second);assert.equal(item.injection.active.enabled,true);
 await open(item.name);assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),second);await page.getByRole('button',{name:'取消',exact:true}).click();
 await visit(fixture.main,item,new URL(fixture.upstreams[0]).port,'/first?q=a%2Fb',true);await visit(fixture.other,item,new URL(fixture.upstreams[1]).port,'/second?q=x%2Fy',true);
 result.checks.push('Second HTTP upstream keeps path/query/hash, actual public/other iframe bodies differ; saved CSS and JavaScript execute only inside isolated pages');
 // Actual expanded editor under complete App CSS at all required widths.
 await settings();await open(item.name);
 await page.locator('details.custom>summary').click();
 for(const width of [1200,1365,1920,390,320]){
  await page.setViewportSize({width,height:900});await page.locator('#website-address').scrollIntoViewIfNeeded();await page.waitForTimeout(150);
  await page.getByLabel('其他入口地址',{exact:true}).fill(second+'-'+('long-segment/'.repeat(12))+width);
  const geometry=await page.locator('.inline-editor').evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,addresses:[...el.querySelectorAll('#website-address,#website-alternate')].map(x=>{const r=x.getBoundingClientRect();return {x:r.x,width:r.width,right:r.right};})};});
  assert.ok(geometry.left>=0&&geometry.right<=width+1);assert.ok(geometry.scrollWidth<=width);assert.ok(geometry.addresses.every(r=>r.width>=120&&r.right<=width));result.geometry.push(geometry);await shot('expanded-'+width);
  await page.getByLabel('自定义 CSS',{exact:true}).scrollIntoViewIfNeeded();await shot('code-'+width);
 }
 await page.getByLabel('其他入口地址',{exact:true}).fill(second);await page.setViewportSize({width:320,height:400});await page.getByRole('button',{name:'保存',exact:true}).scrollIntoViewIfNeeded();await shot('short-height-save');
 assert.ok(await page.getByRole('button',{name:'保存',exact:true}).isVisible());
 result.mobileSaveTarget=await page.getByRole('button',{name:'保存',exact:true}).evaluate(el=>{const r=el.getBoundingClientRect();return {width:r.width,height:r.height,inViewport:r.top>=0&&r.bottom<=innerHeight,hit:el.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))};});
 assert.ok(result.mobileSaveTarget.height>=44&&result.mobileSaveTarget.inViewport&&result.mobileSaveTarget.hit);await page.setViewportSize({width:1365,height:900});
 // Write ACK is real; synthetic GET403 must retain draft and retry GET only.
 await page.getByLabel('显示名称',{exact:true}).fill('已写入待回读');failRead=true;const writes=result.requests.filter(r=>r.method==='PATCH').length;
 await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'保存结果尚未确认'}).waitFor();assert.equal(await page.getByLabel('显示名称',{exact:true}).inputValue(),'已写入待回读');await shot('readback-403-retained');failRead=false;
 await page.getByRole('button',{name:'重试回读',exact:true}).click();await page.locator('.inline-editor').waitFor({state:'detached'});assert.equal(result.requests.filter(r=>r.method==='PATCH').length,writes+1);
 item=(await get('/external-modules'))[0];await open(item.name);
 // PATCH and GET both corrupted to the same cleared mapping must not self-confirm.
 await page.getByLabel('显示名称',{exact:true}).fill('映射负控');corruptMapping=true;await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'保存结果尚未确认'}).waitFor();await shot('mapping-readback-negative');corruptMapping=false;
 await page.getByRole('button',{name:'重试回读',exact:true}).click();await page.locator('.inline-editor').waitFor({state:'detached'});item=(await get('/external-modules'))[0];assert.equal(item.alternate_address,second);
 result.checks.push('ACK/GET403 recovery performs no duplicate PATCH; equal corrupted PATCH and GET cannot redefine the frozen mapping expectation');
 await open(item.name);await page.getByLabel('其他入口地址',{exact:true}).fill(fixture.upstreams[1]+'/blocked');await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'当前设置不能保存'}).waitFor();assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),fixture.upstreams[1]+'/blocked');await shot('second-upstream-error');
 // A delayed check for old second input cannot replace the new name/code/URL drafts.
 await page.getByLabel('其他入口地址',{exact:true}).fill(second);holdCheck=true;checkHeld=false;await page.getByRole('button',{name:'检测',exact:true}).click();
 for(let n=0;n<100&&!checkHeld;n++)await new Promise(r=>setTimeout(r,20));assert.ok(checkHeld);
 await page.getByLabel('其他入口地址',{exact:true}).fill(second+'-new');await page.getByLabel('显示名称',{exact:true}).fill('迟到检测保留');await page.locator('details.custom>summary').click();await page.getByLabel('自定义 CSS',{exact:true}).fill('h1{color:rgb(39,78,123)}/* retained late draft */');holdCheck=false;checkRelease();await page.waitForTimeout(200);
 assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),second+'-new');assert.equal(await page.getByLabel('显示名称',{exact:true}).inputValue(),'迟到检测保留');
 assert.equal(await page.getByLabel('自定义 CSS',{exact:true}).inputValue(),'h1{color:rgb(39,78,123)}/* retained late draft */');
 await page.getByLabel('其他入口地址',{exact:true}).fill('');await save();item=(await get('/external-modules'))[0];assert.equal(item.alternate_address,null);
 await visit(fixture.other,item,new URL(fixture.upstreams[0]).port,'/first?q=a%2Fb',true);
 result.checks.push('Blocked second upstream retains input; delayed old check is fenced; explicit clearing restores shared primary without deleting CSS/JS');
 // Direct sites use the same mapping via original HTTPS browser addresses, no proxy Host substitution.
 await settings();const direct=await page.evaluate(async address=>{const response=await fetch('/website-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({address,address_mode:'ip',alternate_address:null,name:'直连网站',connection:{transport:'direct',injection_delivery:'loader'},idempotency_key:'v6-real-direct'})});if(!response.ok)throw new Error(await response.text());return response.json();},fixture.upstreams[2]+'/direct?q=one#first');
 await visit(fixture.main,direct,new URL(fixture.upstreams[2]).port,'/direct?q=one');await visit(fixture.other,direct,new URL(fixture.upstreams[2]).port,'/direct?q=one');
 await settings();await open(direct.name);await page.getByLabel('其他入口地址',{exact:true}).fill(fixture.upstreams[3]+'/different?q=two#second');await save();const directRead=await get('/external-modules/'+direct.id);assert.equal(directRead.mode,'iframe');
 await visit(fixture.main,directRead,new URL(fixture.upstreams[2]).port,'/direct?q=one');await visit(fixture.other,directRead,new URL(fixture.upstreams[3]).port,'/different?q=two');
 result.checks.push('Real original HTTPS direct iframe mapping selects distinct owned TLS upstreams with path/query preserved');
 // Domain mode is an actual new-site path, not only a renamed selector.
 await settings();await page.getByRole('button',{name:'＋ 添加网站',exact:true}).click();
 const domainFirst=fixture.upstreams[0].replace('127.0.0.1','first.fixture.test')+'/domain?q=main#one',domainOther=fixture.upstreams[1].replace('127.0.0.1','second.fixture.test')+'/domain-other?q=other#two';
 await page.getByLabel('网站地址',{exact:true}).fill(domainFirst);await page.getByLabel('其他入口地址',{exact:true}).fill(domainOther);await page.getByLabel('显示名称',{exact:true}).fill('域名网站');await shot('new-domain-two');await save();
 const domain=(await get('/external-modules')).find(item=>item.name==='域名网站');assert.equal(domain.address_mode,'domain');assert.equal(domain.alternate_address,domainOther);
 await open(domain.name);assert.equal(await page.getByRole('button',{name:'域名',exact:true}).count(),1);assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),domainOther);await page.getByRole('button',{name:'取消',exact:true}).click();
 await visit(fixture.main,domain,new URL(fixture.upstreams[0]).port,'/domain?q=main');await visit(fixture.other,domain,new URL(fixture.upstreams[1]).port,'/domain-other?q=other');
 result.checks.push('Domain-mode actual UI create/save/reopen and two generated proxy origins select independently DNS-pinned domain upstreams');
 // Independent POST acknowledgement / GET403 control (owner suite only tested PATCH).
 await settings();await page.getByRole('button',{name:'＋ 添加网站',exact:true}).click();
 await page.getByRole('button',{name:'域名',exact:true}).click();await page.getByRole('option',{name:'私网 IP / 端口',exact:true}).click();
 await page.getByLabel('网站地址',{exact:true}).fill(fixture.upstreams[0]+'/create-ack');await page.getByLabel('显示名称',{exact:true}).fill('create-ack-review');
 failRead=true;const postBefore=result.requests.filter(r=>r.method==='POST'&&r.path==='/website-settings').length;
 await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'保存结果尚未确认'}).waitFor();
 assert.equal(await page.getByLabel('显示名称',{exact:true}).inputValue(),'create-ack-review');failRead=false;
 await page.getByRole('button',{name:'重试回读',exact:true}).click();await page.locator('.inline-editor').waitFor({state:'detached'});
 assert.equal(result.requests.filter(r=>r.method==='POST'&&r.path==='/website-settings').length,postBefore+1);
 result.checks.push('INDEPENDENT create POST ACK then GET403 retries GET only');
 // A mode change alone invalidates an old in-flight check, even with untouched URLs.
 await open('create-ack-review');holdCheck=true;checkHeld=false;await page.getByRole('button',{name:'检测',exact:true}).click();
 for(let n=0;n<100&&!checkHeld;n++)await new Promise(r=>setTimeout(r,20));assert.ok(checkHeld);
 await page.getByRole('button',{name:'私网 IP / 端口',exact:true}).click();await page.getByRole('option',{name:'域名',exact:true}).click();
 holdCheck=false;checkRelease();await page.waitForTimeout(250);
 assert.equal(await page.getByRole('button',{name:'域名',exact:true}).count(),1);
 assert.equal(await page.getByLabel('网站地址',{exact:true}).inputValue(),fixture.upstreams[0]+'/create-ack');
 await page.getByRole('button',{name:'取消',exact:true}).click();
 result.checks.push('INDEPENDENT mode-only change rejects late check');
 // Regression of the independent review's exact legacy registry-only routes.
 // No private_address, address_mode, or alternate_address is persisted on create.
 const legacyFailures=[];result.legacyRegressions=[];
 const legacyCase=async(id,fn)=>{try{await fn();result.legacyRegressions.push({id,passed:true});}catch(e){legacyFailures.push(id+': '+e.message);result.legacyRegressions.push({id,passed:false,error:e.message});await settings();}};
 const createLegacy=async name=>page.evaluate(async({address,name})=>{const items=await (await fetch('/external-modules')).json();for(const old of items.filter(x=>x.name.startsWith('legacy-implicit'))){const removed=await fetch('/external-modules/'+old.id,{method:'DELETE'});if(!removed.ok)throw new Error(await removed.text());}const r=await fetch('/website-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({address,name,connection:{transport:'direct',injection_delivery:'loader'},idempotency_key:name})});if(!r.ok)throw new Error(await r.text());return r.json();},{address:fixture.upstreams[2]+'/legacy?q=old#one',name});
 await legacyCase('W1',async()=>{
  await settings();const legacy=await createLegacy('legacy-implicit');await settings();await open(legacy.name);
  assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),'');
  for(const width of [1200,320]){await page.setViewportSize({width,height:900});await page.locator('#website-address').scrollIntoViewIfNeeded();await page.waitForTimeout(250);await shot('legacy-retained-'+width);}
  await page.setViewportSize({width:1365,height:900});
  // Metadata must retain the exact implicit registry route, with omission.
  await page.getByLabel('显示名称',{exact:true}).fill('legacy-implicit');await save();
  const metadataPatch=result.requests.filter(r=>r.method==='PATCH'&&r.path==='/website-settings/'+legacy.id).at(-1).body;
  assert.ok(!('alternate_address' in metadataPatch)&&!('address_mode' in metadataPatch));
  await visit(fixture.other,legacy,new URL(fixture.upstreams[3]).port,'/legacy?q=old');
  await settings();await open(legacy.name);
  const retainedHelp=await page.locator('.mapping-help').innerText();
  await page.getByLabel('网站地址',{exact:true}).fill(fixture.upstreams[2]+'/edited?q=new#two');
  await shot('legacy-primary-edited');await save();
  const saved=await get('/external-modules/'+legacy.id),payload=result.requests.filter(r=>r.method==='PATCH'&&r.path==='/website-settings/'+legacy.id).at(-1).body;
  assert.equal(payload.address_mode,'ip');assert.equal(payload.alternate_address,null);
  assert.match(retainedHelp,/沿用旧入口映射/);assert.equal(saved.mapping_configured,true);assert.equal(saved.alternate_address,null);assert.equal(saved.address_mode,'ip');
  await visit(fixture.main,saved,new URL(fixture.upstreams[2]).port,'/edited?q=new');await visit(fixture.other,saved,new URL(fixture.upstreams[2]).port,'/edited?q=new');
  await settings();await open(legacy.name);assert.equal(await page.getByLabel('其他入口地址',{exact:true}).inputValue(),'');await page.getByRole('button',{name:'取消',exact:true}).click();
 });
 await legacyCase('W2',async()=>{
  await settings();const legacy=await createLegacy('legacy-implicit-mode');await settings();await open(legacy.name);
  assert.equal(legacy.address_mode,null);assert.equal(legacy.mapping_configured,false);
  assert.equal(await page.getByRole('button',{name:'私网 IP / 端口',exact:true}).count(),1);
  const changed=fixture.upstreams[2].replace('127.0.0.1','first.fixture.test')+'/domain-under-ip-mode';
  await page.getByLabel('网站地址',{exact:true}).fill(changed);
  const rejectedCheck=page.waitForResponse(r=>new URL(r.url()).pathname==='/website-settings/check');
  await page.getByRole('button',{name:'检测',exact:true}).click();const rejected=await rejectedCheck;assert.equal(rejected.status(),422);await page.getByRole('alert').waitFor();
  const check=result.requests.filter(r=>r.path==='/website-settings/check'&&r.body?.module_id===legacy.id).at(-1);
  assert.equal(check.body.address_mode,'ip');assert.equal(check.body.alternate_address,null);
  const writes=result.requests.filter(r=>r.method==='PATCH').length;
  const rejectedSaveCheck=page.waitForResponse(r=>new URL(r.url()).pathname==='/website-settings/check');
  await page.getByRole('button',{name:'保存',exact:true}).click();assert.equal((await rejectedSaveCheck).status(),422);await page.getByRole('alert').waitFor();
  assert.equal(result.requests.filter(r=>r.method==='PATCH').length,writes);
  assert.equal((await get('/external-modules/'+legacy.id)).browser_url,legacy.browser_url);
  assert.equal(await page.getByLabel('网站地址',{exact:true}).inputValue(),changed);await shot('legacy-domain-rejected-in-ip-mode');
  await page.getByRole('button',{name:'私网 IP / 端口',exact:true}).click();await page.getByRole('option',{name:'域名',exact:true}).click();
  await save();const saved=await get('/external-modules/'+legacy.id);assert.equal(saved.address_mode,'domain');assert.equal(saved.browser_url,changed);assert.equal(saved.mapping_configured,true);
  await open(legacy.name);assert.equal(await page.getByRole('button',{name:'域名',exact:true}).count(),1);await shot('legacy-domain-explicit-reopen');await page.getByRole('button',{name:'取消',exact:true}).click();
 });
 await legacyCase('W1-explicit-clear',async()=>{
  await settings();const legacy=await createLegacy('legacy-implicit-clear');await settings();await open(legacy.name);
  await page.getByLabel('其他入口地址',{exact:true}).fill(fixture.upstreams[3]+'/temporary');await page.getByLabel('其他入口地址',{exact:true}).fill('');await save();
  const saved=await get('/external-modules/'+legacy.id);assert.equal(saved.mapping_configured,true);assert.equal(saved.alternate_address,null);
  await visit(fixture.other,saved,new URL(fixture.upstreams[2]).port,'/legacy?q=old');
 });
 assert.deepEqual(legacyFailures,[]);

 assert.deepEqual(result.unknown,[]);assert.deepEqual(result.errors,[]);
 const observations=JSON.parse(fs.readFileSync(path.join(out,'server-observations.json'),'utf8'));assert.deepEqual(observations.unknown,[]);result.upstreamObservations=observations.seen;
 result.passed=true;
 await context.close();
}catch(error){const pages=browser?.contexts()[0]?.pages()||[];if(pages[0]){await pages[0].screenshot({path:path.join(out,'failure.png')});result.dom=await pages[0].locator('body').innerText();}result.failure={message:error.message,stack:error.stack};throw error;}
finally{fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify(result,null,2));await browser?.close();child.kill('SIGTERM');await new Promise(resolve=>{if(child.exitCode!==null)resolve();else child.once('exit',resolve);});fs.closeSync(log);}
