import {test,expect,type Page} from '@playwright/test';
import {mock} from './low-config-mocks';
const out='/opt/hermes-workstation/docs/2026-10-06-Stella-upgrade/low-config-fix';
async function setup(page:Page,{failResolve=false,failTarget=false}={}){
 const m=await mock(page);m.state.elevated=true;
 const flow:{path:string;body:any}[]=[];let target:any;
 await page.route(/\/integration-targets(?:\/resolve)?$/,async route=>{
  const req=route.request(),path=new URL(req.url()).pathname,body=req.postDataJSON();
  if(req.method()==='GET')return route.fulfill({json:target?[target]:[]});
  flow.push({path,body});
  if(!m.state.elevated)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
  if(path.endsWith('/resolve'))return route.fulfill(failResolve?{status:422,json:{detail:'禁止元数据或非法目标'}}:{json:{normalized_origin:new URL(body.upstream_url).origin,resolved_ips:['10.66.0.2'],status:'resolved',private_addresses:true}});
  if(failTarget)return route.fulfill({status:422,json:{detail:'目标解析/批准列表无效'}});
  target={...body,id:'frozen1'};return route.fulfill({status:201,json:target});
 });
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 return {...m,flow,errors};
}
async function form(page:Page,url='http://10.66.0.2:12020/photos?q=1#grid'){
 await page.goto('/settings?section=navigation');
 await page.getByRole('button',{name:'新增网站',exact:true}).click();
 await page.getByLabel('网站名称',{exact:true}).fill('私网照片');
 await page.getByLabel('网站 URL',{exact:true}).fill(url);
 await page.getByText('高级接入',{exact:true}).click();
 await page.getByText('iframe 直连',{exact:true}).click();
 await page.getByText('独立域名代理',{exact:true}).click();
}
test('one URL approves frozen target and creates proxy without IP entry or background detection',async({page})=>{
 const m=await setup(page);await form(page);
 expect(m.flow).toEqual([]);
 await expect(page.getByLabel('此上游为我自有或明确受控的服务',{exact:true})).not.toBeChecked();
 await page.getByLabel('允许此固定目标访问私网或本机地址',{exact:true}).check();
 await page.getByLabel('为此网址批准固定目标',{exact:true}).check();
 await page.screenshot({path:out+'/approval-desktop.png',fullPage:true,animations:'disabled'});
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(m.flow.map(x=>x.path)).toEqual(['/integration-targets/resolve','/integration-targets']);
 expect(m.flow[0]!.body).toEqual({upstream_url:'http://10.66.0.2:12020',allow_private:true});
 expect(m.flow[1]!.body).toEqual({name:'私网照片',upstream_url:'http://10.66.0.2:12020',allowed_ips:['10.66.0.2'],controlled:false,headers:{}});
 const creates=m.requests.filter(x=>x.path==='/external-modules'&&x.method==='POST');expect(creates).toHaveLength(1);
 expect(creates[0]!.body).toMatchObject({target_id:'frozen1',mode:'isolated_proxy',initial_path:'/photos?q=1#grid',browser_url:'http://10.66.0.2:12020/photos?q=1#grid'});
 await page.screenshot({path:out+'/created-desktop.png',fullPage:true,animations:'disabled'});
 await page.goto('/apps/demo1');
 await expect(page.frameLocator('iframe').getByText('Mock website',{exact:true})).toBeVisible();
 await expect(page.getByText('已导航，内部状态不可读',{exact:true})).toBeVisible();
 expect(m.requests.find(x=>x.path==='/__stella/bootstrap')?.method).toBe('POST');
 expect(m.requests.some(x=>x.path==='/photos')).toBe(false);
 await page.screenshot({path:out+'/proxy-launch.png',fullPage:true,animations:'disabled'});
 expect(m.errors).toEqual([]);expect(m.unknown).toEqual([]);
});

test('target readback failure retains URL path and re-verifies before retry without recreating target',async({page})=>{
 const m=await setup(page);let reads=0;
 await page.route('**/integration-targets',async route=>{
  if(route.request().method()!=='GET')return route.fallback();
  reads++;
  if(reads===1)return route.fulfill({status:503,json:{detail:'暂时无法回读目标'}});
  return route.fulfill({json:[{id:'frozen1',name:'私网照片',upstream_url:'http://10.66.0.2:12020/',controlled:false,allowed_ips:['10.66.0.2']}]});
 });
 await form(page);
 await page.getByLabel('允许此固定目标访问私网或本机地址',{exact:true}).check();
 await page.getByLabel('为此网址批准固定目标',{exact:true}).check();
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('暂时无法回读目标');
 expect(m.requests.filter(x=>x.path==='/external-modules'&&x.method==='POST')).toHaveLength(0);
 await page.getByRole('button',{name:'创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(reads).toBe(2);
 expect(m.flow.filter(x=>x.path==='/integration-targets')).toHaveLength(1);
 expect(m.requests.find(x=>x.path==='/external-modules'&&x.method==='POST')!.body.initial_path).toBe('/photos?q=1#grid');
 expect(m.errors).toEqual([]);
});

async function consent(page:Page){
 await page.getByLabel('允许此固定目标访问私网或本机地址',{exact:true}).check();
 await page.getByLabel('为此网址批准固定目标',{exact:true}).check();
}
for(const failure of ['resolve','target'] as const)test(failure+' rejection never creates a module',async({page})=>{
 const m=await setup(page,{failResolve:failure==='resolve',failTarget:failure==='target'});await form(page,'http://169.254.169.254/');await consent(page);
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText(failure==='resolve'?'禁止元数据或非法目标':'目标解析/批准列表无效');
 expect(m.requests.filter(x=>x.path==='/external-modules'&&x.method==='POST')).toHaveLength(0);
 expect(m.flow.filter(x=>x.path==='/integration-targets')).toHaveLength(failure==='resolve'?0:1);
 expect(m.errors).toEqual([]);
});
test('global elevation modal requires unlock and explicit one retry before approving a target',async({page})=>{
 const m=await setup(page);m.state.elevated=false;await form(page);await consent(page);
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('dialog')).toBeVisible();expect(m.flow).toHaveLength(1);
 await page.screenshot({path:out+'/approval-admin-modal.png',fullPage:true,animations:'disabled'});
 await page.getByRole('dialog').getByLabel('管理密码',{exact:true}).fill('MOCK_ADMIN_NOT_SECRET');
 await page.getByRole('button',{name:'验证管理权限',exact:true}).click();
 await expect(page.getByRole('button',{name:'确认重试一次',exact:true})).toBeVisible();expect(m.flow).toHaveLength(1);
 await page.getByRole('button',{name:'确认重试一次',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(m.flow.map(x=>x.path)).toEqual(['/integration-targets/resolve','/integration-targets/resolve','/integration-targets']);
 expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain('MOCK_ADMIN_NOT_SECRET');
 expect(m.requests.filter(x=>x.path==='/external-modules'&&x.method==='POST')).toHaveLength(1);
 expect(m.errors).toEqual([]);expect(m.unknown).toEqual([]);
});
test('failed module readback retries update rather than creating another module',async({page})=>{
 const m=await setup(page);let reads=0;
 await page.route(/\/external-modules\/demo1$/,async route=>{
  if(route.request().method()==='GET'&&++reads===1)return route.fulfill({status:503,json:{detail:'模块回读暂不可用'}});
  return route.fallback();
 });
 await form(page);await consent(page);
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('模块回读暂不可用');
 await page.getByRole('button',{name:'应用接入变更',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(m.requests.filter(x=>x.path==='/external-modules'&&x.method==='POST')).toHaveLength(1);
 expect(m.requests.filter(x=>x.path==='/external-modules/demo1'&&x.method==='PATCH')).toHaveLength(1);
 expect(m.flow.filter(x=>x.path==='/integration-targets')).toHaveLength(1);expect(m.errors).toEqual([]);
});
test('Immich retains original browser origin while approving explicit private upstream and ownership',async({page})=>{
 const m=await setup(page);await form(page,'https://immich.xiya.live/');
 await page.getByText('通用网站',{exact:true}).click();await page.getByText('Immich（保留原域名 / OIDC）',{exact:true}).click();
 await page.getByLabel('独立上游根地址',{exact:true}).fill('http://10.66.0.2:12020/');
 await page.getByLabel('此上游为我自有或明确受控的服务',{exact:true}).check();await consent(page);
 await page.screenshot({path:out+'/immich-private-upstream.png',fullPage:true,animations:'disabled'});
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(m.flow[0]!.body).toEqual({upstream_url:'http://10.66.0.2:12020/',allow_private:true});
 expect(m.flow[1]!.body.controlled).toBe(true);
 expect(m.requests.find(x=>x.path==='/external-modules'&&x.method==='POST')!.body).toMatchObject({browser_url:'https://immich.xiya.live/',adapter:'immich',initial_path:'/',target_id:'frozen1'});
 expect(m.errors).toEqual([]);
});
test('default iframe never auto-switches mode or resolves a URL',async({page})=>{
 const m=await setup(page);await page.goto('/settings?section=navigation');await page.getByRole('button',{name:'新增网站',exact:true}).click();
 await page.getByLabel('网站名称',{exact:true}).fill('直连');await page.getByLabel('网站 URL',{exact:true}).fill('https://third-party.example/');
 await expect(page.getByLabel('为此网址批准固定目标',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'创建网站',exact:true}).click();await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(m.flow).toEqual([]);expect(m.requests.find(x=>x.path==='/external-modules'&&x.method==='POST')!.body.mode).toBe('iframe');expect(m.errors).toEqual([]);
});
test('advanced existing approved target bypasses new approval flow',async({page})=>{
 const m=await setup(page);
 await page.route('**/integration-targets',async route=>route.request().method()==='GET'?route.fulfill({json:[{id:'existing',name:'已批准服务',upstream_url:'http://10.66.0.2:12020/',controlled:true}]}):route.fallback());
 await form(page);await page.getByRole('button',{name:'选择已批准上游',exact:true}).click();
 await page.getByRole('button',{name:'—',exact:true}).click();await page.getByText('已批准服务',{exact:true}).click();
 await expect(page.getByLabel('为此网址批准固定目标',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'创建网站',exact:true}).click();await expect(page.getByRole('status')).toContainText('网站入口已更新');
 expect(m.flow).toEqual([]);expect(m.requests.find(x=>x.path==='/external-modules'&&x.method==='POST')!.body.target_id).toBe('existing');expect(m.errors).toEqual([]);
});
test('mobile fixed approval form stays inside viewport and readable',async({page})=>{
 const m=await setup(page);await page.setViewportSize({width:390,height:844});await form(page);await consent(page);
 const button=page.getByRole('button',{name:'批准固定上游并创建网站',exact:true});await button.scrollIntoViewIfNeeded();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(await page.locator('.approval').evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})).toBe(true);
 await page.screenshot({path:out+'/approval-mobile.png',fullPage:true,animations:'disabled'});
 expect(m.flow).toEqual([]);expect(m.errors).toEqual([]);
});

test('editing a refreshed existing proxy never drops its previously approved target',async({page})=>{
 const m=await setup(page);await form(page);await consent(page);
 await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();await expect(page.getByRole('status')).toContainText('网站入口已更新');
 await page.route(/\/external-modules\/demo1$/,async route=>route.request().method()==='GET'?route.fulfill({json:{id:'demo1',name:'私网照片',icon:'globe',mode:'isolated_proxy',adapter:'generic',browser_url:'http://10.66.0.2:12020/new-path',target_id:'frozen1',initial_path:'/new-path',enabled:true,injection:{draft:null,active:null,previous:null},capabilities:{injection:true}}}):route.fallback());
 await page.getByRole('button',{name:'编辑 私网照片',exact:true}).click();
 await expect(page.getByLabel('网站 URL',{exact:true})).toHaveValue('http://10.66.0.2:12020/new-path');
 await expect(page.getByLabel('为此网址批准固定目标',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'应用接入变更',exact:true})).toBeVisible();expect(m.errors).toEqual([]);
});

test('ambiguous create response cannot be retried into a duplicate module',async({page})=>{
 const m=await setup(page);let writes=0;
 await page.route('**/external-modules',async route=>{
  if(route.request().method()!=='POST')return route.fallback();
  writes++;
  // Model a committed write whose successful response did not reach this client.
  m.addModule({...route.request().postDataJSON(),id:'committed',origin:'https://mock-embed.test',capabilities:{injection:true},injection:{draft:null,active:null,previous:null}});
  return route.fulfill({status:503,json:{detail:'响应丢失'}});
 });
 await form(page);await consent(page);await page.getByRole('button',{name:'批准固定上游并创建网站',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('创建结果未确认');
 await expect(page.getByRole('button',{name:'创建网站',exact:true})).toBeDisabled();
 expect(writes).toBe(1);expect(m.errors).toEqual([]);
});
