import {test,expect,type Page} from '@playwright/test';
const ROOT='http://127.0.0.1:15286';
async function setup(page:Page,proxy=false){
 const me={id:'cache-owner',username:'owner',display_name:'Cache owner',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false};
 const modules=Array.from({length:5},(_,i)=>({id:'c'+(i+1),name:'Cache '+(i+1),icon:'globe',adapter:'generic',origin:'https://c'+(i+1)+'.cache.test',mode:proxy?'isolated_proxy':'iframe',browser_url:'https://cache.test/site/c'+(i+1),enabled:true,keep_alive:i<4,initial_path:'/',injection:{draft:null,active:null,previous:null},capabilities:{injection:false}}));
 const launches:string[]=[];let delayGet=0;
 await page.route('**/*',async r=>{
  const u=new URL(r.request().url()),p=u.pathname,m=r.request().method();
  if(u.origin===ROOT&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||['/','/settings','/login','/notes'].includes(p)||p.startsWith('/apps/')))return r.continue();
  const ok=(json:any)=>r.fulfill({json});
  if(u.hostname==='cache.test'||u.hostname.endsWith('.cache.test'))return r.fulfill({contentType:'text/html',body:'<!doctype html><h1>'+p+'</h1><label>Draft<input aria-label="Draft"></label>'});
  if(p==='/auth/me'||p==='/auth/refresh')return ok(me);
  if(p==='/auth/logout')return ok({ok:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,expires_at:null,single_user:true,setup_required:false});
  if(p==='/navigation')return ok({entries:[],settings_route:'/settings'});
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
  if(p==='/notes/preferences')return ok({});
  if(p==='/workspaces/')return ok([{id:'11111111-1111-4111-8111-111111111111',name:'Cache notes',user_id:me.id}]);
  if(p.startsWith('/workspaces/'))return ok({id:'11111111-1111-4111-8111-111111111111',name:'Cache notes',user_id:me.id});
  if(p.endsWith('/tree'))return ok([]);
  if(p.endsWith('/stats'))return ok({});
  if(p.endsWith('/sessions/history'))return ok({items:[],total:0,page:1,page_size:20});
  if(p.endsWith('.webp')||p.endsWith('.png')||p.endsWith('.svg'))return r.fulfill({status:404,body:''});
  return ok([]);
 });
 await page.goto('/apps/c1');await expect(page.locator('iframe[title="Cache 1"]')).toBeVisible();
 return {modules,launches,setDelay:(ms:number)=>delayGet=ms};
}
async function go(page:Page,id:string){await page.locator(`.sidebar a[href="/apps/${id}"]`).click();await expect(page.locator(`iframe[title="Cache ${id.slice(1)}"]`)).toBeVisible();}
const draft=(page:Page,n:number)=>page.frameLocator(`iframe[title="Cache ${n}"]`).getByLabel('Draft');
async function update(page:Page,id:string,fields:any){await page.evaluate(async({id,fields})=>{const {navigation}=await import('/src/stores/navigation.ts');Object.assign(navigation.modules.find((x:any)=>x.id===id)!,fields);},{id,fields});}

test('settings edits and copies persist opt-in; fresh form defaults off',async({page})=>{
 const {modules}=await setup(page);await page.locator('.sidebar .nav-item[href="/settings"]').click();
 await page.getByRole('button',{name:'导航与网站',exact:true}).click();
 await page.getByRole('button',{name:'编辑 Cache 1',exact:true}).click();
 const toggle=page.getByRole('checkbox',{name:'切页保留现场（最多 3 个网站）'});await expect(toggle).toBeChecked();
 await toggle.uncheck();await page.getByRole('button',{name:'应用接入变更',exact:true}).click();expect(modules[0].keep_alive).toBe(false);
 await page.getByRole('button',{name:'编辑 Cache 1',exact:true}).click();await toggle.check();await page.getByRole('button',{name:'应用接入变更',exact:true}).click();
 await page.getByRole('button',{name:'复制 Cache 1',exact:true}).click();await expect(page.getByRole('main').getByText('Cache 1 副本',{exact:true})).toBeVisible();expect(modules.at(-1)?.keep_alive).toBe(true);
 await page.getByRole('button',{name:'新增网站',exact:true}).click();await expect(toggle).not.toBeChecked();
});

test('same-owner logout/login in one tick cannot revive old cached grants or input',async({page})=>{
 await setup(page);await draft(page,1).fill('old-session');await go(page,'c2');
 await page.evaluate(async()=>{const {auth}=await import('/src/modules/home/auth.ts');const owner=auth.me;auth.me=null;auth.me=owner;});
 await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(0);await go(page,'c1');await expect(draft(page,1)).toHaveValue('');
});

test('logout starts cleanup before slow response and aborts pending get before launch',async({page})=>{
 const {launches,setDelay}=await setup(page);setDelay(1200);
 await page.locator('.sidebar a[href="/apps/c2"]').click();
 await page.route('**/auth/logout',async r=>{await new Promise(resolve=>setTimeout(resolve,800));await r.fulfill({json:{ok:true}});});
 await page.evaluate(async()=>{const {logout}=await import('/src/modules/home/auth.ts');void logout();});
 await expect(page.locator('iframe')).toHaveCount(0,{timeout:500});await page.waitForTimeout(1400);expect(launches).toEqual(['c1']);
});

test('switch mode or turn off retention destroys old frame; noncached pages unload on leave',async({page})=>{
 const {modules,launches}=await setup(page);await draft(page,1).fill('obsolete');
 modules[0].mode='link';await update(page,'c1',{mode:'link'});await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(0);
 modules[0].mode='iframe';modules[0].keep_alive=false;await update(page,'c1',{mode:'iframe',keep_alive:false});await expect(page.locator('iframe[title="Cache 1"]')).toBeVisible();await expect(draft(page,1)).toHaveValue('');
 await draft(page,1).fill('uncached');await go(page,'c2');await expect(page.locator('iframe[title="Cache 1"]')).toHaveCount(0);await go(page,'c1');await expect(draft(page,1)).toHaveValue('');
 expect(launches.filter(x=>x==='c1')).toHaveLength(4);
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
 await page.screenshot({path:'/opt/hermes-workstation/docs/2026-10-06-Stella-upgrade/iframe-cache/post-ticket-retained.png'});
});

test('15 minute hidden period cannot silently launch or renew or add persistent controls',async({page})=>{
 const {launches}=await setup(page,true);await draft(page,1).fill('pre-expiry');await go(page,'c2');
 await page.clock.install();await page.clock.fastForward(901000);expect(launches).toEqual(['c1','c2']);
 await go(page,'c1');await expect(draft(page,1)).toHaveValue('pre-expiry');expect(launches).toEqual(['c1','c2']);
 await expect(page.locator('.external-page:visible').getByRole('button',{name:'重新连接',exact:true})).toHaveCount(0);expect(launches).toEqual(['c1','c2']);
});

test('notes cache stays independent while all four external LRU entries churn',async({page})=>{
 await setup(page);await page.locator('.sidebar a[href="/notes"]').click();await expect(page.locator('.notes-page')).toBeVisible();
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
 await page.screenshot({path:'/opt/hermes-workstation/docs/2026-10-06-Stella-upgrade/iframe-cache/retained-draft.png'});
 await go(page,'c2');await expect(draft(page,2)).toHaveValue('');expect(launches.filter(x=>x==='c2')).toHaveLength(2);
});
