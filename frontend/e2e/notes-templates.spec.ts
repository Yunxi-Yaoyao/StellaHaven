import {test,expect,chromium,type Browser,type Page} from '@playwright/test';
let browser:Browser;let page:Page;let creates:any[];let docWrites:string[];
const body='## 私有事件模板\n\n- [ ] 验证和回滚';
const base={id:'source',title:'我的事件模板',workspace_id:'ws-a',parent_id:null,content:body,file_path:'/source.md',updated_at:'2026-09-09T00:00:00Z',created_at:'2026-09-09T00:00:00Z',status:'published',has_draft:false,is_folder:false,is_favorite:false,is_pinned:false};
test.beforeAll(async()=>{browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox']});});
test.afterAll(async()=>{await browser.close();});
test.beforeEach(async()=>{
 page=await browser.newPage({viewport:{width:1440,height:1000}});creates=[];docWrites=[];const docs:any[]=[{...base}];let tags:any[]=[{id:'tag-template',name:'模板'}];let joins:any[]=[];
 await page.route('**/*',async route=>{const r=route.request();const u=new URL(r.url());const p=u.pathname;const ok=(json:any)=>route.fulfill({json});if(u.hostname!=='127.0.0.1')return route.abort();
 if(p==='/auth/me')return ok({id:'user-a',username:'test',is_admin:true});
 if(p.startsWith('/workspaces/'))return ok(p==='/workspaces/'?[{id:'ws-a',name:'测试工作区'}]:{id:'ws-a'});
 if(p==='/tags/')return ok(tags);
 if(p==='/doc-tags/'){if(r.method()==='POST'){joins.push(r.postDataJSON());return ok(joins.at(-1));}if(r.method()==='DELETE'){joins=[];return route.fulfill({status:204});}return ok(u.searchParams.has('doc_id')?joins.filter(x=>x.doc_id===u.searchParams.get('doc_id')):joins);}
 if(p==='/documents/'){if(r.method()==='POST'){const payload=r.postDataJSON();creates.push(payload);const doc={...base,...payload,id:`created-${creates.length}`};docs.push(doc);return ok(doc);}return ok(docs);}
 const doc=docs.find(d=>p===`/documents/${d.id}`);if(doc){if(r.method()!=='GET')docWrites.push(r.method());return ok(doc);}
 if(p.startsWith('/documents/')||p.startsWith('/attachments/')||p.startsWith('/document-links/'))return ok([]);
 if(p.startsWith('/auth/')||p.startsWith('/api/'))return ok({});return route.continue();});
 await page.addInitScript(()=>{localStorage.clear();localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'user-a',workspaceId:'ws-a'}));});
 await page.goto('http://127.0.0.1:5173/notes');await expect(page.locator('.title-readonly')).toHaveText(base.title);
});
test.afterEach(async()=>{await page.close();});
test('mark saved page as reusable template then create a root copy without touching source',async()=>{
 await page.getByRole('button',{name:'设为模板',exact:true}).click();await expect(page.getByRole('button',{name:'移出模板库',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'新建笔记',exact:true}).click();const dialog=page.getByRole('dialog',{name:'新建笔记'});await expect(dialog).toBeVisible();
 await dialog.getByRole('button',{name:base.title,exact:true}).click();await expect(dialog.locator('.template-preview')).toContainText('私有事件模板');
 await dialog.getByLabel('标题',{exact:true}).fill('9月事件');await dialog.getByRole('button',{name:'创建',exact:true}).click();
 await expect.poll(()=>creates.length).toBe(1);expect(creates[0]).toMatchObject({title:'9月事件',content:body,parent_id:null,workspace_id:'ws-a'});expect(docWrites).toEqual([]);
});
test('built-in event template and mobile dialog are usable without source writes',async()=>{
 await page.setViewportSize({width:390,height:844});await page.reload();await page.locator('.list-strip').click();await page.getByRole('button',{name:'新建笔记',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'新建笔记'});await dialog.getByRole('button',{name:'事件记录模板',exact:true}).click();
 await expect(dialog.locator('.template-preview')).toContainText('回滚');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'/tmp/stella-templates-mobile.png',fullPage:true});await dialog.getByRole('button',{name:'创建',exact:true}).click();
 await expect.poll(()=>creates.length).toBe(1);expect(creates[0].content).toContain('## 时间线');expect(docWrites).toEqual([]);
});
test('unmark does not delete the source and missing template cannot create empty copy',async()=>{
 await page.getByRole('button',{name:'设为模板',exact:true}).click();await page.getByRole('button',{name:'移出模板库',exact:true}).click();await expect(page.getByRole('button',{name:'设为模板',exact:true})).toBeVisible();expect(docWrites).toEqual([]);
 await page.getByRole('button',{name:'设为模板',exact:true}).click();await page.getByRole('button',{name:'新建笔记',exact:true}).click();
 await page.route('**/documents/source',r=>r.fulfill({status:404,json:{detail:'not found'}}));
 const dialog=page.getByRole('dialog',{name:'新建笔记'});await dialog.getByRole('button',{name:base.title,exact:true}).click();await expect(dialog.getByRole('alert')).toBeVisible();await expect(dialog.getByRole('button',{name:'创建',exact:true})).toBeDisabled();expect(creates).toEqual([]);
});
