// Legacy approval-flow scenarios expressed through the current atomic website contract.
import {test as base,expect,type Page} from '@playwright/test';
import {mock} from './low-config-mocks';
const ROOT='http://127.0.0.1:15274';
const ADDRESS='http://owned-private.test:12020/photos?q=1#grid';
async function setup(page:Page){
 const m=await mock(page);m.state.elevated=true;const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const writes:any[]=[],checks:any[]=[];const options={rejectCheck:false,rejectSave:false,failRead:false,uncertain:false};
 let item:any=null;const keys=new Map<string,any>();
 const checked=(address:string)=>({normalized_url:address,name_suggestion:'照片',access:{status:options.rejectCheck?'blocked':'reachable',http_status:200},embedding:{status:options.rejectCheck?'blocked':'allowed',reason_code:options.rejectCheck?'invalid_target':'no_observed_restriction',reason:options.rejectCheck?'禁止元数据或非法目标':'未发现响应头限制'},injection:{status:'unsupported',reason:'未启用自定义'},can_save:!options.rejectCheck,recommended_behavior:'embedded',issues:[],help:null});
 await page.route(ROOT+'/website-settings/check',route=>{checks.push(route.request().postDataJSON());return route.fulfill({json:checked(checks.at(-1).address)});});
 await page.route(ROOT+'/website-settings',async route=>{
  const body=route.request().postDataJSON();writes.push(body);
  if(!m.state.elevated)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
  if(options.rejectSave)return route.fulfill({status:422,json:{detail:'目标校验失败，未创建网站'}});
  if(!keys.has(body.idempotency_key)){
   item={id:'demo1',name:body.name,icon:body.icon,adapter:'generic',mode:body.open_behavior==='external'?'link':body.address.includes('owned-private')?'isolated_proxy':'iframe',browser_url:body.address,origin:'https://mock-embed.test',target_id:'server-managed-target',initial_path:new URL(body.address).pathname+new URL(body.address).search+new URL(body.address).hash,keep_alive:body.keep_alive,enabled:true,injection:{active:null,draft:body.custom,previous:null},capabilities:{injection:false}};
   m.addModule(item);m.setEntry({id:item.id,title:item.name,icon:item.icon,visible:body.visible});keys.set(body.idempotency_key,item);
  }
  if(options.uncertain){options.uncertain=false;return route.abort('connectionreset');}return route.fulfill({json:item});
 });
 await page.route(ROOT+'/external-modules/demo1',route=>options.failRead?route.fulfill({status:503,json:{detail:'读取暂不可用'}}):route.fallback());
 return {...m,errors,writes,checks,options,keys,get item(){return item;}};
}
const test=base.extend<{fixture:Awaited<ReturnType<typeof setup>>}>({fixture:async({page},use)=>{const f=await setup(page);try{await use(f);}finally{expect(f.errors).toEqual([]);expect(f.unknown).toEqual([]);expect(f.requests.filter(x=>x.path.startsWith('/integration-targets'))).toEqual([]);}}});
async function form(page:Page,url=ADDRESS){await page.goto('/settings?section=navigation');await page.getByRole('button',{name:'＋ 添加网站',exact:true}).click();await page.getByLabel('显示名称',{exact:true}).fill('私网照片');await page.getByLabel('网站地址',{exact:true}).fill(url);}
const save=(page:Page)=>page.locator('.inline-editor').getByRole('button',{name:'保存',exact:true}).click();
test('one URL retains path and server-managed isolated launch without client target approval',async({page,fixture})=>{
 await form(page);expect(fixture.checks).toEqual([]);expect(fixture.writes).toEqual([]);await expect(page.getByText('批准固定目标',{exact:false})).toHaveCount(0);await save(page);await expect(page.locator('.inline-editor')).toHaveCount(0);expect(fixture.writes).toHaveLength(1);expect(fixture.writes[0].address).toBe(ADDRESS);expect(fixture.item.initial_path).toBe('/photos?q=1#grid');
 await page.locator('.sidebar a[href="/apps/demo1"]').click();await expect(page.frameLocator('iframe').getByText('Mock website')).toBeVisible();await expect(page.locator('.external-page')).toHaveText('');expect(fixture.requests.find(x=>x.path==='/__stella/bootstrap')?.method).toBe('POST');
});
test('readback failure retains address and only retries the exact module GET',async({page,fixture})=>{
 await form(page);fixture.options.failRead=true;await save(page);await expect(page.getByRole('button',{name:'重试回读',exact:true})).toBeEnabled();await expect(page.getByLabel('网站地址')).toHaveValue(ADDRESS);expect(fixture.writes).toHaveLength(1);fixture.options.failRead=false;await page.getByRole('button',{name:'重试回读',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);expect(fixture.writes).toHaveLength(1);
});
for(const phase of ['check','save'] as const)test(phase+' rejection retains all inputs and never creates a module',async({page,fixture})=>{
 await form(page,'http://169.254.169.254/');fixture.options.rejectCheck=phase==='check';fixture.options.rejectSave=phase==='save';await save(page);await expect(page.getByRole('alert')).toContainText(phase==='check'?'当前设置不能保存':'目标校验失败');expect(fixture.item).toBeNull();expect(fixture.writes).toHaveLength(phase==='check'?0:1);await expect(page.getByLabel('网站地址')).toHaveValue('http://169.254.169.254/');
});
test('global elevation unlock requires separate confirmation and one retry of website save',async({page,fixture})=>{
 fixture.state.elevated=false;await form(page);await save(page);await expect(page.getByRole('dialog',{name:'解锁管理权限'})).toBeVisible();expect(fixture.writes).toHaveLength(1);await page.getByRole('dialog').getByLabel('管理密码',{exact:true}).fill('synthetic-fixture');await page.getByRole('button',{name:'验证管理权限',exact:true}).click();await expect(page.getByRole('button',{name:'确认重试一次',exact:true})).toBeVisible();expect(fixture.writes).toHaveLength(1);await page.getByRole('button',{name:'确认重试一次',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);expect(fixture.writes).toHaveLength(2);expect(fixture.keys.size).toBe(1);
});
test('cancelled elevation leaves form and never issues a hidden retry',async({page,fixture})=>{
 fixture.state.elevated=false;await form(page);await save(page);await page.getByRole('dialog',{name:'解锁管理权限'}).getByRole('button',{name:'取消',exact:true}).click();await expect(page.getByLabel('网站地址')).toHaveValue(ADDRESS);expect(fixture.writes).toHaveLength(1);expect(fixture.item).toBeNull();
});
test('existing Immich retains dedicated original-domain and OIDC settings, not website API',async({page,fixture})=>{
 await page.goto('/settings?section=navigation');await page.getByRole('button',{name:'编辑 图库',exact:true}).click();await expect(page.getByLabel('Immich 浏览器地址')).toHaveValue('https://owned-gallery.test');await expect(page.getByRole('button',{name:'登录方式',exact:true})).toHaveText('OIDC 单点登录');expect(fixture.writes).toHaveLength(0);expect(fixture.checks).toHaveLength(0);
});
test('ordinary direct website saves embedded behavior without automatic client proxy migration',async({page,fixture})=>{
 await form(page,'https://third-party.example/');await save(page);await expect(page.locator('.inline-editor')).toHaveCount(0);expect(fixture.item.mode).toBe('iframe');expect(fixture.writes[0].open_behavior).toBe('embedded');expect(fixture.writes[0]).not.toHaveProperty('target_id');
});
test('explicit new-window behavior is preserved instead of silently switching back',async({page,fixture})=>{
 await form(page);await page.getByLabel('打开方式').selectOption('external');await save(page);await expect(page.locator('.inline-editor')).toHaveCount(0);expect(fixture.item.mode).toBe('link');
});
test('mobile URL form is compact and stays in viewport without approval controls',async({page,fixture},info)=>{
 await page.setViewportSize({width:390,height:844});await form(page);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await expect(page.getByText('批准固定上游并创建网站',{exact:true})).toHaveCount(0);await page.screenshot({path:info.outputPath('url-only-mobile.png'),animations:'disabled'});expect(fixture.writes).toHaveLength(0);
});
test('reopening existing server-managed proxy retains path and never posts a replacement',async({page,fixture})=>{
 await form(page);await save(page);await expect(page.locator('.inline-editor')).toHaveCount(0);await page.getByRole('button',{name:'编辑 私网照片',exact:true}).click();await expect(page.getByLabel('网站地址')).toHaveValue(ADDRESS);expect(fixture.item.target_id).toBe('server-managed-target');expect(fixture.writes).toHaveLength(1);
});
test('uncertain create retries frozen payload and idempotency key, never creates duplicate',async({page,fixture})=>{
 await form(page);fixture.options.uncertain=true;await save(page);await expect(page.getByRole('button',{name:'确认保存结果',exact:true})).toBeEnabled();await expect(page.getByLabel('网站地址')).toBeDisabled();expect(fixture.keys.size).toBe(1);await page.getByRole('button',{name:'确认保存结果',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);expect(fixture.writes).toHaveLength(2);expect(fixture.writes[0]).toEqual(fixture.writes[1]);expect(fixture.keys.size).toBe(1);
});
