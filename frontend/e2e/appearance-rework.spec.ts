import {test,expect} from '@playwright/test';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
const base='http://127.0.0.1:15189';
async function setup(page:any) {
 const clientPreferences=createClientPreferencesFixture({storage:{stella_live2d:'off'},allowWrite:true});
 const unexpected:string[]=[];const errors:string[]=[];
 page.on('pageerror',(e:any)=>errors.push(e.message));
 await page.routeWebSocket('**/*',(ws:any)=>{if(new URL(ws.url()).pathname!='/ws/notifications')unexpected.push(ws.url());});
 await page.route('**/*',async(route:any)=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  if(u.origin===base&&(p==='/'||p==='/settings'||p.startsWith('/static/')||p==='/favicon.svg'))return route.continue();
  const ok=(data:any)=>route.fulfill({json:data});
  if(u.origin!==base){unexpected.push(req.url());return route.abort();}
  const preference=clientPreferences.respond(req.method(),p+u.search,req.method()==='PUT'?req.postDataJSON():undefined);if(preference)return route.fulfill(preference);
  if(p==='/auth/status')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'fixture-owner',username:'云曦',is_admin:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,single_user:true});
  if(p==='/navigation')return ok({entries:[],legacy_routes:{}});
  if(p==='/external-modules')return ok([]);
  if(p==='/config/home')return ok({value:JSON.stringify({live2d:false})});
  if(['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(p==='/notifications/unread-count')return ok({count:1});
  if(p==='/notifications')return ok([{id:1,title:'测试通知',body:'通知应该在内容上层',severity:'info',ts:new Date().toISOString(),read:false,link:null}]);
  if(p==='/avatar.png')return route.continue();
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/auth/email-service')return ok({ready:false});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(['/auth/sessions','/auth/avatars','/homebg/'].includes(p))return ok([]);
  if(p==='/homebg/media')return ok({source:'',poster:''});
  if(p.startsWith('/assets/homebg/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="900"><rect width="1440" height="900" fill="#191a20"/></svg>'});
  unexpected.push(req.method()+' '+p);return route.fulfill({status:500,json:{detail:'Unknown isolated fixture'}});
 });
 await page.addInitScript(()=>{localStorage.setItem('stella_live2d','off');});
 return {unexpected,errors};
}
for(const width of [1440,393])test(`appearance and bell ${width}`,async({page})=>{
 const m=await setup(page);await page.setViewportSize({width,height:960});
 await page.goto('/settings?section=appearance');
 await expect(page.getByRole('heading',{name:'全站外观'})).toBeVisible();
 await expect(page.locator('html')).toHaveAttribute('data-appearance','A');
 const saved=page.waitForResponse(r=>r.url()===base+'/operations/backups/client-preferences'&&r.request().method()==='PUT'&&r.request().postDataJSON().appearance==='B');
 await page.getByRole('button',{name:/B · 鸢尾蓝/}).click();
 await expect(page.locator('html')).toHaveAttribute('data-appearance','B');
 expect((await saved).status()).toBe(200);
 const stored=await page.evaluate(async()=>{const r=await fetch('/operations/backups/client-preferences');return r.json();});expect(stored.appearance).toBe('B');
 await page.reload();await expect(page.locator('html')).toHaveAttribute('data-appearance','B');
 if(width<769)await page.getByRole('button',{name:'打开导航',exact:true}).click();
 const bell=page.getByRole('button',{name:'通知',exact:true});await bell.click();
 const panel=page.getByRole('dialog',{name:'通知',exact:true});await expect(panel).toBeVisible();
 const geometry=await panel.evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,hit:el.contains(document.elementFromPoint(r.left+r.width/2,r.top+20)),w:innerWidth,h:innerHeight};});
 expect(geometry.hit).toBe(true);expect(geometry.left).toBeGreaterThanOrEqual(0);expect(geometry.right).toBeLessThanOrEqual(geometry.w);expect(geometry.bottom).toBeLessThanOrEqual(geometry.h);
 await page.screenshot({path:process.env.APPEARANCE_OUT+`/bell-${width}.png`});
 await page.keyboard.press('Escape');await expect(panel).not.toBeVisible();
 if(width<769)await page.getByRole('button',{name:'收起导航',exact:true}).click();
 await page.goto('/settings?section=navigation');
 await page.getByRole('button',{name:'编辑 个人主页',exact:true}).click();
 const editor=page.locator('.inline-editor').first();
 await expect(editor.getByLabel('显示名称',{exact:true})).toBeVisible();
 const editorBox=await editor.boundingBox();expect(editorBox!.height).toBeLessThan(width<769?390:260);
 const nameBox=await editor.getByLabel('显示名称',{exact:true}).boundingBox();
 if(width>=769){const previewBox=await editor.getByLabel('侧栏效果',{exact:true}).boundingBox();expect(Math.abs(previewBox!.y-nameBox!.y)).toBeLessThan(70);}
 await page.screenshot({path:process.env.APPEARANCE_OUT+`/navigation-${width}.png`});
 await page.goto('/');
 const tarot=page.getByTitle('今日塔罗',{exact:true}),settings=page.getByRole('button',{name:'主页设置',exact:true});await expect(tarot).toBeVisible();await expect(settings).toBeVisible();
 const a=await tarot.boundingBox(),b=await settings.boundingBox();expect(Math.abs(a!.y-b!.y)).toBeLessThan(2);expect(a!.height).toBe(b!.height);
 await settings.click();await expect(page.getByRole('heading',{name:'主页设置',exact:true})).toBeVisible();await expect(page.getByText('海岸线',{exact:true})).toHaveCount(0);
 expect(m.unexpected).toEqual([]);expect(m.errors).toEqual([]);
});
