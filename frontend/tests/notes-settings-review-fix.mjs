// Real App production bundle, owned full-main/PG only. No canned API responses.
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs';import crypto from 'node:crypto';
const R=process.env.NS_REVIEW_ROOT||'/root/.hermes/cache/scratch/notes-settings-review-fix';
const O=process.env.NS_REVIEW_OUT||'/opt/hermes-workstation/docs/Stella-完整收尾/notes-settings-review-fix';
const a=JSON.parse(fs.readFileSync(R+'/auth-private.json')),s=JSON.parse(fs.readFileSync(R+'/private.json')),url=a.url;
if(url!==`http://127.0.0.1:${s.http_port}`||!/^notes-settings-[a-f0-9]{16}$/.test(s.label)||fs.readlinkSync('/proc/self/ns/net')!==fs.readlinkSync(`/proc/${s.pid}/ns/net`))throw Error('owned namespace required');
const browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const results=[],errors=[],denied=[],payloads=[],docs=[];
fs.mkdirSync(O+'/screenshots',{recursive:true});
function receipt(){fs.writeFileSync(O+'/browser.json',JSON.stringify({results,errors,denied,payloads,docs},null,2));}
async function context(mobile){const c=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1365,height:950},isMobile:mobile,hasTouch:mobile,serviceWorkers:'block'});await c.addCookies(Object.entries(a.elevated).map(([name,value])=>({name,value,url})));await c.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin===url)return r.continue();denied.push(u.origin+u.pathname);return r.abort('blockedbyclient')});await c.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.host===new URL(url).host&&u.pathname.startsWith('/ws/'))ws.connectToServer();else ws.close()});return c;}
async function checked(r,code=200){expect(r.status()).toBe(code);return r.json();}
try{for(const mobile of [false,true]){
 const label=mobile?'mobile':'desktop',c=await context(mobile),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));
 const get=async path=>checked(await c.request.get(url+path));
 const shot=async name=>p.screenshot({path:O+'/screenshots/'+label+'-'+name+'.png',fullPage:true});
 async function check(id,fn){try{await fn();results.push({id:label+'-'+id,status:'passed'});}catch(e){results.push({id:label+'-'+id,status:'failed',error:e.message});await shot(id+'-failure');throw e;}finally{receipt();}}
 await check('smtp-hide-lock-return',async()=>{
  await p.goto(url+'/settings?section=services');await expect(p.getByLabel('SMTP 服务地址')).toBeVisible();
  await p.getByLabel('SMTP 服务地址').fill('draft.owned.invalid');const secret=crypto.randomBytes(24).toString('hex');await p.getByLabel('SMTP 密钥',{exact:true}).fill(secret);
  await p.route('**/admin/email/config',r=>r.request().method()==='PUT'?r.abort('failed'):r.continue());
  await p.getByRole('button',{name:'应用 SMTP 配置',exact:true}).click();await expect(p.getByText('未保存，请重试',{exact:true})).toBeVisible();expect(await p.getByLabel('SMTP 密钥',{exact:true}).inputValue()===secret).toBe(true);
  await p.getByRole('button',{name:'认证与安全',exact:true}).click();await expect(p.getByLabel('SMTP 密钥',{exact:true})).toHaveCount(0);
  const card=p.locator('.security-card');await card.getByRole('button',{name:'立即锁回',exact:true}).click();await expect(card.getByText('管理权限未解锁',{exact:true})).toBeVisible();
  await p.getByRole('button',{name:'服务与通知',exact:true}).click();await expect(p.getByLabel('SMTP 密钥',{exact:true})).toHaveCount(0);await expect(p.getByText('解锁管理保护后读取 SMTP 配置。')).toBeVisible();expect((await c.request.get(url+'/admin/email/config')).status()).toBe(403);await shot('locked-return');
  await p.getByRole('button',{name:'认证与安全',exact:true}).click();await card.getByRole('button',{name:'解锁管理权限',exact:true}).click();await card.getByLabel('当前管理密码',{exact:true}).fill(a.management);await card.getByRole('button',{name:'确认安全变更'}).click();await expect(card.getByText('管理权限已解锁',{exact:true})).toBeVisible();
  await p.getByRole('button',{name:'服务与通知',exact:true}).click();await expect(p.getByLabel('SMTP 服务地址')).toHaveValue('draft.owned.invalid');await expect(p.getByLabel('SMTP 密钥',{exact:true})).toHaveValue('');await p.unroute('**/admin/email/config');await shot('unlocked-draft');
 });
 await check('smtp-readback-only-new-edit',async()=>{
  let writes=0,reads=0,failRead=false;await p.route('**/admin/email/config',r=>{if(r.request().method()==='PUT'){writes++;failRead=true;return r.continue();}reads++;return failRead?r.abort('failed'):r.continue();});
  const secret=crypto.randomBytes(24).toString('hex');await p.getByLabel('SMTP 密钥',{exact:true}).fill(secret);await p.getByRole('button',{name:'应用 SMTP 配置',exact:true}).click();const retry=p.getByRole('button',{name:'重试读取 SMTP 配置',exact:true});await expect(retry).toBeEnabled();expect(writes).toBe(1);expect(await p.getByLabel('SMTP 密钥',{exact:true}).inputValue()===secret).toBe(true);
  const newer=crypto.randomBytes(24).toString('hex');await p.getByLabel('SMTP 密钥',{exact:true}).fill(newer);await p.getByLabel('SMTP 服务地址').fill('newer.owned.invalid');failRead=false;await retry.click();await expect(p.getByText('配置已保存',{exact:true})).toBeVisible();expect(writes).toBe(1);expect(reads).toBe(2);expect(await p.getByLabel('SMTP 密钥',{exact:true}).inputValue()===newer).toBe(true);await expect(p.getByLabel('SMTP 服务地址')).toHaveValue('newer.owned.invalid');expect((await get('/admin/email/config')).password).toBe('••••••');await shot('get-only-recovered');await p.unroute('**/admin/email/config');
 });
 const node=await checked(await c.request.post(url+'/nodes/',{headers:{Origin:url},data:{name:'Review '+label,host:'127.0.0.1',platform:'linux'}}),201);
 const ws=await checked(await c.request.post(url+'/workspaces/',{headers:{Origin:url},data:{user_id:a.uid,name:'Review '+label}}),201);
 for(const endpoint of ['association','nodes'])await check('timeline-'+endpoint+'-retry',async()=>{
  const doc=await checked(await c.request.post(url+'/documents/',{headers:{Origin:url},data:{workspace_id:ws.id,title:'Retained '+label+' '+endpoint,file_path:'/notes/'+crypto.randomUUID()+'.md',content:'Preserve association'}}),201);
  const path='/notes-tools/documents/'+doc.id+'/node';await checked(await c.request.put(url+path,{headers:{Origin:url},data:{node_id:node.id}}));docs.push({id:doc.id,node_id:node.id,endpoint,label});
  await p.goto(url+'/notes?doc='+doc.id);await expect(p.locator('.title-readonly')).toHaveText(doc.title);await expect(p.locator('.preview')).toContainText('Preserve association');if(mobile&&await p.locator('.list-drawer-shade').count())await p.getByTitle('收起列表',{exact:true}).click();
  const pattern=endpoint==='association'?'**'+path:'**/nodes/';let fail=true;let writes=0;
  const listener=req=>{if(new URL(req.url()).pathname===path&&req.method()==='PUT'){writes++;payloads.push({label,endpoint,path,method:'PUT',body:JSON.parse(req.postData())});}};p.on('request',listener);
  await p.route(pattern,r=>r.request().method()==='GET'&&fail?r.abort('failed'):r.continue());
  await p.getByRole('button',{name:'更多',exact:true}).click();await p.locator('#note-more-menu').getByRole('button',{name:'关联时间线',exact:true}).click();const panel=p.getByRole('dialog',{name:'关联时间线'});await expect(panel.getByRole('button',{name:'重试读取关联'})).toBeEnabled();await expect(panel.getByRole('button',{name:'保存关联'})).toBeDisabled();await expect(panel.getByLabel('关联节点')).toBeDisabled();expect(writes).toBe(0);expect((await get(path)).node_id).toBe(node.id);await shot('timeline-'+endpoint+'-unknown');
  fail=false;await panel.getByRole('button',{name:'重试读取关联'}).click();await expect(panel.getByRole('button',{name:'保存关联'})).toBeEnabled();await expect(panel.getByLabel('关联节点')).toHaveValue(String(node.id));expect(writes).toBe(0);expect((await get(path)).node_id).toBe(node.id);
  await panel.getByRole('button',{name:'保存关联'}).click();await expect(panel.getByRole('button',{name:'保存关联'})).toBeEnabled();expect(writes).toBe(1);expect(payloads.at(-1).body).toEqual({node_id:node.id});expect((await get(path)).node_id).toBe(node.id);const box=await panel.boundingBox();expect(box.x).toBeGreaterThanOrEqual(16);expect(box.x+box.width).toBeLessThanOrEqual((mobile?390:1365)-16);await shot('timeline-'+endpoint+'-recovered');await panel.getByRole('button',{name:'关闭关联时间线'}).click();await p.unroute(pattern);p.off('request',listener);
 });
 await c.close();
}}finally{receipt();await browser.close();}
expect(errors).toEqual([]);console.log('Real App bounded browser journeys passed',results.length);
