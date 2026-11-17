import {test as base,expect,type Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
const ROOT='http://127.0.0.1:15286';
const test=base.extend<{network:{unknown:string[];errors:string[]}}>({network:[async({page},use)=>{const network={unknown:[] as string[],errors:[] as string[]};page.on('pageerror',e=>network.errors.push(e.message));await page.route('**/*',r=>{network.unknown.push(r.request().method()+' '+r.request().url());return r.abort('blockedbyclient');});await page.routeWebSocket('**/*',socket=>{const u=new URL(socket.url());if(u.origin===ROOT.replace('http:','ws:')&&(u.pathname==='/'||u.pathname==='/ws/notifications'||u.pathname==='/ws/list/11111111-1111-4111-8111-111111111111'))return;network.unknown.push(socket.url());socket.close();});try{await use(network);}finally{expect(network.unknown).toEqual([]);expect(network.errors).toEqual([]);}},{auto:true}]});
async function setup(page:Page,proxy=false){
 const clientPreferences=createClientPreferencesFixture();
 const me={id:'cache-owner',username:'owner',display_name:'Cache owner',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false};
 const modules=Array.from({length:5},(_,i)=>({id:'c'+(i+1),name:'Cache '+(i+1),icon:'globe',adapter:'generic',origin:'https://c'+(i+1)+'.cache.test',mode:proxy?'isolated_proxy':'iframe',browser_url:'https://cache.test/site/c'+(i+1),enabled:true,keep_alive:i===4?undefined:i!==0,initial_path:'/',injection:{draft:null,active:null,previous:null},capabilities:{injection:false}}));
 const launches:string[]=[];let delayGet=0;
 await page.route('**/*',async r=>{
  const u=new URL(r.request().url()),p=u.pathname,m=r.request().method();
  if(u.origin===ROOT&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||['/','/settings','/login','/notes'].includes(p)||p.startsWith('/apps/')||p==='/avatar.png'))return r.continue();
  const ok=(json:any)=>r.fulfill({json});
  if(u.hostname==='cache.test'||u.hostname.endsWith('.cache.test'))return r.fulfill({contentType:'text/html',body:'<!doctype html><h1>'+p+'</h1><label>Draft<input aria-label="Draft"></label><div style="height:2600px">Local browsing fixture, not a real drive</div>'});
  if(u.origin!==ROOT)return r.fallback();
  const preference=clientPreferences.respond(m,p+u.search);if(preference)return r.fulfill(preference);
  if(p==='/auth/me'||p==='/auth/refresh')return ok(me);
  if(p==='/auth/logout')return ok({ok:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
  if(p==='/navigation')return ok({entries:[],settings_route:'/settings'});
  if(m==='GET'&&p==='/website-templates'&&!u.search)return ok([]);
  if(p==='/website-settings/check'&&m==='POST')return ok({normalized_url:r.request().postDataJSON().address,name_suggestion:'Cache',access:{status:'reachable',http_status:200},embedding:{status:'allowed',reason_code:'no_observed_restriction',reason:'Fixture allowed'},injection:{status:'unsupported',reason:'Fixture direct'},can_save:true,recommended_behavior:'embedded',issues:[],help:null});
  if(/^\/website-settings\/c[1-5]$/.test(p)&&m==='PATCH'){const item=modules.find(x=>x.id===p.split('/')[2])!;const body=r.request().postDataJSON();Object.assign(item,{name:body.name,icon:body.icon,browser_url:body.address});if(body.keep_alive!==undefined)item.keep_alive=body.keep_alive;if(body.custom)item.injection.draft=body.custom;return ok(item);}
  if(p==='/external-modules'){
   if(m==='POST'){const body=r.request().postDataJSON();const item={...modules[0],...body,id:'copy'+modules.length};modules.push(item);return ok(item);}
   return ok(modules);
  }
  if(p.startsWith('/external-modules/')){
   const id=p.split('/')[2],item=modules.find(x=>x.id===id);if(!item)return r.fulfill({status:404,json:{detail:'missing'}});
   if(p.endsWith('/launch')){launches.push(id);return ok(item.mode==='isolated_proxy'?{mode:item.mode,url:item.origin+'/__stella/bootstrap',method:'POST',fields:{ticket:'mock-ticket-'+id}}:{mode:item.mode,url:item.browser_url,method:'GET'});}
   if(m==='PATCH'){Object.assign(item,r.request().postDataJSON());return ok(item);}
   if(delayGet)await new Promise(resolve=>setTimeout(resolve,delayGet));return ok(item);
  }
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/config/public-host'||p==='/config/site-background')return ok({value:''});
  if(p==='/auth/status')return ok({initialized:true,has_users:true});
  if(p==='/operations/backup-health')return ok({status:'unknown'});
  if(p==='/notes-preferences'&&m==='GET')return ok({revision:0,delete_action:'trash',ask_before_delete:true});
  if(p==='/notes-tools/templates/11111111-1111-4111-8111-111111111111/initialize'&&m==='POST')return ok({root_id:null,items:[],recent_ids:[]});
  if(p==='/web-projects/workspace/11111111-1111-4111-8111-111111111111/identities'&&m==='GET')return ok([]);
  if(p==='/detached-sources'&&u.search==='?workspace_id=11111111-1111-4111-8111-111111111111'&&m==='GET')return ok([]);
  if(p==='/workspaces/')return ok([{id:'11111111-1111-4111-8111-111111111111',name:'Cache notes',user_id:me.id}]);
  if(p.startsWith('/workspaces/'))return ok({id:'11111111-1111-4111-8111-111111111111',name:'Cache notes',user_id:me.id});
  if(p.endsWith('/tree'))return ok([]);
  if(p.endsWith('/stats'))return ok({});
  if(p.endsWith('/sessions/history'))return ok({items:[],total:0,page:1,page_size:20});
  if(p.endsWith('.webp')||p.endsWith('.png')||p.endsWith('.svg'))return r.fulfill({status:404,body:''});
  if(['/auth/sessions','/auth/avatars','/homebg/','/documents/','/documents/recent','/doc-tags/','/tags/'].includes(p)&&m==='GET')return ok([]);
  if(p==='/auth/email-service'&&m==='GET')return ok({ready:false});
  if(p==='/auth/activity'&&m==='POST')return ok({ok:true});
  return r.fallback();
 });
 await page.goto('/apps/c1');await expect(page.locator('iframe[title="Cache 1"]')).toBeVisible();
 return {modules,launches,setDelay:(ms:number)=>delayGet=ms};
}
async function go(page:Page,id:string){await page.locator(`.sidebar a[href="/apps/${id}"]`).click();await expect(page.locator(`iframe[title="Cache ${id.slice(1)}"]`)).toBeVisible();}
const draft=(page:Page,n:number)=>page.frameLocator(`iframe[title="Cache ${n}"]`).getByLabel('Draft');
async function update(page:Page,id:string,fields:any){await page.evaluate(async({id,fields})=>{const {navigation}=await import('/src/stores/navigation.ts');Object.assign(navigation.modules.find((x:any)=>x.id===id)!,fields);},{id,fields});}

test('automatic retention has no settings control for new or legacy websites',async({page})=>{
 const {modules}=await setup(page);await page.locator('.sidebar .nav-item[href="/settings"]').click();
 await page.getByRole('link',{name:'网站与访问',exact:true}).click();
 await page.getByRole('button',{name:'编辑 Cache 1',exact:true}).click();
 await expect(page.locator('.inline-editor')).not.toContainText('打开方式');await expect(page.locator('.inline-editor')).not.toContainText('新窗口打开');
 await expect(page.getByRole('checkbox',{name:/切页保留现场/})).toHaveCount(0);await expect(page.getByRole('button',{name:'保留现场说明',exact:true})).toHaveCount(0);
 await page.locator('.inline-editor').getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);expect(modules[0].keep_alive).toBe(false);
 await page.getByRole('button',{name:'＋ 添加网站',exact:true}).click();await expect(page.getByRole('checkbox',{name:/切页保留现场/})).toHaveCount(0);await page.locator('.inline-editor details.custom > summary').click();await expect(page.getByRole('checkbox',{name:'启用自定义代码',exact:true})).toHaveCount(1);await page.screenshot({path:(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/service-regression')+'/settings-no-retention-control.png'});
});

for(const id of ['c1','c5'])test(`automatic retention through notes preserves exact iframe, scroll and unsaved input (${id})`,async({page})=>{
 await setup(page);if(id==='c5')await go(page,id);
 const n=Number(id.slice(1)),frame=page.locator(`iframe[title="Cache ${n}"]`);await draft(page,n).fill('unsaved through notes');
 await frame.evaluate(el=>{(window as any).__retainedIframe=el;});
 await draft(page,n).evaluate(el=>el.ownerDocument.defaultView!.scrollTo(0,620));
 expect(await draft(page,n).evaluate(el=>el.ownerDocument.defaultView!.scrollY)).toBe(620);
 await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.notes-page')).toHaveAttribute('aria-busy','false');
 await go(page,id);await expect(draft(page,n)).toHaveValue('unsaved through notes');expect(await frame.evaluate(el=>el===(window as any).__retainedIframe)).toBe(true);
 expect(await draft(page,n).evaluate(el=>el.ownerDocument.defaultView!.scrollY)).toBe(620);
 await page.screenshot({path:(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/service-regression')+`/notes-retained-${id}.png`});
});

test('same-owner logout/login in one tick cannot revive old cached grants or input',async({page})=>{
 await setup(page);await draft(page,1).fill('old-session');await go(page,'c2');
 await page.evaluate(async()=>{const {auth}=await import('/src/modules/home/auth.ts');const owner=auth.me;auth.me=null;auth.me=owner;});
 await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(0);await go(page,'c1');await expect(draft(page,1)).toHaveValue('');
});

test('logout starts cleanup before slow response and aborts pending launch before a document is opened',async({page})=>{
 await setup(page);let release!:()=>void;const gate=new Promise<void>(resolve=>release=resolve);const opened:string[]=[];page.on('request',req=>{if(req.url()==='https://cache.test/site/c2')opened.push(req.url());});
 await page.route('**/external-modules/c2/launch',async r=>{await gate;await r.fulfill({json:{mode:'iframe',url:'https://cache.test/site/c2',method:'GET'}}).catch(()=>{});});
 const requested=page.waitForRequest('**/external-modules/c2/launch');await page.locator('.sidebar a[href="/apps/c2"]').click();await requested;
 await page.route('**/auth/logout',async r=>{await new Promise(resolve=>setTimeout(resolve,800));await r.fulfill({json:{ok:true}});});
 await page.evaluate(async()=>{const {logout}=await import('/src/modules/home/auth.ts');void logout();});
 await expect(page.locator('iframe')).toHaveCount(0,{timeout:500});release();await page.waitForTimeout(1400);expect(opened).toEqual([]);await expect(page.locator('iframe')).toHaveCount(0);
});

test('switch mode destroys old frame but obsolete false flags still retain embedded pages',async({page})=>{
 const {modules,launches}=await setup(page);await draft(page,1).fill('obsolete');
 modules[0].mode='link';await update(page,'c1',{mode:'link'});await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(0);
 modules[0].mode='iframe';modules[0].keep_alive=false;await update(page,'c1',{mode:'iframe',keep_alive:false});await expect(page.locator('iframe[title="Cache 1"]')).toBeVisible();await expect(draft(page,1)).toHaveValue('');
 await draft(page,1).fill('automatic');await go(page,'c2');await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(1);await go(page,'c1');await expect(draft(page,1)).toHaveValue('automatic');
 expect(launches.filter(x=>x==='c1')).toHaveLength(3);
});

for(const operation of ['hide','disable','delete'])test(operation+' immediately removes active and hidden cached module',async({page})=>{
 await setup(page);await go(page,'c2');
 await page.evaluate(async op=>{const {navigation}=await import('/src/stores/navigation.ts');if(op==='hide')navigation.entries=[{id:'c1',visible:false},{id:'c2',visible:false}];if(op==='disable')for(const m of navigation.modules)m.enabled=false;if(op==='delete')navigation.modules=[];},operation);
 await expect(page.locator('iframe')).toHaveCount(0);await expect(page.getByRole('alert')).toContainText('已禁用');
});

test('POST boot tickets target distinct module iframes and preserve earlier site',async({page})=>{
 const {launches}=await setup(page,true);await draft(page,1).fill('proxy-one');await go(page,'c2');await draft(page,2).fill('proxy-two');await go(page,'c1');await expect(draft(page,1)).toHaveValue('proxy-one');
 const names=await page.locator('iframe').evaluateAll(frames=>frames.map(f=>f.getAttribute('name')));expect(new Set(names).size).toBe(2);expect(launches).toEqual(['c1','c2']);
 expect(page.frames().some(f=>f.url()==='https://c1.cache.test/__stella/bootstrap')).toBe(true);expect(page.frames().some(f=>f.url()==='https://c2.cache.test/__stella/bootstrap')).toBe(true);
 await page.screenshot({path:(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/service-regression')+'/post-ticket-retained.png'});
});

test('15 minute hidden period cannot silently launch or renew or add persistent controls',async({page})=>{
 const {launches}=await setup(page,true);await draft(page,1).fill('pre-expiry');await go(page,'c2');
 await page.clock.install();await page.clock.fastForward(901000);expect(launches).toEqual(['c1','c2']);
 await go(page,'c1');await expect(draft(page,1)).toHaveValue('pre-expiry');expect(launches).toEqual(['c1','c2']);
 await expect(page.locator('.external-page:visible').getByRole('button',{name:'重新连接',exact:true})).toHaveCount(0);expect(launches).toEqual(['c1','c2']);
});

test('notes cache stays independent while all four external LRU entries churn',async({page})=>{
 await setup(page);await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.notes-page')).toHaveAttribute('aria-busy','false');
 await page.locator('.notes-page').evaluate(el=>{(window as any).__noteElement=el;el.setAttribute('data-cache-proof','same-notes-instance');});
 for(const id of ['c2','c3','c4','c1'])await go(page,id);
 await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.notes-page')).toHaveAttribute('data-cache-proof','same-notes-instance');
 expect(await page.locator('.notes-page').evaluate(el=>el===(window as any).__noteElement)).toBe(true);
});

test('explicit new same-owner login resets retained frames without UID change',async({page})=>{
 const {launches}=await setup(page);await draft(page,1).fill('old-cookie-session');await go(page,'c2');
 await page.route('**/auth/login',r=>r.fulfill({json:{id:'cache-owner',username:'owner',display_name:'Cache owner',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false}}));
 await page.evaluate(async()=>{const path='/src/modules/home/auth.ts';const {login}=await import(path);await login('mock-owner','mock-daily-fixture',false);});
 await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(0);await go(page,'c1');await expect(draft(page,1)).toHaveValue('');expect(launches.filter(id=>id==='c1')).toHaveLength(2);
});

test('three LRU iframes keep DOM input state and launches; fourth evicts only oldest',async({page})=>{
 const {launches}=await setup(page);await draft(page,1).fill('draft-one');
 await go(page,'c2');await draft(page,2).fill('draft-two');await go(page,'c3');await draft(page,3).fill('draft-three');
 await go(page,'c1');await expect(draft(page,1)).toHaveValue('draft-one');expect(launches).toEqual(['c1','c2','c3']);
 await go(page,'c4');expect(await page.locator('iframe').count()).toBe(3);await expect(page.locator('iframe[title="Cache 2"]')).toHaveCount(0);
 await go(page,'c3');await expect(draft(page,3)).toHaveValue('draft-three');await go(page,'c1');await expect(draft(page,1)).toHaveValue('draft-one');
 await page.screenshot({path:(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/service-regression')+'/retained-draft.png'});
 await go(page,'c2');await expect(draft(page,2)).toHaveValue('');expect(launches.filter(x=>x==='c2')).toHaveLength(2);
});
