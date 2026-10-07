import {test as base,expect,type Page} from '@playwright/test';
import {mock} from './settings-mocks';
import {serviceFixture} from '../tests/fixtures/serviceSettings';
const ROOT='http://127.0.0.1:15173';
async function setup(page:Page){
 const m=await mock(page);const errors:string[]=[],visits:string[]=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.routeWebSocket('**/*',socket=>{const u=new URL(socket.url());if(u.origin===ROOT.replace('http:','ws:')&&['/','/ws/notifications'].includes(u.pathname))return;m.unknown.push(socket.url());socket.close();});
 const states:Record<string,any>={drive:serviceFixture('drive'),gallery:serviceFixture('gallery')};
 const failures={read:false,write:0,uncertain:false};let version=0;
 await page.route(ROOT+'/service-settings/**',async route=>{
  const req=route.request(),p=new URL(req.url()).pathname,site=p.split('/')[2]!,state=states[site],method=req.method(),body=req.postDataJSON();
  m.requests.push({path:p,method,body});
  if(!state){m.unknown.push(p);return route.abort('blockedbyclient');}
  if(p.endsWith('/check')&&method==='POST')return route.fulfill({json:{ok:true,message:'当前草稿服务端可访问'}});
  if(p!==`/service-settings/${site}`){m.unknown.push(p);return route.abort('blockedbyclient');}
  if(method==='PUT'){
   if(!m.state.elevated)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
   if(failures.write)return route.fulfill({status:failures.write,json:{detail:'地址或代码校验失败，所有设置未变更'}});
   const {token,clear_token,...connection}=body.connection;
   Object.assign(state,{name:body.name,icon:body.icon,visible:body.visible,appearance:body.appearance,connection:{...connection,...(site==='drive'?{has_token:clear_token?false:!!token||state.connection.has_token}:{})}});
   m.setEntry({id:site,title:state.name,icon:state.icon,visible:state.visible});
   if(body.custom){state.injection.previous={...state.injection.active,status:'revoked'};state.injection.active={...body.custom,version:'version-'+(++version),status:'active'};}
   if(failures.uncertain)return route.abort('connectionreset');
  }else if(method!=='GET'){m.unknown.push(method+' '+p);return route.abort('blockedbyclient');}
  if(method==='GET'&&failures.read)return route.fulfill({status:503,json:{detail:'read unavailable'}});
  return route.fulfill({json:state});
 });
 await page.route(ROOT+'/builtin-injections/*/*',route=>{
  const req=route.request(),p=new URL(req.url()).pathname,site=p.split('/')[2]!,state=states[site],body=req.postDataJSON();m.requests.push({path:p,method:req.method(),body});
  if(req.method()!=='POST'||!state){m.unknown.push(p);return route.abort('blockedbyclient');}
  if(!m.state.elevated)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
  if(p.endsWith('/validate')){state.injection.draft=body;return route.fulfill({json:{valid:true,errors:[],draft:body}});}
  if(p.endsWith('/rollback')){[state.injection.active,state.injection.previous]=[{...state.injection.previous,status:'active'},{...state.injection.active,status:'revoked'}];return route.fulfill({json:state.injection});}
  m.unknown.push(p);return route.abort('blockedbyclient');
 });
 for(const p of ['/drive/openlist/','/gallery/connect'])await page.route(ROOT+p,route=>{visits.push(p);return route.continue();});
 return {...m,states,errors,visits,failures};
}
const test=base.extend<{fixture:Awaited<ReturnType<typeof setup>>}>({fixture:async({page},use,testInfo)=>{
 const fixture=await setup(page);try{await use(fixture);}finally{await testInfo.attach('isolated-network',{body:JSON.stringify(fixture,null,2),contentType:'application/json'});expect(fixture.unknown).toEqual([]);expect(fixture.errors).toEqual([]);}
}});
const editor=(page:Page)=>page.locator('.service-editor');
async function previewShot(page:Page,path:string){await editor(page).getByLabel('外观示意预览').scrollIntoViewIfNeeded();await page.screenshot({path,animations:'disabled'});}

for(const site of ['drive','gallery'])test('clean shell contains only owned HTTP iframe: '+site,async({page,fixture},testInfo)=>{
 await page.goto('/'+site);const frame=page.locator('iframe');await expect(frame.contentFrame().getByRole('heading',{name:/Owned .* fixture/})).toBeVisible();
 const shell=page.locator('.'+site+'-page');await expect(shell).toHaveText('');await expect(shell.locator('button,a,header')).toHaveCount(0);expect(await frame.evaluate(el=>getComputedStyle(el).borderTopWidth)).toBe('0px');
 expect(fixture.visits).toEqual([site==='drive'?'/drive/openlist/':'/gallery/connect']);
 await page.screenshot({path:testInfo.outputPath(site+'-desktop.png'),animations:'disabled'});
 await page.setViewportSize({width:390,height:852});await page.screenshot({path:testInfo.outputPath(site+'-mobile.png'),animations:'disabled'});
});
test('ordinary owner sees service categories and one unified form without elevation',async({page,fixture})=>{
 await page.goto('/settings?section=navigation');
 await expect(page.locator('[data-row-id="drive"]')).toContainText('OpenList · 接入服务');await expect(page.locator('[data-row-id="gallery"]')).toContainText('Immich · 接入服务');await expect(page.locator('[data-row-id="notes"]')).toContainText('内置页面');
 await page.getByRole('button',{name:'编辑 网盘',exact:true}).click();await expect(editor(page).getByLabel('显示名称')).toHaveValue('网盘');
 expect(fixture.requests.some(x=>x.path==='/drive/connection'||x.path==='/builtin-injections/drive'||x.path.includes('/token'))).toBe(false);
 await expect(page.getByRole('dialog')).toHaveCount(0);expect(fixture.requests.filter(x=>x.path.startsWith('/auth/admin/'))).toEqual([]);
 await expect(page.locator('.inline-editor')).toHaveCount(1);await expect(editor(page).locator('.advanced')).not.toHaveAttribute('open');
});

async function openEditor(page:Page,site='drive'){await page.goto('/settings?section=navigation&module='+site);await expect(editor(page).getByLabel('显示名称')).toBeVisible();}
const saves=(fixture:Awaited<ReturnType<typeof setup>>)=>fixture.requests.filter(x=>x.path.startsWith('/service-settings/')&&x.method==='PUT');
async function elevate(page:Page){
 const dialog=page.getByRole('dialog',{name:'解锁管理权限'});await expect(dialog).toBeVisible();
 await dialog.getByLabel('管理密码',{exact:true}).fill('synthetic-management-fixture');await dialog.getByRole('button',{name:'验证管理权限',exact:true}).click();
 await page.getByRole('dialog',{name:'确认重试操作'}).getByRole('button',{name:'确认重试一次',exact:true}).click();
}
test('plain GET is 200 and unprivileged PUT is 403; save alone triggers shared elevation',async({page,fixture})=>{
 await openEditor(page);const statuses=await page.evaluate(async()=>({get:(await fetch('/service-settings/drive')).status,put:(await fetch('/service-settings/drive',{method:'PUT',headers:{'Content-Type':'application/json'},body:'{}'})).status}));expect(statuses).toEqual({get:200,put:403});
 await editor(page).getByLabel('显示名称').fill('家庭文件');await editor(page).getByLabel('OpenList 服务地址').fill('http://owned.test:5244/kept/subpath');
 await editor(page).getByRole('button',{name:'保存',exact:true}).click();await elevate(page);await expect(editor(page)).toHaveCount(0);
 expect(fixture.states.drive.name).toBe('家庭文件');expect(fixture.states.drive.connection.service_url).toBe('http://owned.test:5244/kept/subpath');expect(fixture.states.drive.connection.has_token).toBe(true);
 await expect(page.locator('.sidebar a[href="/drive"]')).toContainText('家庭文件');await page.getByRole('button',{name:'编辑 家庭文件',exact:true}).click();await expect(editor(page).getByLabel('显示名称')).toHaveValue('家庭文件');await expect(editor(page).getByLabel('OpenList 服务地址')).toHaveValue('http://owned.test:5244/kept/subpath');await expect(editor(page).getByLabel('Token',{exact:true})).toHaveValue('');
 expect(saves(fixture).filter(x=>x.body.name==='家庭文件')).toHaveLength(2); // rejected then one explicitly confirmed retry
});
for(const uncertain of [false,true])test('failed GET holds all inputs and retry is read-only, network uncertainty='+uncertain,async({page,fixture})=>{
 fixture.state.elevated=true;await openEditor(page);fixture.failures.read=true;fixture.failures.uncertain=uncertain;
 await editor(page).getByLabel('显示名称').fill('待回读名称');await editor(page).getByLabel('OpenList 服务地址').fill('http://owned.test/edited');await editor(page).getByRole('button',{name:'保存',exact:true}).click();
 await expect(editor(page).getByRole('button',{name:'重试回读',exact:true})).toBeEnabled();await expect(editor(page).getByLabel('显示名称')).toHaveValue('待回读名称');await expect(page.getByRole('button',{name:'编辑 图库',exact:true})).toBeDisabled();
 expect(saves(fixture)).toHaveLength(1);fixture.failures.read=false;await editor(page).getByRole('button',{name:'重试回读',exact:true}).click();await expect(editor(page)).toHaveCount(0);expect(saves(fixture)).toHaveLength(1);await expect(page.locator('.sidebar a[href="/drive"]')).toContainText('待回读名称');
});
test('whole-form validation error retains name, connection, appearance and custom without success',async({page,fixture})=>{
 fixture.state.elevated=true;fixture.failures.write=422;await openEditor(page);await editor(page).getByLabel('显示名称').fill('保留全部输入');await editor(page).getByLabel('OpenList 服务地址').fill('http://owned.test/draft');await editor(page).getByLabel('Stella 主题',{exact:true}).uncheck();
 await editor(page).locator('.advanced > summary').click();await editor(page).getByLabel('自定义 CSS',{exact:true}).fill('body { color: coral; }');await editor(page).getByRole('button',{name:'保存',exact:true}).click();await expect(editor(page).getByRole('alert')).toContainText('校验失败');await expect(editor(page).getByLabel('显示名称')).toHaveValue('保留全部输入');await expect(editor(page).getByLabel('Stella 主题',{exact:true})).not.toBeChecked();await expect(editor(page).getByLabel('自定义 CSS',{exact:true})).toHaveValue('body { color: coral; }');expect(fixture.states.drive.name).toBe('网盘');expect(saves(fixture)).toHaveLength(1);
});
test('dirty switching and leaving preserve service edits until explicit discard',async({page,fixture})=>{
 await openEditor(page);await editor(page).getByLabel('显示名称').fill('未保存');await page.getByRole('button',{name:'编辑 图库',exact:true}).click();const dialog=page.getByRole('dialog',{name:'未保存的修改'});await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'继续编辑'}).click();await expect(editor(page).getByLabel('显示名称')).toHaveValue('未保存');
 await page.getByRole('button',{name:'资料与安全',exact:true}).click();await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:'继续编辑'}).click();await expect(editor(page).getByLabel('显示名称')).toHaveValue('未保存');
 await page.getByRole('button',{name:'编辑 图库',exact:true}).click();await dialog.getByRole('button',{name:'放弃修改'}).click();await expect(editor(page).getByLabel('Immich 浏览器地址')).toBeVisible();expect(saves(fixture)).toHaveLength(0);
});
for(const width of [1440,390])test('real graphical appearance previews and compact form at '+width,async({page,fixture},testInfo)=>{
 await page.setViewportSize({width,height:width===390?852:1000});await openEditor(page);
 const name=editor(page).getByLabel('显示名称');expect((await name.boundingBox())!.width).toBeLessThanOrEqual(221);
 await editor(page).getByRole('button',{name:/选择图标/}).click();await expect(editor(page).getByRole('radiogroup',{name:'图标选择'}).locator('svg')).toHaveCount(14);await editor(page).getByRole('radio',{name:'文件夹',exact:true}).click();await expect(editor(page).getByLabel('侧栏效果')).toContainText('网盘');
 await name.scrollIntoViewIfNeeded();await page.screenshot({path:testInfo.outputPath('openlist-form-'+width+'.png'),animations:'disabled'});
 await previewShot(page,testInfo.outputPath('openlist-stella-'+width+'.png'));
 const preview=editor(page).locator('[data-preview-theme]');const before=await preview.evaluate(el=>getComputedStyle(el).backgroundColor);await editor(page).getByLabel('Stella 主题',{exact:true}).uncheck();await editor(page).getByLabel('简洁显示',{exact:true}).uncheck();await expect(preview).toHaveAttribute('data-preview-theme','original');expect(await preview.evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe(before);await expect(preview.locator('[data-preview-brand]')).toBeVisible();
 await previewShot(page,testInfo.outputPath('openlist-original-'+width+'.png'));
 await editor(page).getByLabel('主页背景',{exact:true}).check();expect(await page.evaluate(()=>localStorage.getItem('stella_drive_bg_mode'))).toBeNull();await editor(page).getByRole('button',{name:'保存本机背景'}).click();expect(await page.evaluate(()=>[localStorage.getItem('stella_drive_bg_mode'),localStorage.getItem('__stella_drive_bg_mode__')])).toEqual(['image','image']);expect(saves(fixture)).toHaveLength(0);
 await page.getByRole('button',{name:'编辑 图库',exact:true}).click();await page.getByRole('dialog',{name:'未保存的修改'}).getByRole('button',{name:'放弃修改'}).click();await expect(editor(page).getByLabel('Stella Logo',{exact:true})).toBeVisible();
 await expect(editor(page).locator('[data-preview-logo="stella"] img')).toBeVisible();await previewShot(page,testInfo.outputPath('immich-stella-'+width+'.png'));
 await editor(page).getByLabel('Stella Logo',{exact:true}).uncheck();await expect(editor(page).locator('[data-preview-logo="original"] svg[role="img"]')).toBeVisible();await expect(editor(page)).toContainText('整个原站域名');await previewShot(page,testInfo.outputPath('immich-original-'+width+'.png'));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await testInfo.attach('form-dom',{body:await editor(page).innerText(),contentType:'text/plain'});
});
test('custom draft and rollback use old writes but new aggregate reads, preserving distinct saved draft',async({page,fixture})=>{
 fixture.state.elevated=true;const state=fixture.states.drive;state.injection.previous={...state.injection.active,css:'/* prior */',version:'prior-v1',status:'revoked'};
 await openEditor(page);await editor(page).locator('.advanced > summary').click();await editor(page).getByLabel('自定义 CSS',{exact:true}).fill('/* distinct draft */');await editor(page).getByRole('button',{name:'仅保存草稿',exact:true}).click();await expect(editor(page).getByRole('alert')).toContainText('草稿已保存并回读');expect(state.injection.active.css).toBe('');
 await editor(page).locator('.technical > summary').click();await editor(page).getByRole('button',{name:'回退上一版本',exact:true}).click();await expect(editor(page).getByLabel('活动版本 CSS',{exact:true})).toHaveValue('/* prior */');await expect(editor(page).getByLabel('自定义 CSS',{exact:true})).toHaveValue('/* distinct draft */');expect(fixture.requests.at(-1)?.path).toBe('/service-settings/drive');
 await editor(page).getByLabel('自定义 JavaScript',{exact:true}).fill('window.ownedFixture = 1;');await editor(page).getByLabel('启用自定义',{exact:true}).check();await editor(page).getByRole('button',{name:'保存',exact:true}).click();await expect(editor(page)).toHaveCount(0);expect(state.injection.active.js).toBe('window.ownedFixture = 1;');expect(state.injection.active.enabled).toBe(true);expect(await page.evaluate(()=>('ownedFixture' in window))).toBe(false);
});
for(const site of ['drive','gallery'])test('actual connection failure exposes recovery, then clean HTTP content: '+site,async({page,fixture})=>{
 let attempts=0;await page.route(ROOT+'/'+site+'/status',route=>++attempts===1?route.fulfill({status:502,json:{detail:'测试上游暂不可达'}}):route.fulfill({json:{configured:true}}));
 await page.goto('/'+site);await expect(page.getByRole('alert')).toContainText('测试上游暂不可达');await expect(page.getByRole('button',{name:'连接设置',exact:true})).toBeVisible();await page.getByRole('button',{name:'重新连接',exact:true}).click();await expect(page.locator('iframe').contentFrame().getByRole('heading',{name:/Owned .* fixture/})).toBeVisible();await expect(page.locator('.'+site+'-page')).toHaveText('');expect(attempts).toBe(2);expect(fixture.state.elevated).toBe(false);
});
for(const site of ['drive','gallery'])test('late HTTP load clears timeout recovery rather than leaving a permanent toolbar: '+site,async({page,fixture})=>{
 let release!:()=>void;const gate=new Promise<void>(resolve=>release=resolve);let requested=false;
 const target=site==='drive'?'/drive/openlist/':'/gallery/connect';await page.route(ROOT+target,async route=>{requested=true;await gate;await route.continue();});
 await page.clock.install();await page.goto('/'+site,{waitUntil:'domcontentloaded'});await expect.poll(()=>requested).toBe(true);await page.clock.fastForward(21000);await expect(page.locator('.'+site+'-page .recovery')).toBeVisible();release();
 await expect(page.locator('iframe').contentFrame().getByRole('heading',{name:/Owned .* fixture/})).toBeVisible();await expect(page.locator('.'+site+'-page')).toHaveText('');expect(fixture.state.elevated).toBe(false);
});
test('same-owner real thirty-second App inspection retains service iframe DOM and input',async({page,fixture},testInfo)=>{
 test.setTimeout(75000);await page.goto('/settings?section=navigation');await page.locator('.sidebar a[href="/drive"]').click();await expect(page.locator('iframe').contentFrame().getByRole('heading',{name:'Owned OpenList fixture'})).toBeVisible();
 await page.locator('iframe').contentFrame().getByLabel('服务内输入').fill('跨越真实巡检保留');const first=await page.locator('iframe').elementHandle();const probes=fixture.requests.filter(x=>x.path==='/auth/me').length;const start=Date.now();await page.waitForTimeout(31000);expect(Date.now()-start).toBeGreaterThanOrEqual(30000);expect(fixture.requests.filter(x=>x.path==='/auth/me').length).toBeGreaterThan(probes);
 expect(await page.locator('iframe').evaluate((el,old)=>el===old,first)).toBe(true);await expect(page.locator('iframe').contentFrame().getByLabel('服务内输入')).toHaveValue('跨越真实巡检保留');await expect(page.locator('.drive-page')).toHaveText('');expect(fixture.visits).toEqual(['/drive/openlist/']);
 await testInfo.attach('real-watchdog',{body:JSON.stringify({elapsed:Date.now()-start,authMeRequests:fixture.requests.filter(x=>x.path==='/auth/me').length}),contentType:'application/json'});
 await page.locator('.sidebar a[href="/gallery"]').click();await expect(page.locator('iframe').contentFrame().getByRole('heading',{name:'Owned Immich fixture'})).toBeVisible();await page.locator('.sidebar a[href="/drive"]').click();await expect(page.locator('iframe').contentFrame().getByRole('heading',{name:'Owned OpenList fixture'})).toBeVisible();expect(fixture.state.elevated).toBe(false);await expect(page.getByRole('dialog')).toHaveCount(0);
});
