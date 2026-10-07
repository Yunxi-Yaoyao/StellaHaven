import {test,expect,type Page} from '@playwright/test';
import {serviceFixture} from './fixtures/serviceSettings';
const checked=(address:string,blocked=false)=>({normalized_url:new URL(address.includes('://')?address:'https://'+address).href,name_suggestion:'建议网站名',access:{status:'reachable',http_status:200},embedding:{status:blocked?'blocked':'allowed',reason_code:blocked?'csp_none':'no_observed_restriction',reason:blocked?"CSP frame-ancestors 'none' 禁止嵌入":'未发现响应头限制'},injection:{status:'unsupported',reason:'跨域直连不能修改 DOM'},help:blocked?{title:'额度 Nginx 配置',location:'/etc/nginx/conf.d/quota.conf',instructions:['在额度服务允许 Stella 精确 origin，保留其他 CSP 和 LAN ACL'],external_url:null}:null,can_save:!blocked,recommended_behavior:blocked?'external':'embedded',issues:[]});
async function fixture(page:Page,options:{failNavigation?:boolean;loseCreateResponse?:boolean;full?:boolean;module?:string;external?:boolean;blockedCheck?:boolean;supported?:boolean;previous?:boolean;savedDraft?:boolean;legacyNavigation?:boolean;legacyNavigationIcon?:string;legacyIcon?:boolean;corruptReadback?:boolean}={}){
 const unknown:string[]=[],errors:string[]=[],consoleErrors:string[]=[],requests:any[]=[];
 page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
 const modules:any[]=[{id:'quota',name:'额度',icon:'globe',browser_url:'https://quota.example.test/',mode:'iframe',adapter:'generic',enabled:true,keep_alive:false,injection:{active:null,draft:null,previous:null}},{id:'second',name:'第二网站',icon:'book',browser_url:'https://second.example.test/',mode:'iframe',adapter:'generic',enabled:true,keep_alive:false}];
 if(options.previous)modules[0].injection={draft:null,active:{enabled:false,css:'current',js:'',timing:'dom_ready',version:'v2'},previous:{enabled:false,css:'previous',js:'',timing:'dom_ready',version:'v1'}};
 if(options.savedDraft)modules[0].injection={draft:{enabled:false,css:'body{color:blue}',js:'window.savedDraft=true',timing:'dom_ready',version:'draft-v3'},active:{enabled:true,css:'body{color:green}',js:'window.activeGreen=true',timing:'dom_ready',version:'v2'},previous:{enabled:true,css:'body{color:red}',js:'window.activeRed=true',timing:'dom_ready',version:'v1'}};
 if(options.legacyIcon)modules[0].icon='heart';
 let writes=0;
 let entries:any[]=[{id:'quota',title:options.legacyNavigation?'原来配置的显示名':'额度',icon:options.legacyNavigation?(options.legacyNavigationIcon||'book'):options.legacyIcon?'heart':'globe',visible:true}];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;
  // Only real Vite files on this isolated loopback origin can pass. No API forwarding.
  if(u.origin==='http://127.0.0.1:15179'&&(p==='/tests/website-settings.html'||p==='/avatar.png'||p.startsWith('/tests/')||p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')))return route.continue();
  const body=req.postData()?req.postDataJSON():null; requests.push({path:p,method:req.method(),body});
  if(p==='/navigation'){if(options.failNavigation&&writes){options.failNavigation=false;return route.fulfill({status:503,json:{detail:'fixture refresh failed'}});}if(body)entries=body.entries;return route.fulfill({json:{entries}});}
  if(['/auth/avatars','/auth/sessions','/homebg/'].includes(p))return route.fulfill({json:[]});
  if(p==='/config/public-host')return route.fulfill({json:{value:''}});
  if(p==='/auth/email-service')return route.fulfill({json:{ready:false}});
  if(p==='/auth/security')return route.fulfill({json:{enabled:true,configured:true,elevated:true,setup_required:false,single_user:true}});
  if(p==='/service-settings/drive'&&req.method()==='GET')return route.fulfill({json:serviceFixture('drive')});
  if(p==='/drive/connection')return route.fulfill({json:{service_url:'https://openlist.example.test/',auth_mode:'manual',has_token:false}});
  if(p==='/drive/status')return route.fulfill({json:{configured:true}});
  if(p==='/builtin-injections/drive')return route.fulfill({json:{site:'drive',source:'preset',active:{enabled:false,css:'',js:'',timing:'dom_ready',version:'fixture-v1',status:'active'},draft:null,previous:null,preset:{css:'',js:''}}});
  if(p==='/external-modules')return route.fulfill({json:modules});
  if(p==='/website-settings/check'){const result=checked(body.address,body.address.includes('blocked')||options.blockedCheck);if(body.open_behavior==='external'&&!body.custom_enabled)result.can_save=true;if(options.supported)result.injection={status:'supported',reason:'测试上游支持隔离注入'};return route.fulfill({json:result});}
  if(p==='/external-modules/quota/injection/rollback'){[modules[0].injection.active,modules[0].injection.previous]=[modules[0].injection.previous,modules[0].injection.active];return route.fulfill({json:modules[0].injection});}
  if(p==='/external-modules/quota/launch')return route.fulfill({json:{mode:'iframe',method:'GET',url:'http://127.0.0.1:15179/fixture-frame'}});
  if(p==='/fixture-frame')return route.fulfill({contentType:'text/html',body:'<!doctype html><h1>Actual isolated iframe content</h1>'});
  if(p==='/website-settings'||p.startsWith('/website-settings/')){
   if(body.address.includes('race'))return route.fulfill({status:422,json:{detail:{code:'website_check_failed',check:checked(body.address,true)}}});
   writes++; const id=p.split('/')[2]||'created'; let item=modules.find(x=>x.id===id);
   if(!item){item={id,adapter:'generic',enabled:true};modules.push(item);}
   Object.assign(item,{name:body.name||'建议网站名',icon:body.icon,browser_url:checked(body.address).normalized_url,mode:body.open_behavior==='external'?'link':'iframe',keep_alive:body.keep_alive});
   item.injection={draft:{...body.custom},active:body.custom?.enabled?{...body.custom,version:'fixture-active-v2'}:item.injection?.active||null,previous:item.injection?.active||null};
   entries=entries.filter(x=>x.id!==id);entries.push({id,title:item.name,icon:item.icon,visible:body.visible});
   if(options.loseCreateResponse){options.loseCreateResponse=false;return route.abort('failed');}
   return route.fulfill({json:{...item,check:checked(body.address)}});
  }
  const id=p.split('/')[2];const item=modules.find(x=>p==='/external-modules/'+x.id);if(item){if(req.method()==='DELETE'){modules.splice(modules.indexOf(item),1);entries=entries.filter(x=>x.id!==id);return route.fulfill({status:204});}return route.fulfill({json:options.corruptReadback&&writes?{...item,injection:{...item.injection,draft:{...item.injection.draft,css:'corrupt'}}}:item});}
  if(p.startsWith('/external-modules/')&&req.method()==='GET')return route.fulfill({status:404,json:{detail:'Module missing'}});
  unknown.push(req.url());return route.abort('blockedbyclient');
 });
 await page.goto('/tests/website-settings.html'+'?'+(options.full?'full=1':'')+(options.module?'&module='+options.module:'')+(options.external?'&external=1':''));
 await expect(page.getByRole('button',{name:'编辑 '+(options.legacyNavigation?'原来配置的显示名':'额度'),exact:true})).toBeVisible();
 return {unknown,errors,consoleErrors,requests,modules};
}
test('R1 回退明确显示实际活动红色代码并保留蓝色草稿',async({page})=>{
 const f=await fixture(page,{savedDraft:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 await page.getByRole('button',{name:'回退上一版本',exact:true}).click();
 await expect(page.getByText('已回退并回读活动版本；已打开的网站请手动重载。',{exact:true})).toBeVisible();
 await expect(page.getByLabel('活动版本 CSS',{exact:true})).toHaveValue('body{color:red}');
 await expect(page.getByLabel('活动版本 JavaScript',{exact:true})).toHaveValue('window.activeRed=true');
 await expect(page.getByLabel('活动版本 CSS',{exact:true})).toHaveAttribute('readonly','');
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:blue}');
 await expect(page.getByText('编辑内容：已保存草稿（与活动版本分开）',{exact:true})).toBeVisible();
 await expect(page.getByLabel('活动版本内容')).toContainText('v1');
 expect(f.modules[0].injection.draft.css).toBe('body{color:blue}');
 expect(await page.evaluate(()=> (window as any).activeRed)).toBeUndefined();
 expect(f.requests.filter(x=>x.path.endsWith('/rollback'))).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('R3 旧导航覆盖在升级、排序、编辑保存后保持显示一致',async({page})=>{
 const f=await fixture(page,{legacyNavigation:true});
 await expect(page.locator('aside [data-nav-id="quota"]')).toHaveText('原来配置的显示名');
 await expect(page.locator('aside [data-nav-id="quota"] svg path').first()).toHaveAttribute('d','M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z');
 await page.getByRole('button',{name:'下移 原来配置的显示名',exact:true}).click();
 await expect(page.getByText('导航已同步',{exact:true})).toBeVisible();
 await page.reload();
 await page.getByRole('button',{name:'编辑 原来配置的显示名',exact:true}).click();
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('原来配置的显示名');
 await expect(page.getByRole('button',{name:'选择图标，当前书籍',exact:true})).toBeVisible();
 await page.getByLabel('显示名称',{exact:true}).fill('用户明确改名');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 await expect(page.locator('aside [data-nav-id="quota"]')).toHaveText('用户明确改名');
 expect(f.requests.find(x=>x.path==='/website-settings/quota').body.icon).toBe('book');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('R2 既有heart实际预览与改名payload均保留，不能静默替换',async({page})=>{
 const f=await fixture(page,{legacyIcon:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await expect(page.getByRole('button',{name:'选择图标，当前爱心（旧图标）',exact:true})).toBeVisible();
 const heart='M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z';
 await expect(page.getByLabel('侧栏效果').locator('svg path').first()).toHaveAttribute('d',heart);
 await expect(page.locator('aside [data-nav-id="quota"] svg path').first()).toHaveAttribute('d',heart);
 await page.getByRole('button',{name:'选择图标，当前爱心（旧图标）',exact:true}).click();
 await expect(page.getByRole('radio',{name:'首页',exact:true})).toBeFocused();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('button',{name:'选择图标，当前爱心（旧图标）',exact:true})).toBeFocused();
 await page.getByLabel('显示名称',{exact:true}).fill('只改名字');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.requests.find(x=>x.path==='/website-settings/quota').body.icon).toBe('heart');
 await page.reload();await page.getByRole('button',{name:'编辑 只改名字',exact:true}).click();
 await expect(page.getByRole('button',{name:'选择图标，当前爱心（旧图标）',exact:true})).toBeVisible();
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

for(const normalized of ['', 'file:///still-unsafe'])test('R4 检测拒绝保留原始地址、姓名和代码草稿 '+(normalized?'invalid':'empty'),async({page})=>{
 const f=await fixture(page);
 await page.route('**/website-settings/check',route=>route.fulfill({json:{normalized_url:normalized,name_suggestion:'',access:{status:'unknown',http_status:null},embedding:{status:'unknown',reason_code:'unsafe_address',reason:'只支持 HTTP(S) 地址'},injection:{status:'unknown',reason:'地址未通过安全检查'},help:null,can_save:false,recommended_behavior:'external',issues:['只支持 HTTP(S) 地址']}}));
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('file:///user-draft');
 await page.getByLabel('显示名称',{exact:true}).fill('用户姓名草稿');
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 await page.getByLabel('自定义 CSS',{exact:true}).fill('body{color:blue}');
 await page.getByRole('button',{name:'检测',exact:true}).click();
 await expect(page.getByLabel('检测结果')).toContainText('只支持 HTTP(S) 地址');
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('file:///user-draft');
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('用户姓名草稿');
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:blue}');
 await expect(page.getByRole('button',{name:'检测',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByText('当前设置不能保存；请按检测结果处理或显式选择新窗口后重试。',{exact:true})).toBeVisible();
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('file:///user-draft');
 expect(f.requests.filter(x=>x.path==='/website-settings')).toHaveLength(0);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('回退版本回读不一致保留编辑器，只重试精确读取不重复回退',async({page})=>{
 const f=await fixture(page,{savedDraft:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 let corrupt=true;
 await page.route('**/external-modules/quota',route=>route.fulfill({json:corrupt?{...f.modules[0],injection:{...f.modules[0].injection,active:{...f.modules[0].injection.active,version:'wrong-version'}}}:f.modules[0]}));
 await page.getByRole('button',{name:'回退上一版本',exact:true}).click();
 await expect(page.getByText('回退结果未确认，请刷新活动版本，不要重复回退。',{exact:true})).toBeVisible();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:blue}');
 await expect(page.getByText('已回退并回读活动版本；已打开的网站请手动重载。',{exact:true})).toHaveCount(0);
 corrupt=false;await page.getByRole('button',{name:'回退结果回读',exact:true}).click();
 await expect(page.getByLabel('活动版本 CSS',{exact:true})).toHaveValue('body{color:red}');
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:blue}');
 expect(f.requests.filter(x=>x.path.endsWith('/rollback'))).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('检测归一化后可立即重检，不遗留检测中或覆盖手写名称',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('normalize.example.test/path?q=1#last');
 await page.getByLabel('显示名称',{exact:true}).fill('手写名称');
 await page.getByRole('button',{name:'检测',exact:true}).click();
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('https://normalize.example.test/path?q=1#last');
 await expect(page.getByRole('button',{name:'检测',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'检测',exact:true}).click();
 await expect.poll(()=>f.requests.filter(x=>x.path==='/website-settings/check').length).toBe(2);
 await expect(page.getByRole('button',{name:'检测',exact:true})).toBeEnabled();
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('手写名称');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('旧合法cloud导航图标保留原key并明确说明网站预览，不伪装为globe',async({page})=>{
 const f=await fixture(page,{legacyNavigation:true,legacyNavigationIcon:'cloud'});
 await page.getByRole('button',{name:'编辑 原来配置的显示名',exact:true}).click();
 await expect(page.getByRole('button',{name:'选择图标，当前旧图标：cloud（网站预览，保存时保留）',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.requests.find(x=>x.path==='/website-settings/quota').body.icon).toBe('cloud');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('统一列表为文字，仅在选中行下面展开编辑器',async({page})=>{
 const f=await fixture(page);
 await expect(page.locator('.nav-row')).toHaveCount(8);
 await expect(page.locator('.nav-row input:not([type=checkbox])')).toHaveCount(0);
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await expect(page.locator('[data-row-id="quota"] .inline-editor')).toBeVisible();
 await expect(page.locator('.inline-editor')).toHaveCount(1);
 await page.getByLabel('网站地址',{exact:true}).fill('new.example.test/path?q=1#start');
 await page.getByRole('button',{name:'编辑 第二网站',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'未保存的修改'})).toBeVisible();
 await page.getByRole('button',{name:'继续编辑',exact:true}).click();
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('new.example.test/path?q=1#start');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
test('图标中文实际SVG预览，编辑同一网站后侧栏名称图标一致',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByLabel('显示名称',{exact:true}).fill('统一新名字');
 await page.getByRole('button',{name:'选择图标',exact:false}).click();
 const pick=page.getByRole('radio',{name:'服务器',exact:true});
 await expect(pick.locator('svg path').first()).toHaveAttribute('d','M2 2h20v8H2z');
 await pick.click();
 await expect(page.getByLabel('侧栏效果')).toHaveText('统一新名字');
 await expect(page.getByLabel('侧栏效果').locator('svg path').first()).toHaveAttribute('d','M2 2h20v8H2z');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 await expect(page.locator('aside [data-nav-id="quota"]')).toHaveText('统一新名字');
 await expect(page.getByText('条目已更新并回读',{exact:true})).toBeVisible();
 await expect(page.locator('aside [data-nav-id="quota"] svg path').first()).toHaveAttribute('d','M2 2h20v8H2z');
 expect(f.requests.filter(x=>x.path==='/website-settings/quota')).toHaveLength(1);
 await page.getByRole('button',{name:'编辑 统一新名字',exact:true}).click();
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('统一新名字');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('首次新增可以保存CSS和JS草稿；不执行，不支持注入给具体原因',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('draft.example.test');
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 await page.getByLabel('自定义 CSS',{exact:true}).fill('body{color:red}');
 await page.getByLabel('自定义 JavaScript',{exact:true}).fill('window.__shouldNotRun=true');
 await page.getByRole('button',{name:'检测',exact:true}).click();
 await expect(page.getByText('跨域直连不能修改 DOM',{exact:true}).first()).toBeVisible();
 await expect(page.getByRole('button',{name:'应用保存的版本',exact:true})).toBeDisabled();
 expect(await page.evaluate(()=> (window as any).__shouldNotRun)).toBeUndefined();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.requests.find(x=>x.path==='/website-settings').body.custom).toEqual({enabled:false,css:'body{color:red}',js:'window.__shouldNotRun=true',timing:'dom_ready'});
 expect(f.requests.filter(x=>x.path.endsWith('/apply')||x.path.endsWith('/validate'))).toEqual([]);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('保存成功但列表回读失败只重试读回，不能重建或关闭草稿',async({page})=>{
 const f=await fixture(page,{failNavigation:true});
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('readback.example.test');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByRole('button',{name:'重试回读',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'保存',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'重试回读',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.requests.filter(x=>x.path==='/website-settings')).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('创建响应丢失仅以相同幂等键和冻结payload重试',async({page})=>{
 const f=await fixture(page,{loseCreateResponse:true});
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('uncertain.example.test');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByRole('button',{name:'确认保存结果',exact:true})).toBeVisible();
 await expect(page.getByLabel('网站地址',{exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'下移 额度',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'确认保存结果',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 const creates=f.requests.filter(x=>x.path==='/website-settings');
 expect(creates).toHaveLength(2);expect(creates[0].body).toEqual(creates[1].body);
 expect(f.modules.filter(x=>x.id==='created')).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('内置条目仍在统一行编辑名称图标，图标别名未知值非空',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'编辑 笔记',exact:true}).click();
 await page.getByLabel('显示名称',{exact:true}).fill('我的笔记');
 await page.getByRole('button',{name:'选择图标'}).click();
 await page.getByRole('radio',{name:'书籍',exact:true}).click();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('aside [data-nav-id="notes"]')).toHaveText('我的笔记');
 for(const id of ['file-text','hard-drive','unknown-icon'])await expect(page.locator('[data-icon-test="'+id+'"] path').first()).toHaveAttribute('d',/.+/);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('真实SettingsPage只保留一个列表，内置深链唯一设置源位于所选行',async({page})=>{
 const f=await fixture(page,{full:true,module:'drive'});
 await expect(page.locator('.nav-row')).toHaveCount(8);
 await expect(page.locator('[data-row-id="drive"] .inline-editor')).toBeVisible();
 await expect(page.locator('[data-row-id="drive"] .service-editor')).toHaveCount(1);
 await expect(page.locator('.builtin-settings,.connection-inline')).toHaveCount(0);
 await expect(page.locator('.website-row')).toHaveCount(0);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('真实iframe load只收起加载占位，不宣称成功也不显示调试说明',async({page})=>{
 const f=await fixture(page,{external:true});
 await expect(page.frameLocator('.external-page iframe').getByText('Actual isolated iframe content')).toBeVisible();
 await expect(page.locator('.external-page')).toHaveText('');
 await expect(page.locator('.external-page header')).toHaveCount(0);
 await expect(page.locator('.external-page')).not.toContainText('已导航');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('已知CSP阻断给简短提示和集中设置入口，不创建iframe',async({page})=>{
 const f=await fixture(page,{external:true,blockedCheck:true});
 await expect(page.locator('.external-page')).toContainText('该网站不允许在这里打开');
 await expect(page.locator('.external-page').getByRole('link',{name:'连接设置',exact:true})).toHaveAttribute('href','/settings?section=navigation&module=quota');
 await expect(page.locator('.external-page iframe')).toHaveCount(0);
 expect(f.requests.filter(x=>x.path.endsWith('/launch'))).toHaveLength(0);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('支持注入时主动应用走同一保存事务，不调用草稿审批API',async({page})=>{
 const f=await fixture(page,{supported:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 await page.getByRole('button',{name:'检测',exact:true}).click();
 await page.getByRole('button',{name:'应用保存的版本',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 const write=f.requests.find(x=>x.path==='/website-settings/quota');expect(write.body.custom.enabled).toBe(true);
 expect(f.requests.filter(x=>x.path.endsWith('/validate')||x.path.endsWith('/apply'))).toHaveLength(0);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

for(const width of [1440,390])test('真实设置布局和关闭按钮 '+width,async({page},testInfo)=>{
 await page.setViewportSize({width,height:width===390?844:1000});
 const f=await fixture(page,{full:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByRole('button',{name:'选择图标'}).click();
 await expect(page.getByRole('radiogroup',{name:'图标选择'})).toBeVisible();
 const metrics=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,nameWidth:document.querySelector<HTMLInputElement>('[aria-label="显示名称"]')!.getBoundingClientRect().width,rowId:document.querySelector('.inline-editor')!.parentElement!.getAttribute('data-row-id'),closeButtons:document.querySelectorAll('[aria-label="收起编辑"]').length}));
 expect(metrics.nameWidth).toBeGreaterThanOrEqual(200);expect(metrics.nameWidth).toBeLessThanOrEqual(240);expect(metrics.scroll).toBeLessThanOrEqual(width);expect(metrics.rowId).toBe('quota');expect(metrics.closeButtons).toBe(1);
 await testInfo.attach('DOM-widths',{body:JSON.stringify(metrics),contentType:'application/json'});
 await page.screenshot({path:process.env.TMPDIR+'/stella-website-'+width+'.png',fullPage:true});
 await page.getByRole('button',{name:'收起编辑',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('删除需明确确认，精确404与导航回读后关闭；不触碰原站',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'编辑 第二网站',exact:true}).click();
 await page.getByRole('button',{name:'删除网站入口',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'删除网站入口'})).toContainText('不删除原网站数据');
 expect(f.modules).toHaveLength(2);
 await page.getByRole('button',{name:'确认删除入口',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'编辑 第二网站',exact:true})).toHaveCount(0);
 expect(f.requests.filter(x=>x.method==='DELETE').map(x=>x.path)).toEqual(['/external-modules/second']);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('回退保留既有API并核对活动版本，不把本地代码执行作预览',async({page})=>{
 const f=await fixture(page,{previous:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 await page.getByRole('button',{name:'回退上一版本',exact:true}).click();
 await expect(page.getByText('已回退并回读活动版本；已打开的网站请手动重载。',{exact:true})).toBeVisible();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('previous');
 expect(f.requests.filter(x=>x.path.endsWith('/rollback'))).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('内置深链加载后名称正确，唯一服务代码草稿切行也提示保留',async({page})=>{
 const f=await fixture(page,{full:true,module:'drive'});
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('网盘');
 await page.locator('.service-editor .advanced > summary').click();
 await page.getByLabel('自定义 CSS',{exact:true}).fill('unsaved builtin CSS');
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'未保存的修改'})).toBeVisible();
 await page.getByRole('button',{name:'继续编辑',exact:true}).click();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('unsaved builtin CSS');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('迟到检测不能覆盖改后的URL或手写名称，未知状态不冒充已连接',async({page})=>{
 const f=await fixture(page);let release:()=>void=()=>{};let seen:()=>void=()=>{};
 let done:()=>void=()=>{};const finished=new Promise<void>(resolve=>done=resolve);
 const started=new Promise<void>(resolve=>seen=resolve),wait=new Promise<void>(resolve=>release=resolve);
 await page.route('**/website-settings/check',async route=>{const body=route.request().postDataJSON();seen();await wait;await route.fulfill({json:checked(body.address)}).catch(()=>{});done();});
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('old.example.test');
 await page.getByRole('button',{name:'检测',exact:true}).click();await started;
 await page.getByLabel('网站地址',{exact:true}).fill('latest.example.test/path?q=1#last');
 await page.getByLabel('显示名称',{exact:true}).fill('手写名称');release();await finished;
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('latest.example.test/path?q=1#last');
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('手写名称');
 await expect(page.getByLabel('检测结果')).toHaveCount(0);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
test('已知阻断不能保存为嵌入，用户显式选新窗口后自动重检才保存',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'添加网站'}).click();await page.getByLabel('网站地址',{exact:true}).fill('blocked.example.test');
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.getByText('/etc/nginx/conf.d/quota.conf',{exact:true})).toBeVisible();
 expect(f.requests.filter(x=>x.path==='/website-settings')).toHaveLength(0);
 await page.getByLabel('打开方式',{exact:true}).selectOption('external');
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.requests.filter(x=>x.path==='/website-settings/check').at(-1).body.open_behavior).toBe('external');
 expect(f.requests.find(x=>x.path==='/website-settings').body.open_behavior).toBe('external');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('跨origin改址不会自动继承活动脚本启用状态',async({page})=>{
 const f=await fixture(page,{previous:true});f.modules[0].injection.active.enabled=true;
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();
 const enabled=page.getByRole('checkbox',{name:'保存时启用自定义'});await expect(enabled).toBeChecked();
 await page.getByLabel('网站地址',{exact:true}).fill('different.example.test');await expect(enabled).not.toBeChecked();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('current');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('代码草稿读回不一致必须留在编辑区并允许重试回读',async({page})=>{
 const f=await fixture(page,{corruptReadback:true});
 await page.getByRole('button',{name:'添加网站'}).click();await page.getByLabel('网站地址',{exact:true}).fill('draftreadback.example.test');
 await page.getByText('自定义外观与脚本（可选）',{exact:true}).click();await page.getByLabel('自定义 CSS',{exact:true}).fill('body{color:red}');
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.getByRole('button',{name:'重试回读',exact:true})).toBeEnabled();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:red}');
 expect(f.requests.filter(x=>x.path==='/website-settings')).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('隐藏排序读回后保留；网站导航不再写名称图标影子配置',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('checkbox',{name:'显示导航 额度',exact:true}).uncheck();
 await expect(page.locator('aside [data-nav-id="quota"]')).toHaveCount(0);
 const write=f.requests.find(x=>x.path==='/navigation'&&x.method==='PUT');expect(write.body.entries.find((x:any)=>x.id==='quota')).toEqual({id:'quota',visible:false});
 await page.getByRole('button',{name:'上移 第二网站',exact:true}).click();await expect(page.getByText('导航已同步',{exact:true})).toBeVisible();
 await page.reload();await expect(page.getByRole('checkbox',{name:'显示导航 额度',exact:true})).not.toBeChecked();
 const ids=await page.locator('[data-row-id]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-row-id')));expect(ids.indexOf('second')).toBeLessThan(ids.indexOf('settings'));
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('名称清空仍只有地址必填，保存省略空名称给服务端建议',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'添加网站'}).click();await page.getByLabel('网站地址',{exact:true}).fill('nameoptional.example.test');
 await page.getByLabel('显示名称',{exact:true}).fill('tmp');await page.getByLabel('显示名称',{exact:true}).fill('');
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.requests.find(x=>x.path==='/website-settings').body).not.toHaveProperty('name');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('切换设置分类也不能静默丢失草稿',async({page})=>{
 const f=await fixture(page,{full:true});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();await page.getByLabel('网站地址',{exact:true}).fill('unsaved.example.test');
 await page.getByRole('button',{name:'资料与安全',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'未保存的修改'})).toBeVisible();await page.getByRole('button',{name:'继续编辑',exact:true}).click();
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('unsaved.example.test');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const width of [1440,390])test('新增草稿检测与保存422具体帮助 '+width,async({page})=>{
 await page.setViewportSize({width,height:1000});const f=await fixture(page);
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByLabel('网站地址',{exact:true}).fill('bare.example.test/path?q=1#start');
 await page.getByRole('button',{name:'检测',exact:true}).click();
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('https://bare.example.test/path?q=1#start');
 expect(f.requests.filter(x=>x.method!=='GET').map(x=>x.path)).toEqual(['/website-settings/check']);
 expect(f.requests.at(-1).body).toEqual({address:'bare.example.test/path?q=1#start',open_behavior:'embedded',custom_enabled:false});
 await page.getByLabel('显示名称',{exact:true}).fill('人为名字');
 await page.getByLabel('网站地址',{exact:true}).fill('race.example.test/edited?q=2#changed');
 await expect(page.getByText('需重新检测',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByText('/etc/nginx/conf.d/quota.conf',{exact:true})).toBeVisible();
 await expect(page.getByLabel('显示名称',{exact:true})).toHaveValue('人为名字');
 await expect(page.getByLabel('网站地址',{exact:true})).toHaveValue('https://race.example.test/edited?q=2#changed');
 expect(f.requests.filter(x=>x.path==='/website-settings/check')).toHaveLength(2);
 expect(f.requests.find(x=>x.path==='/website-settings').body).toMatchObject({address:'https://race.example.test/edited?q=2#changed',name:'人为名字',visible:true,open_behavior:'embedded',keep_alive:false,custom:{enabled:false,css:'',js:'',timing:'dom_ready'}});
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
