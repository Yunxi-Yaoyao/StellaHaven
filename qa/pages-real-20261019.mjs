import {captureOwnSession,logoutOwnSession} from './own-session.mjs';
let ownSID;
import {chromium} from '/opt/hermes-workstation/stella-preview-20261018/frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs';import assert from 'node:assert/strict';import crypto from 'node:crypto'
const out='/opt/hermes-workstation/docs/Stella-反馈梳理-20261018/external-runtime'
const objects=JSON.parse(fs.readFileSync(out+'/OBJECTS.json','utf8'))
const cred=JSON.parse(fs.readFileSync('/var/lib/stella-preview-20261018/private/owner.json','utf8'))
const base='https://stella-dev.p.xiya.live',pages='https://pages-dev.p.xiya.live',root=objects.project_id
const result={scope:'real persistent preview Vue WebProjectPane + imported HTML/JS/CSS + backend PostgreSQL state',normal_ui_login:false,resources:[],pageErrors:[],steps:[],blockedExternal:[]}
const b=await chromium.launch({executablePath:'/usr/bin/google-chrome-stable',headless:true,args:['--no-sandbox','--no-proxy-server']});const c=await b.newContext({viewport:{width:1440,height:1000}});const p=await c.newPage();let grant
await c.route('**/*',r=>{const u=new URL(r.request().url());if([base,pages,'https://pages-alt-dev.p.xiya.live'].includes(u.origin)||['blob:','data:'].includes(u.protocol))return r.continue();result.blockedExternal.push(u.hostname+u.pathname);return r.abort()})
p.on('pageerror',e=>result.pageErrors.push(e.message))
p.on('response',async r=>{const u=new URL(r.url());if(u.origin===pages)result.resources.push({path:u.pathname.replace(/\/p\/[^/]+\//,'/p/<cap>/'),status:r.status(),type:r.headers()['content-type']});if(u.pathname==='/web-projects/'+root+'/launch'&&r.ok())grant=await r.json()})
async function api(method,path,data,expected=200,headers={}){const r=await c.request.fetch(base+path,{method,data,headers:{Origin:base,...headers}});result.steps.push({method,path,status:r.status()});assert.equal(r.status(),expected);return r.json()}
try{
 await p.goto(base+'/notes?doc='+root,{waitUntil:'domcontentloaded'});await p.getByRole('dialog',{name:'Stella 登录'}).waitFor();await p.locator('input[autocomplete=username]').fill(cred.username);await p.locator('input[autocomplete=current-password]').fill(cred.password);const login=p.waitForResponse(r=>new URL(r.url()).pathname==='/auth/login'&&r.request().method()==='POST');await p.getByRole('button',{name:'回港',exact:true}).click();assert.equal((await login).status(),200);await p.getByRole('dialog',{name:'Stella 登录'}).waitFor({state:'hidden'});result.normal_ui_login=true;ownSID=await captureOwnSession(c,base);
 const frame=p.frameLocator('.web-project-pane iframe');await frame.getByRole('heading',{name:'TEST Real Imported Runtime'}).waitFor({timeout:30000});
 assert.equal(grant.target_origin,pages);assert.equal(grant.source_origin,base);
 assert.equal(await frame.locator('body').getAttribute('data-real-script'),'executed');assert.equal(await frame.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(24, 50, 74)');result.real_html_js_css_executed=true;
 const before=await api('GET','/web-projects/'+root+'/state');
 const write=p.waitForResponse(r=>new URL(r.url()).pathname==='/web-projects/'+root+'/state'&&r.request().method()==='PUT');await frame.getByRole('button',{name:'保存网页状态'}).click();assert.equal((await write).status(),200);
 await p.getByText('网页进度已保存到 Stella',{exact:true}).waitFor();const state=await api('GET','/web-projects/'+root+'/state');assert.equal(state.data.acceptance,'REAL-RUNTIME-PERSISTED-20261019');assert.equal(state.revision,before.revision+1);result.real_parent_bridge_write_read=true;
 const body={revision:state.revision,epoch:state.epoch,write_id:crypto.randomUUID(),data:{acceptance:'MUST-NOT-COMMIT'},capability:grant.capability};
 await api('PUT','/web-projects/'+root+'/state',{...body,capability:'a'.repeat(43)},403);result.wrong_capability_rejected=true;
 await api('PUT','/web-projects/'+root+'/state',body,403,{Origin:'https://evil.invalid'});result.wrong_origin_rejected=true;
 const anonymous=await b.newContext();const deny=await anonymous.request.put(base+'/web-projects/'+root+'/state',{headers:{Origin:base},data:body});assert.equal(deny.status(),401);result.anonymous_rejected=true;await anonymous.close();
 const foreign=await c.request.get(grant.url.replace(pages,'https://pages-alt-dev.p.xiya.live'));assert.equal(foreign.status(),403);result.foreign_pages_origin_cap_rejected=true;
 const unchanged=await api('GET','/web-projects/'+root+'/state');assert.deepEqual(unchanged,state);result.all_negatives_state_unchanged=true;
 const oldCap=grant.capability;const relaunch=p.waitForResponse(r=>new URL(r.url()).pathname==='/web-projects/'+root+'/launch'&&r.ok());await p.getByRole('button',{name:'刷新网页',exact:true}).click();await relaunch;await frame.locator('#state').filter({hasText:'REAL-RUNTIME-PERSISTED-20261019'}).waitFor({timeout:15000});assert.notEqual(grant.capability,oldCap);result.relaunch_restores_server_state=true;
 await p.screenshot({path:out+'/evidence/pages-real-vue-state.png',fullPage:true});result.screenshot='evidence/pages-real-vue-state.png';
 assert(result.resources.some(r=>r.path.endsWith('/app.js')&&r.status===200&&r.type.includes('javascript')));assert(result.resources.some(r=>r.path.endsWith('/style.css')&&r.status===200&&r.type.includes('css')));assert(result.resources.some(r=>r.path.endsWith('/__stella_storage.js')&&r.status===200));
 result.pageErrorsUnexplained=result.pageErrors;assert.equal(result.pageErrors.length,0);result.passed=true;
}catch(e){result.error=e.message;if(await p.locator('input[type=password]:visible').count()===0){result.failure_body=(await p.locator('body').innerText()).slice(0,3000);await p.screenshot({path:out+'/evidence/pages-real-vue-failed.png',fullPage:true})}process.exitCode=1}finally{try{result.logout=await logoutOwnSession(c,base,ownSID)}catch(e){result.logout_error=e.message;process.exitCode=1}finally{fs.writeFileSync(out+'/PAGES.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await b.close();}}
