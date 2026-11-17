/// <reference types="node" />
import {test,expect,type Page} from '@playwright/test';
import {writeFileSync} from 'node:fs';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
const base='http://127.0.0.1:15232',endpoint='/operations/backups/client-preferences';
const out=process.env.APPEARANCE_OUT??'/root/.hermes/cache/scratch/stella-appearance-feedback';
async function setup(page:Page){
 const prefs=createClientPreferencesFixture({storage:{stella_live2d:'off'},allowWrite:true});
 const unexpected:string[]=[],errors:string[]=[],consoleErrors:string[]=[],calls:{method:string;body?:any}[]=[];
 let fail=false,collide=false;
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
 await page.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!=='ws://127.0.0.1:15232'||u.pathname!='/ws/notifications'||u.search){unexpected.push(ws.url());ws.close({code:1008,reason:'Unknown isolated WebSocket'});}});
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  if(u.origin===base&&(p==='/'||p==='/settings'||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
  const allowed:Record<string,string[]>={'/auth/refresh':['POST'],'/auth/activity':['POST'],[endpoint]:['GET','PUT']};
  const queries:Record<string,string[]>={'/auth/sessions':['?current_only=true','?page=1&page_size=20&exclude_current=true'],'/auth/sessions/history':['?page=1&page_size=20']};
  if((req.method()!=='GET'&&!(allowed[p]||[]).includes(req.method()))||(u.search&&!(queries[p]||[]).includes(u.search))){unexpected.push(req.method()+' '+p+u.search);return route.fulfill({status:500,json:{detail:'Unknown fixture method/query'}});}
  const ok=(json:any)=>route.fulfill({json});
  if(u.origin!==base){unexpected.push(req.url());return route.abort();}
  if(p===endpoint){
   const body=req.method()==='PUT'?req.postDataJSON():undefined;calls.push({method:req.method(),body});
   if(req.method()==='PUT'&&fail)return route.fulfill({status:503,json:{detail:'暂时离线，配色仍保留在本机'}});
   if(req.method()==='PUT'&&collide){collide=false;const current=prefs.respond('GET',endpoint)!.json;const {revision,...content}=current;prefs.respond('PUT',endpoint,{...content,home:{...content.home,siteTitle:'另一设备标题'},ui:{...content.ui,sidebarFold:true},expected_revision:revision});return route.fulfill({status:409,json:{detail:'revision changed'}});}
   const result=prefs.respond(req.method(),p,body);if(result)return route.fulfill(result);
  }
  if(p==='/auth/status')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'fixture-owner',username:'云曦',is_admin:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,single_user:true});
  if(p==='/navigation')return ok({entries:[],legacy_routes:{}});
  if(p==='/external-modules')return ok([]);
  if(p==='/config/home')return ok({value:JSON.stringify({live2d:false})});
  if(['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/avatar.png')return route.fulfill({status:204});
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/auth/email-service')return ok({ready:false});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(['/auth/sessions','/auth/avatars','/homebg/'].includes(p))return ok([]);
  if(p==='/homebg/media')return ok({source:'',poster:''});
  if(p.startsWith('/assets/homebg/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="900"><rect width="1440" height="900" fill="#191a20"/></svg>'});
  unexpected.push(req.method()+' '+p);return route.fulfill({status:500,json:{detail:'Unknown isolated fixture request'}});
 });
 await page.addInitScript(()=>localStorage.setItem('stella_live2d','off'));
 return {calls,unexpected,errors,consoleErrors,set fail(value:boolean){fail=value;},set collide(value:boolean){collide=value;}};
}
async function open(page:Page){await page.goto('/settings?section=appearance');await expect(page.getByRole('heading',{name:/^全站外观/})).toBeVisible();await expect(page.locator('.appearance-sync')).toContainText('账号已同步');await expect(page.locator('main .page')).toHaveCSS('opacity','1');}
async function readback(page:Page){return page.evaluate(async()=>{const response=await fetch('/operations/backups/client-preferences');return response.json();});}
async function bounds(page:Page,selector:string){const geometry=await page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,w:innerWidth,h:innerHeight,scroll:el.scrollWidth,client:el.clientWidth};});expect(geometry.left).toBeGreaterThanOrEqual(0);expect(geometry.right).toBeLessThanOrEqual(geometry.w+1);expect(geometry.scroll).toBeLessThanOrEqual(geometry.client+1);return geometry;}
for(const [width,height] of [[1365,960],[1920,1080],[390,844],[320,640],[1365,420]])test(`real App color autosave and geometry ${width}x${height}`,async({page})=>{
 const m=await setup(page);await page.setViewportSize({width,height});await open(page);
 await bounds(page,'.appearance-settings');await bounds(page,'.appearance-sandbox');
 const busy=page.locator('.appearance-sandbox [aria-busy=true]');await expect(busy).toHaveAttribute('aria-busy','true');
 const spinner=await busy.evaluate(el=>{const pseudo=['::before','::after'].map(p=>{const s=getComputedStyle(el,p);return {content:s.content,display:s.display,animation:s.animationName,width:s.width,position:s.position};});const descendants=[...el.querySelectorAll('*')].filter(e=>getComputedStyle(e).animationName!=='none');return {pseudo,svgCount:[...el.querySelectorAll('svg')].filter(e=>e.getClientRects().length>0&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden').length,children:el.children.length,count:pseudo.filter(s=>s.content!=='none'&&s.content!=='normal'&&s.display!=='none'&&s.animation!=='none').length+descendants.length};});expect(spinner.count).toBe(1);expect(spinner.children).toBe(0);expect(spinner.svgCount).toBe(0);expect(spinner.pseudo[1]!.position).toBe('static');
 await page.mouse.move(0,0);await page.screenshot({path:out+`/appearance-${width}x${height}.png`});
 await busy.scrollIntoViewIfNeeded();await page.screenshot({path:out+`/processing-${width}x${height}.png`});
 const before=m.calls.filter(c=>c.method==='PUT').length;
 await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();await expect(page.getByLabel('颜色值',{exact:true})).toBeFocused();expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(before);
 await page.getByLabel('颜色值',{exact:true}).fill('#A7CDF5');await expect(page.locator('html')).toHaveAttribute('data-appearance','custom');
 // No done, close or blur is needed for the account write and confirmed GET.
 await expect(page.locator('.appearance-sync')).toContainText('账号已同步');const saved=await readback(page);expect(saved.customAppearance.overrides['button-top']).toBe('#A7CDF5');expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(before+1);
 const p=await bounds(page,'.color-panel');expect(p.top).toBeGreaterThanOrEqual(0);expect(p.bottom).toBeLessThanOrEqual(height);await page.mouse.move(0,0);await page.screenshot({path:out+`/picker-${width}x${height}.png`});
 await page.reload();await expect(page.locator('html')).toHaveAttribute('data-appearance','custom');expect((await readback(page)).customAppearance.overrides['button-top']).toBe('#A7CDF5');await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();await expect(page.getByLabel('颜色值',{exact:true})).toHaveValue('#A7CDF5');
 await page.getByRole('button',{name:'关闭调色器'}).click();await expect(page.getByRole('button',{name:'调色：主按钮',exact:true})).toBeFocused();
 await page.getByRole('switch',{name:'调色模式',exact:true}).click();await expect(page.getByRole('switch',{name:'调色模式',exact:true})).toHaveAttribute('aria-checked','false');
 await page.reload();await expect(page.locator('html')).toHaveAttribute('data-appearance','custom');await expect(page.getByRole('switch',{name:'调色模式',exact:true})).toHaveAttribute('aria-checked','false');
 await page.getByRole('button',{name:/B · 鸢尾蓝/}).click();await expect(page.locator('.appearance-sync')).toContainText('账号已同步');await page.getByRole('button',{name:'自定义',exact:true}).click();await expect(page.locator('.appearance-sync')).toContainText('账号已同步');expect((await readback(page)).customAppearance.overrides['button-top']).toBe('#A7CDF5');
 expect(m.unexpected).toEqual([]);expect(m.errors).toEqual([]);expect(m.consoleErrors).toEqual([]);
 writeFileSync(out+`/receipt-${width}x${height}.json`,JSON.stringify({width,height,spinner,calls:m.calls,unexpected:m.unexpected,errors:m.errors},null,2));
});
for(const [width,height] of [[1365,280],[320,360]])test(`short viewport invalid color and focus recovery ${width}x${height}`,async({page})=>{
 const m=await setup(page);await page.setViewportSize({width,height});await open(page);await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();
 await page.getByLabel('颜色值',{exact:true}).fill('#ECECF3');await expect(page.getByRole('button',{name:'低对比度提醒',exact:true})).toBeVisible();await expect(page.locator('.appearance-sync')).toContainText('账号已同步');const writes=m.calls.filter(c=>c.method==='PUT').length;
 await page.getByLabel('颜色值',{exact:true}).fill('#12');await expect(page.getByLabel('颜色值',{exact:true})).toHaveAttribute('aria-invalid','true');const box=await bounds(page,'.color-panel');expect(box.top).toBeGreaterThanOrEqual(0);expect(box.bottom).toBeLessThanOrEqual(height);
 await page.getByRole('button',{name:'重置此颜色'}).focus();const reset=await page.getByRole('button',{name:'重置此颜色'}).boundingBox();expect(reset!.y).toBeGreaterThanOrEqual(box.top);expect(reset!.y+reset!.height).toBeLessThanOrEqual(height);await page.screenshot({path:out+`/invalid-${width}x${height}.png`});
 await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'调色：主按钮',exact:true})).toBeFocused();expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(writes);await page.reload();await expect(page.locator('html')).toHaveAttribute('data-appearance','custom');expect((await readback(page)).customAppearance.overrides['button-top']).toBe('#ECECF3');expect(m.unexpected).toEqual([]);expect(m.errors).toEqual([]);
});
test('picker input burst coalesces one HTTP write; invalid/same value/object/mode are no-ops',async({page})=>{
 const m=await setup(page);await open(page);await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();
 const before=m.calls.filter(c=>c.method==='PUT').length;await page.clock.install();
 // Simulates the native picker input stream, not an OS-native chooser test.
 for(let i=0;i<32;i++){await page.getByLabel('选取颜色',{exact:true}).evaluate((el,i)=>{const input=el as HTMLInputElement;input.value='#A7CD'+i.toString(16).padStart(2,'0');input.dispatchEvent(new Event('input',{bubbles:true}));},i);await page.clock.runFor(8);}
 expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(before);await page.clock.runFor(500);await expect(page.locator('.appearance-sync')).toContainText('账号已同步');expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(before+1);expect((await readback(page)).customAppearance.overrides['button-top']).toBe('#A7CD1F');
 await page.getByLabel('颜色值',{exact:true}).fill('#12');await expect(page.getByLabel('颜色值',{exact:true})).toHaveAttribute('aria-invalid','true');await page.clock.runFor(600);expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(before+1);
 await page.getByRole('button',{name:'关闭调色器'}).click();await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();await page.getByLabel('颜色值',{exact:true}).fill('#A7CD1F');await page.keyboard.press('Escape');await page.getByRole('switch',{name:'调色模式',exact:true}).click();await page.clock.runFor(600);expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(before+1);expect(m.unexpected).toEqual([]);expect(m.errors).toEqual([]);
});
test('failed sync retains current color through reload and offers one contextual narrow recovery',async({page})=>{
 const m=await setup(page);await page.setViewportSize({width:390,height:844});await open(page);m.fail=true;
 await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();await page.getByLabel('颜色值',{exact:true}).fill('#A7CDF5');await expect(page.locator('.appearance-sync')).toContainText('同步失败，本机配色已保存');await expect(page.locator('[data-appearance-retry]')).toHaveCount(1);await expect(page.locator('[data-client-preferences]')).toHaveCount(0);await expect(page.getByLabel('颜色值',{exact:true})).toHaveValue('#A7CDF5');await expect(page.locator('.color-panel')).toHaveCount(1);await page.getByRole('button',{name:'关闭调色器'}).click();
 await page.screenshot({path:out+'/sync-failure-390.png'});m.fail=false;await page.reload();await expect(page.locator('html')).toHaveAttribute('data-appearance','custom');await expect(page.locator('.appearance-sync')).toContainText('其他设备已更改');
 await page.locator('.appearance-conflict summary').click();await bounds(page,'.appearance-conflict>div');await page.screenshot({path:out+'/conflict-390.png'});await page.getByRole('button',{name:'同步当前配色'}).click();await expect(page.locator('.appearance-sync')).toContainText('账号已同步');expect((await readback(page)).customAppearance.overrides['button-top']).toBe('#A7CDF5');expect(m.unexpected).toEqual([]);expect(m.errors).toEqual([]);
});
test('CAS rebases appearance without overwriting another device home/ui',async({page})=>{
 const m=await setup(page);await open(page);m.collide=true;await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();await page.getByLabel('颜色值',{exact:true}).fill('#A7CDF5');await expect(page.locator('.appearance-sync')).toContainText('账号已同步');const saved=await readback(page);expect(saved.customAppearance.overrides['button-top']).toBe('#A7CDF5');expect(saved.home.siteTitle).toBe('另一设备标题');expect(saved.ui.sidebarFold).toBe(true);expect(m.calls.filter(c=>c.method==='PUT')).toHaveLength(2);expect(m.unexpected).toEqual([]);expect(m.errors).toEqual([]);
});
test('appearance fixture rejects unknown API method, query and WebSocket',async({page})=>{const m=await setup(page);await open(page);const result=await page.evaluate(async()=>{const codes=[];for(const [url,method] of [['/auth/me?unknown=1','GET'],['/auth/me','POST']])codes.push((await fetch(url!,{method})).status);await new Promise<void>(resolve=>{const ws=new WebSocket('ws://127.0.0.1:15232/ws/notifications?unknown=1');ws.onclose=()=>resolve();ws.onerror=()=>resolve();});return codes;});expect(result).toEqual([500,500]);expect(m.unexpected).toEqual(['GET /auth/me?unknown=1','POST /auth/me','ws://127.0.0.1:15232/ws/notifications?unknown=1']);expect(m.errors).toEqual([]);});
