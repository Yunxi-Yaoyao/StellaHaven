import {test,expect} from '@playwright/test';
import {fixture} from './fixtures/websiteSettings';
import {templates,legacyRoutes} from './fixtures/websiteTemplates';
for(const template of templates)test('模板选择立即展示真实可编辑 CSS/JS '+template.id,async({page})=>{
 const f=await fixture(page,{supported:true});
 await page.getByRole('button',{name:'添加网站'}).click();
 await page.getByRole('button',{name:'模板',exact:true}).click();
 await page.getByRole('button',{name:template.name,exact:true}).click();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toBeVisible();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue(template.draft.custom.css);
 await expect(page.getByLabel('自定义 JavaScript',{exact:true})).toHaveValue(template.draft.custom.js);
 expect(await page.evaluate(()=>document.documentElement.dataset.template)).toBeUndefined();
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const [legacy,id] of Object.entries(legacyRoutes))test('已有网站编辑优先生效代码而非空草稿 '+legacy,async({page})=>{
 const f=await fixture(page,{migrated:true,full:true,module:id});
 const actual=f.modules.find(x=>x.id===id);
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toBeVisible();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue(actual.injection.active.css);
 await expect(page.getByLabel('自定义 JavaScript',{exact:true})).toHaveValue(actual.injection.active.js);
 await expect(page.locator('[data-row-id="'+id+'"]')).not.toContainText('内置页面');
 await expect(page.locator('select,.service-editor')).toHaveCount(0);
 expect(f.requests.filter(x=>x.path.startsWith('/auth/admin')||x.path.startsWith('/service-settings')||x.path.startsWith('/builtin-injections'))).toEqual([]);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

for(const [legacy,id] of Object.entries(legacyRoutes))test('旧设置别名只打开同一通用网站 '+legacy,async({page})=>{
 const f=await fixture(page,{migrated:true,full:true,module:legacy});
 await expect(page.locator('[data-row-id="'+id+'"] .inline-editor')).toBeVisible();
 await expect(page.locator('[data-row-id="drive"],[data-row-id="gallery"],.service-editor')).toHaveCount(0);
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue(f.modules.find(x=>x.id===id).injection.active.css);
 expect(f.requests.filter(x=>x.path.startsWith('/service-settings')||x.path.startsWith('/builtin-injections'))).toEqual([]);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('保存连接背景不一致必须冻结回读，不谎报已保存',async({page})=>{
 const f=await fixture(page,{migrated:true,module:legacyRoutes.drive,supported:true});
 await page.getByRole('button',{name:'背景',exact:true}).click();await page.getByRole('button',{name:'纯色背景',exact:true}).click();
 let writes=0;page.on('request',req=>{if(req.method()==='PATCH')writes++;});
 await page.route('**/external-modules/'+legacyRoutes.drive,route=>route.fulfill({json:{...f.modules.find(x=>x.id===legacyRoutes.drive),background:writes?'home':'home'}}));
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.getByRole('button',{name:'重试回读',exact:true})).toBeEnabled();
 await expect(page.getByRole('button',{name:'保存',exact:true})).toBeDisabled();
 expect(writes).toBe(1);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

for(const template of templates)test('模板副本改代码保存读回并独立删除 '+template.id,async({page})=>{
 const f=await fixture(page,{supported:true});
 await page.getByRole('button',{name:'添加网站'}).click();await page.getByRole('button',{name:'模板',exact:true}).click();await page.getByRole('button',{name:template.name,exact:true}).click();
 await page.getByLabel('自定义 CSS',{exact:true}).fill(template.draft.custom.css+'\n/* my independent code */');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 const write=f.requests.find(x=>x.path==='/website-settings');expect(write.body).toMatchObject({template_id:template.id,connection:template.draft.connection,background:template.draft.background,request_policy:template.draft.request_policy});
 const created=f.modules.find(x=>x.id==='created');expect(created.injection.active.css).toContain('my independent code');
 await page.getByRole('button',{name:'编辑 '+template.draft.name,exact:true}).click();await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue(created.injection.active.css);
 await page.getByRole('button',{name:'删除网站入口',exact:true}).click();await page.getByRole('button',{name:'确认删除入口',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.modules.find(x=>x.id==='created')).toBeUndefined();expect(templates.find(x=>x.id===template.id)!.draft.custom.css).not.toContain('my independent code');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual(['Failed to load resource: the server responded with a status of 404 (Not Found)']);
});

test('已有网站只改名称保留独立草稿与masked凭据',async({page})=>{
 const f=await fixture(page,{migrated:true,module:legacyRoutes.drive,supported:true});
 const item=f.modules.find(x=>x.id===legacyRoutes.drive);const savedDraft=JSON.stringify(item.injection.draft);
 await expect(page.getByLabel('Token',{exact:true})).toHaveValue('');await expect(page.getByLabel('Token',{exact:true})).toHaveAttribute('type','password');
 await page.getByLabel('显示名称',{exact:true}).fill('我的独立网盘');await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 const body=f.requests.find(x=>x.method==='PATCH').body;expect(body).not.toHaveProperty('custom');expect(body.connection).toMatchObject({token:null,clear_token:false});expect(JSON.stringify(item.injection.draft)).toBe(savedDraft);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('更新结果丢失只精确回读，冻结期间不重发PATCH',async({page})=>{
 const f=await fixture(page,{migrated:true,module:legacyRoutes.gallery,supported:true});
 await page.getByLabel('自定义 CSS',{exact:true}).fill('body {color:pink}');
 let reads=0;
 await page.route('**/external-modules/'+legacyRoutes.gallery,route=>{reads++;return route.fulfill({status:503,json:{detail:'Owned readback failure'}});});
 await page.route('**/website-settings/'+legacyRoutes.gallery,route=>route.abort('failed'));
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.getByRole('button',{name:'重试回读',exact:true})).toBeEnabled();
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toBeDisabled();await page.getByRole('button',{name:'重试回读',exact:true}).click();expect(reads).toBe(2);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

test('切换生效代码与草稿保留两边修改且不能静默离开',async({page})=>{
 const f=await fixture(page,{savedDraft:true});await page.getByRole('button',{name:'编辑 额度',exact:true}).click();
 await page.getByRole('button',{name:'已保存草稿',exact:true}).click();await page.getByLabel('自定义 CSS',{exact:true}).fill('body{color:orange}');
 await page.getByRole('button',{name:'当前生效代码',exact:true}).click();await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:green}');
 await page.getByRole('button',{name:'编辑 第二网站',exact:true}).click();await expect(page.getByRole('dialog',{name:'未保存的修改'})).toBeVisible();
 await page.getByRole('button',{name:'继续编辑',exact:true}).click();await page.getByRole('button',{name:'已保存草稿',exact:true}).click();await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('body{color:orange}');
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('通用主页背景只铺外层，不秘密改写浅色原站',async({page})=>{
 const f=await fixture(page,{external:true,backgroundHome:true});const frame=page.frameLocator('.external-page iframe');await expect(frame.getByText('Actual isolated iframe content')).toBeVisible();
 expect(await page.locator('.external-page').evaluate(el=>getComputedStyle(el).backgroundImage)).toContain('/owned-bg.svg');
 expect(await page.locator('.external-page iframe').evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
 expect(await frame.locator('body').evaluate(el=>getComputedStyle(el).backgroundColor)).toBe('rgb(245, 245, 245)');
 expect(await frame.locator('body').getAttribute('style')).toBeNull();
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('恢复模板需要确认且取消保留未保存代码',async({page})=>{
 const f=await fixture(page,{migrated:true,module:legacyRoutes.gallery});await page.getByLabel('自定义 CSS',{exact:true}).fill('/* do not lose */');
 await page.getByRole('button',{name:'恢复模板代码',exact:true}).click();await expect(page.getByRole('dialog',{name:'替换模板'})).toBeVisible();
 await page.getByRole('button',{name:'继续编辑',exact:true}).click();await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('/* do not lose */');
 await page.getByRole('button',{name:'恢复模板代码',exact:true}).click();await page.getByRole('button',{name:'确认替换模板',exact:true}).click();await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue(templates[1]!.draft.custom.css);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

for(const width of [1440,390])test('模板真实代码视觉验收 '+width,async({page},testInfo)=>{
 await page.setViewportSize({width,height:1000});const f=await fixture(page,{migrated:true,full:true,module:legacyRoutes.gallery});
 await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue(templates[1]!.draft.custom.css);await expect(page.getByLabel('自定义 JavaScript',{exact:true})).toHaveValue(templates[1]!.draft.custom.js);
 const metrics=await page.evaluate(()=>({nameWidth:document.querySelector('[aria-label="显示名称"]')!.getBoundingClientRect().width,scroll:document.documentElement.scrollWidth,forms:document.querySelectorAll('form.inline-editor').length,selects:document.querySelectorAll('select').length}));
 expect(metrics.nameWidth).toBe(220);expect(metrics.scroll).toBeLessThanOrEqual(width);expect(metrics.forms).toBe(1);expect(metrics.selects).toBe(0);
 await testInfo.attach('template-layout',{body:JSON.stringify(metrics),contentType:'application/json'});
 await page.screenshot({path:process.env.TMPDIR+'/stella-generic-template-'+width+'.png',fullPage:true,animations:'disabled'});
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('活动代码与提交不同不能仅凭草稿一致声称已启用',async({page},testInfo)=>{
 const f=await fixture(page,{migrated:true,module:legacyRoutes.gallery,supported:true});
 await page.getByLabel('自定义 CSS',{exact:true}).fill('body {color:orange}');
 await page.route('**/external-modules/'+legacyRoutes.gallery,route=>{const item=f.modules.find(x=>x.id===legacyRoutes.gallery);return route.fulfill({json:{...item,injection:{...item.injection,active:{...item.injection.active,css:'body {color:old}'}}}});});
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.getByRole('button',{name:'重试回读',exact:true})).toBeEnabled();
 await expect(page.getByRole('button',{name:'保存',exact:true})).toBeDisabled();expect(f.requests.filter(x=>x.method==='PATCH')).toHaveLength(1);
 await testInfo.attach('active-mismatch',{body:JSON.stringify({requests:f.requests,module:f.modules.find(x=>x.id===legacyRoutes.gallery)}),contentType:'application/json'});
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('旧quota缺新字段改名保留隔离代理与既有目标',async({page})=>{
 const f=await fixture(page);Object.assign(f.modules[0],{mode:'isolated_proxy',target_id:'owned-fixed-target',initial_path:'/quota/',browser_url:'http://10.20.30.40/quota/'});
 await page.getByRole('button',{name:'编辑 额度',exact:true}).click();await page.getByLabel('显示名称',{exact:true}).fill('保留代理额度');
 await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 const body=f.requests.find(x=>x.method==='PATCH').body;expect(body).not.toHaveProperty('connection');expect(f.modules[0]).toMatchObject({mode:'isolated_proxy',target_id:'owned-fixed-target',initial_path:'/quota/'});
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});

test('已有模板修改代码仍以同一PATCH保存并读回当前生效',async({page},testInfo)=>{
 const f=await fixture(page,{migrated:true,module:legacyRoutes.gallery,supported:true});await page.getByLabel('自定义 CSS',{exact:true}).fill('body { color:orange }');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await testInfo.attach('existing-save',{body:JSON.stringify({requests:f.requests,module:f.modules.find(x=>x.id===legacyRoutes.gallery)}),contentType:'application/json'});
 await expect(page.locator('.inline-editor')).toHaveCount(0);
 expect(f.modules.find(x=>x.id===legacyRoutes.gallery).injection.active.css).toBe('body { color:orange }');expect(f.requests.filter(x=>x.method==='PATCH')).toHaveLength(1);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.consoleErrors).toEqual([]);
});
