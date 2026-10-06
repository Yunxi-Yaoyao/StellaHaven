import {test as base,expect,type Page} from '@playwright/test';

const ROOT='http://127.0.0.1:15287';
const workspaceId='11111111-1111-4111-8111-111111111111';
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(done=>resolve=done);return {promise,resolve};}
function checked(address:string){return {
 normalized_url:address,name_suggestion:'额度',access:{status:'reachable',http_status:200},
 embedding:{status:'allowed',reason_code:'no_observed_restriction',reason:'未发现响应头限制'},
 injection:{status:'unsupported',reason:'跨域直连不能修改 DOM'},help:null,
 can_save:true,recommended_behavior:'embedded',issues:[],
};}
async function setup(page:Page){
 const me={id:'cache-owner',username:'owner',display_name:'Cache owner',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false};
 const modules=Array.from({length:4},(_,i)=>({id:'c'+(i+1),name:i===0?'额度':'Cache '+(i+1),icon:'globe',adapter:'generic',origin:'https://c'+(i+1)+'.cache.test',mode:'iframe',browser_url:'https://cache.test/site/c'+(i+1),enabled:true,keep_alive:true,initial_path:'/',injection:{draft:null,active:null,previous:null},capabilities:{injection:false}}));
 const unknown:string[]=[],errors:string[]=[],requests:{path:string;method:string}[]=[],launches:string[]=[],frames:string[]=[];
 const holds=new Map<string,ReturnType<typeof deferred>>();
 page.on('pageerror',error=>errors.push(error.message));
 await page.routeWebSocket('**/*',socket=>{
  const u=new URL(socket.url());
  if(u.origin===ROOT.replace('http:','ws:')&&['/','/ws/notifications','/ws/list/'+workspaceId].includes(u.pathname))return;
  unknown.push(socket.url());socket.close();
 });
 await page.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url()),p=u.pathname,m=request.method();
  const key=m+' '+p;
  const ok=(json:unknown)=>route.fulfill({json});
  if(u.origin===ROOT&&m==='GET'&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||['/notes','/login','/apps/c1','/apps/c2','/apps/c3','/apps/c4'].includes(p)))return route.continue();
  if(u.origin==='https://cache.test'&&m==='GET'&&modules.some(item=>item.browser_url===u.href)){
   frames.push(p);
   if(holds.has('frame:'+p))await holds.get('frame:'+p)!.promise;
   return route.fulfill({contentType:'text/html',body:'<!doctype html><h1>额度卡片 '+p+'</h1><label>Draft<input aria-label="Draft"></label>'});
  }
  if(u.origin!==ROOT){unknown.push(m+' '+u.href);return route.abort('blockedbyclient');}
  requests.push({path:p,method:m});
  if(holds.has(key))await holds.get(key)!.promise;
  if(key==='GET /auth/me'||key==='POST /auth/refresh'||key==='POST /auth/login')return ok(me);
  if(key==='POST /auth/logout'||key==='POST /auth/activity')return ok({ok:true});
  if(key==='GET /auth/security')return ok({enabled:true,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
  if(key==='GET /navigation')return ok({entries:[],settings_route:'/settings'});
  if(key==='GET /external-modules')return ok(modules);
  if(key==='POST /website-settings/check')return ok(checked(request.postDataJSON().address));
  const item=modules.find(item=>p==='/external-modules/'+item.id||p==='/external-modules/'+item.id+'/launch');
  if(item&&m==='GET'&&p==='/external-modules/'+item.id)return ok(item);
  if(item&&m==='POST'&&p.endsWith('/launch')){launches.push(item.id);return ok({mode:item.mode,url:item.browser_url,method:'GET'});}
  if(key==='GET /notifications/unread-count')return ok({count:0});
  if(key==='GET /config/public-host'||key==='GET /config/site-background')return ok({value:''});
  if(key==='GET /auth/status')return ok({initialized:true,has_users:true});
  if(key==='GET /operations/backup-health')return ok({status:'unknown'});
  if(key==='GET /notes/preferences')return ok({});
  if(m==='GET'&&['/documents/recent','/documents/','/tags/','/doc-tags/'].includes(p))return ok([]);
  if(key==='GET /workspaces/')return ok([{id:workspaceId,name:'Cache notes',user_id:me.id}]);
  if(key==='GET /workspaces/'+workspaceId)return ok({id:workspaceId,name:'Cache notes',user_id:me.id});
  if(key==='GET /workspaces/'+workspaceId+'/tree')return ok([]);
  if(key==='GET /workspaces/'+workspaceId+'/stats')return ok({});
  if(key==='GET /workspaces/'+workspaceId+'/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(m==='GET'&&['/favicon.ico','/bg-home.webp','/avatar.png'].includes(p))return route.fulfill({status:204});
  unknown.push(m+' '+u.href);return route.abort('blockedbyclient');
 });
 return {unknown,errors,requests,launches,frames,modules,me,
  hold(key:string){const gate=deferred();holds.set(key,gate);return ()=>{holds.delete(key);gate.resolve();};},
  releaseAll(){for(const gate of holds.values())gate.resolve();holds.clear();},
 };
}
const test=base.extend<{fixture:Awaited<ReturnType<typeof setup>>}>({
 fixture:async({page},use,testInfo)=>{
  const fixture=await setup(page);
  try{await use(fixture);}finally{
   fixture.releaseAll();
   await testInfo.attach('mock-network',{body:JSON.stringify(fixture,null,2),contentType:'application/json'});
   expect(fixture.unknown,'No unknown or production requests').toEqual([]);
   expect(fixture.errors,'No browser page errors').toEqual([]);
  }
 },
});
const frame=(page:Page,id='c1')=>page.locator(`iframe[title="${id==='c1'?'额度':'Cache '+id.slice(1)}"]`);
const draft=(page:Page,id='c1')=>frame(page,id).contentFrame().getByLabel('Draft');

for(const mode of ['iframe','isolated_proxy'])test('clean embedded surface has content only: '+mode,async({page,fixture},testInfo)=>{
 if(mode==='isolated_proxy'){
  fixture.modules[0]!.mode='isolated_proxy';
  await page.route(ROOT+'/external-modules/c1/launch',route=>route.fulfill({json:{mode,url:'https://c1.cache.test/__stella/bootstrap',method:'POST',fields:{ticket:'synthetic-one-use-ticket'}}}));
  await page.route('https://c1.cache.test/__stella/bootstrap',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><h1>额度内容</h1><label>Draft<input aria-label="Draft"></label>'}));
 }
 await page.goto('/apps/c1');await expect(draft(page)).toBeVisible();
 const shell=page.locator('.external-page:visible');
 await expect(shell.locator('header,h1')).toHaveCount(0);
 await expect(shell.getByRole('button')).toHaveCount(0);
 await expect(shell.getByRole('link')).toHaveCount(0);
 await expect(shell.getByRole('status')).toHaveCount(0);
 await expect(shell).toHaveText('');
 expect(await shell.evaluate(el=>getComputedStyle(el).borderTopWidth)).toBe('0px');
 await expect(page.locator('.sidebar a.nav-item[href="/settings"]')).toBeVisible();
 await expect(page.locator('.sidebar a[href="/notes"]')).toBeVisible();
 await page.setViewportSize({width:390,height:852});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:testInfo.outputPath('content-only.png'),animations:'disabled'});
});

test('failed launch exposes a short error and manual recovery, then disappears',async({page,fixture})=>{
 let attempt=0;
 await page.route(ROOT+'/external-modules/c1/launch',route=>++attempt===1?route.fulfill({status:502,json:{detail:'upstream unavailable'}}):route.fulfill({json:{mode:'iframe',url:fixture.modules[0]!.browser_url,method:'GET'}}));
 await page.goto('/apps/c1');await expect(page.getByRole('alert')).toBeVisible();
 const shell=page.locator('.external-page:visible');
 await expect(shell.getByRole('link',{name:'连接设置',exact:true})).toHaveAttribute('href','/settings?section=navigation&module=c1');
 await shell.getByRole('button',{name:'重新连接',exact:true}).click();await expect(draft(page)).toBeVisible();
 await expect(shell.getByRole('alert')).toHaveCount(0);await expect(shell.getByRole('button')).toHaveCount(0);
 expect(attempt).toBe(2);
});

test('link-only website retains explicit open action without iframe or debug prose',async({page,fixture})=>{
 fixture.modules[0]!.mode='link';
 await page.goto('/apps/c1');const shell=page.locator('.external-page:visible');
 await expect(shell.getByRole('link',{name:'新窗口打开',exact:true})).toHaveAttribute('href',fixture.modules[0]!.browser_url);
 await expect(shell.locator('iframe,header')).toHaveCount(0);
 await expect(shell).not.toContainText('load');await expect(shell).not.toContainText('票据');
});

async function enter(page:Page,id='c1'){
 await page.locator(`.sidebar a[href="/apps/${id}"]`).click();
 await expect(page).toHaveURL(ROOT+'/apps/'+id);
}
async function refreshMe(page:Page){
 return page.evaluate(async()=>{
  const path='/src/modules/home/auth.ts';const {auth,fetchMe}=await import(path);
  const previous=auth.me,session=auth.sessionGeneration;
  const ok=await fetchMe();
  return {ok,replaced:auth.me!==previous,sameOwner:auth.me?.id===previous?.id,sameSession:auth.sessionGeneration===session};
 });
}

for(const keepAlive of [false,true])test(`same-owner fetchMe after load keeps exact iframe and input without relaunch (cached=${keepAlive})`,async({page,fixture})=>{
 fixture.modules[0]!.keep_alive=keepAlive;
 await page.goto('/apps/c1');await draft(page).fill('keep my quota card');
 const original=await frame(page).elementHandle();
 expect(await refreshMe(page)).toEqual({ok:true,replaced:true,sameOwner:true,sameSession:true});
 await expect(frame(page)).toBeVisible();
 expect(await frame(page).evaluate((current,old)=>current===old,original)).toBe(true);
 await expect(draft(page)).toHaveValue('keep my quota card');
 expect(fixture.launches).toEqual(['c1']);expect(fixture.frames).toEqual(['/site/c1']);
});

for(const stage of ['GET /external-modules/c1','POST /website-settings/check','POST /external-modules/c1/launch','frame:/site/c1'])test('same-owner fetchMe during '+stage+' does not cancel or duplicate the connection',async({page,fixture})=>{
 const release=fixture.hold(stage);
 await page.goto('/apps/c1',{waitUntil:'domcontentloaded'});
 await expect.poll(()=>stage.startsWith('frame:')?fixture.frames.includes('/site/c1'):fixture.requests.some(request=>request.method+' '+request.path===stage)).toBe(true);
 const original=stage.startsWith('frame:')?await frame(page).elementHandle():null;
 expect(await refreshMe(page)).toEqual({ok:true,replaced:true,sameOwner:true,sameSession:true});
 if(original){await expect(frame(page)).toBeVisible();expect(await original.evaluate(element=>element.isConnected)).toBe(true);}
 release();
 await expect(draft(page)).toBeVisible();
 expect(fixture.requests.filter(request=>request.path==='/external-modules/c1')).toHaveLength(1);
 expect(fixture.requests.filter(request=>request.path==='/website-settings/check')).toHaveLength(1);
 expect(fixture.launches).toEqual(['c1']);expect(fixture.frames).toEqual(['/site/c1']);
});

test('sidebar quota stays usable through a real 30-second App fetchMe watchdog',async({page,fixture},testInfo)=>{
 test.setTimeout(75000);
 await page.goto('/notes');await expect(page.locator('.notes-page')).toBeVisible();
 await enter(page);await draft(page).fill('retained past watchdog');
 const original=await frame(page).elementHandle();
 const probes=fixture.requests.filter(request=>request.path==='/auth/me').length;
 const started=Date.now();await page.waitForTimeout(31000); // Real wall time; no fake clock or manual fetchMe.
 const elapsedMs=Date.now()-started;
 expect(elapsedMs).toBeGreaterThanOrEqual(30000);
 expect(fixture.requests.filter(request=>request.path==='/auth/me').length).toBeGreaterThan(probes);
 await testInfo.attach('real-watchdog',{body:JSON.stringify({elapsedMs,authMeRequests:fixture.requests.filter(request=>request.path==='/auth/me').length}),contentType:'application/json'});
 await expect(frame(page)).toBeVisible();
 await expect(draft(page)).toHaveValue('retained past watchdog');
 expect(await frame(page).evaluate((current,old)=>current===old,original)).toBe(true);
 await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.notes-page')).toBeVisible();
 await enter(page);await expect(draft(page)).toHaveValue('retained past watchdog');
 expect(fixture.launches).toEqual(['c1']);expect(fixture.frames).toEqual(['/site/c1']);
 await page.screenshot({path:testInfo.outputPath('quota-after-watchdog.png'),animations:'disabled'});
});

for(const change of ['owner','same-owner login','same-tick logout/login'])test(change+' destroys old active and hidden frames',async({page,fixture})=>{
 await page.goto('/apps/c1');await draft(page).fill('old secret');const first=await frame(page).elementHandle();
 await enter(page,'c2');await draft(page,'c2').fill('other secret');const second=await frame(page,'c2').elementHandle();
 if(change==='owner'){
  fixture.me.id='other-owner';expect((await refreshMe(page)).sameOwner).toBe(false);
 }else await page.evaluate(async change=>{
  const path='/src/modules/home/auth.ts';const {auth,login}=await import(path);
  if(change==='same-owner login')await login('mock-owner','test-only-fixture',false);
  else{const owner=auth.me;auth.me=null;auth.me=owner;}
 },change);
 await expect.poll(()=>first!.evaluate(element=>element.isConnected)).toBe(false);
 await expect.poll(()=>second!.evaluate(element=>element.isConnected)).toBe(false);
 await expect(frame(page)).toHaveCount(0);
 await expect(draft(page,'c2')).toHaveValue('');
 await enter(page);await expect(draft(page)).toHaveValue('');
});

test('slow logout closes frames immediately and cancels pending launch before its response',async({page,fixture})=>{
 await page.goto('/apps/c1');await draft(page).fill('closing session');
 const releaseGet=fixture.hold('GET /external-modules/c2'),releaseLogout=fixture.hold('POST /auth/logout');
 await enter(page,'c2');await expect.poll(()=>fixture.requests.some(request=>request.path==='/external-modules/c2')).toBe(true);
 await page.evaluate(async()=>{const path='/src/modules/home/auth.ts';const {logout}=await import(path);void logout();});
 await expect.poll(()=>fixture.requests.some(request=>request.path==='/auth/logout')).toBe(true);
 await expect(page.locator('iframe')).toHaveCount(0);
 releaseGet();await page.waitForTimeout(200);
 expect(fixture.launches).toEqual(['c1']);await expect(page.locator('iframe')).toHaveCount(0);
 releaseLogout();
 await expect.poll(()=>page.evaluate(async()=>{const path='/src/modules/home/auth.ts';return (await import(path)).auth.me;})).toBeNull();
 await expect(page.locator('iframe')).toHaveCount(0);
});

test('hidden pending cached page pauses and reconnects only on explicit click without elevation',async({page,fixture})=>{
 await page.goto('/apps/c1');await draft(page).fill('retained first');
 const release=fixture.hold('GET /external-modules/c2');
 await enter(page,'c2');await expect.poll(()=>fixture.requests.some(request=>request.path==='/external-modules/c2')).toBe(true);
 await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.notes-page')).toBeVisible();
 release();await page.waitForTimeout(200);
 await enter(page,'c2');
 const reconnect=page.locator('.external-page:visible').getByRole('button',{name:'重新连接',exact:true});
 await expect(reconnect).toBeEnabled();await expect(frame(page,'c2')).toHaveCount(0);
 expect(fixture.launches).toEqual(['c1']);
 expect(fixture.requests.filter(request=>request.path==='/external-modules/c2')).toHaveLength(1);
 await reconnect.click();await expect(draft(page,'c2')).toBeVisible();
 expect(fixture.launches).toEqual(['c1','c2']);
 expect(fixture.requests.filter(request=>request.path==='/external-modules/c2')).toHaveLength(2);
 expect(fixture.requests.filter(request=>request.path.startsWith('/auth/admin/'))).toEqual([]);
 expect(await page.evaluate(async()=>{const path='/src/modules/home/auth.ts';return (await import(path)).isAdmin.value;})).toBe(false);
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await enter(page);await expect(draft(page)).toHaveValue('retained first');
});

test('paused page with expired grant cannot silently unlock or replay a protected launch',async({page,fixture})=>{
 await page.goto('/apps/c1');await expect(draft(page)).toBeVisible();
 const release=fixture.hold('GET /external-modules/c2');
 let blockedLaunches=0;
 await page.route(ROOT+'/external-modules/c2/launch',async route=>{
  blockedLaunches++;await route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
 });
 await enter(page,'c2');await expect.poll(()=>fixture.requests.some(request=>request.path==='/external-modules/c2')).toBe(true);
 await enter(page);release();await page.waitForTimeout(200);
 await enter(page,'c2');await expect(page.getByRole('dialog')).toHaveCount(0);expect(blockedLaunches).toBe(0);
 await page.locator('.external-page:visible').getByRole('button',{name:'重新连接',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'解锁管理权限'});await expect(dialog).toBeVisible();
 expect(blockedLaunches).toBe(1);await expect(dialog.getByLabel('管理密码',{exact:true})).toHaveValue('');
 await dialog.getByRole('button',{name:'取消',exact:true}).click();await expect(dialog).toHaveCount(0);
 await expect(page.getByRole('alert')).toContainText('未获授权');
 expect(blockedLaunches).toBe(1);expect(fixture.requests.filter(request=>request.path.startsWith('/auth/admin/'))).toEqual([]);
 await expect(frame(page,'c2')).toHaveCount(0);
});

test('same-owner probes keep hidden iframe DOM and existing LRU order',async({page,fixture})=>{
 await page.goto('/apps/c1');await draft(page).fill('one');
 await enter(page,'c2');await draft(page,'c2').fill('two');
 await enter(page,'c3');await draft(page,'c3').fill('three');
 await enter(page);const original=await frame(page).elementHandle();
 for(let i=0;i<3;i++)await refreshMe(page);
 await expect(draft(page)).toHaveValue('one');
 expect(await frame(page).evaluate((current,old)=>current===old,original)).toBe(true);
 expect(fixture.launches).toEqual(['c1','c2','c3']);
 await enter(page,'c4');await expect(draft(page,'c4')).toBeVisible();
 await expect(frame(page,'c2')).toHaveCount(0);await expect(page.locator('iframe')).toHaveCount(3);
 await enter(page,'c3');await expect(draft(page,'c3')).toHaveValue('three');
 await enter(page);await expect(draft(page)).toHaveValue('one');
 expect(fixture.launches).toEqual(['c1','c2','c3','c4']);
});
