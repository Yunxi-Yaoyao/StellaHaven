import {test,expect,type Page} from '@playwright/test';
const out='/opt/hermes-workstation/docs/2026-10-06-Stella-upgrade/notes-features';
const ws='11111111-1111-4111-8111-111111111111', id='22222222-2222-4222-8222-222222222222';
async function mock(page:Page) {
 const calls:{path:string,method:string,body:any}[]=[];
 const state={elevated:false};
 const doc:any={id,title:'版本验收',file_path:'/test.md',workspace_id:ws,parent_id:null,content:'# 当前正文\n\n保存内容',content_hash:'hash',updated_at:'2026-10-06T00:00:00',created_at:'2026-10-06T00:00:00',has_draft:false,status:'published',is_folder:false,is_favorite:false,is_pinned:false};
 const docs=[doc];
 const me={id:'mock-owner',username:'test',display_name:'测试',is_admin:true,email:'',email_verified:false};
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(url.origin==='http://127.0.0.1:15174' && (p==='/notes'||p==='/'||p.startsWith('/e2e/')||p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||/\.(svg|png|woff2)$/.test(p)))return route.continue();
  const body=req.postDataJSON();calls.push({path:p,method:req.method(),body});
  const ok=(json:any)=>route.fulfill({json});
  if(p==='/auth/me'||p==='/auth/refresh')return ok(me);
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:state.elevated,single_user:true,setup_required:false});
  if(p==='/auth/admin/unlock'){state.elevated=true;return ok({enabled:true,configured:true,elevated:true});}
  if(p==='/navigation')return ok({entries:[]});
  if(p==='/external-modules')return ok([]);
  if(p.startsWith('/workspaces/'))return ok(p==='/workspaces/'?[{id:ws,name:'验收工作区',user_id:me.id}]:{id:ws,name:'验收工作区',user_id:me.id});
  if(p==='/documents/')return ok(docs.map(d=>({...d,content:undefined})));
  if(p===`/documents/${id}`){if(req.method()==='PUT')Object.assign(doc,body,{updated_at:'2026-10-06T00:01:00'});return ok(doc);}
  if(p.startsWith('/documents/')&&/\/documents\/[0-9a-f-]{36}$/.test(p)){return ok(docs.find(d=>d.id===p.split('/')[2]));}
  if(p==='/document-versions/')return ok([{id:'version-1',doc_id:id,version_no:1,created_at:'2026-10-05T00:00:00'}]);
  if(p==='/document-versions/version-1/diff')return ok({diff:'--- version\n+++ current\n-旧正文\n+当前正文'});
  if(p==='/document-versions/version-1/restore'){
   if(!state.elevated)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
   doc.content='# 旧正文';doc.updated_at='2026-10-06T00:02:00';return ok(doc);
  }
  if(p==='/notes-tools/quick-record'){
   const captured={...doc,...body,id:'33333333-3333-4333-8333-333333333333',parent_id:'inbox'};docs.push(captured);return route.fulfill({status:201,json:captured});
  }
  if(p===`/notes-tools/documents/${id}/node`)return ok({node_id:1});
  if(p==='/timeline')return ok({items:[{kind:'node_status',id:'1',label:'心跳超时',state:'offline',ts:'2026-10-06T00:00:00Z',node_id:1,path:'/status/1'}],has_more:false});
  if(p==='/nodes/')return ok([{id:1,name:'验收节点',status:'online'}]);
  if(p==='/search')return ok({items:[{kind:'note',id,label:doc.title,path:'/notes?doc='+id},{kind:'node_status',id:'1',label:'心跳超时',path:'/status/1'}]});
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/config/public-host'||p==='/config/site-background')return ok({value:''});
  if(p.startsWith('/tags/')||p.startsWith('/doc-tags/')||p.startsWith('/attachments/')||p.startsWith('/document-links/')||p.startsWith('/documents/'))return ok([]);
  if(p.startsWith('/auth/')||p.startsWith('/api/'))return ok({});
  return route.fulfill({status:501,json:{detail:'Unmocked blocked: '+p}});
 });
 await page.addInitScript(({ws})=>{localStorage.clear();localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'mock-owner',workspaceId:ws}));},{ws});
 return {calls,state,doc};
}
test('version diff and confirmed elevated restore update the real editor once',async({page})=>{
 const m=await mock(page);await page.goto('/notes');
 await page.getByRole('button',{name:'版本历史',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'版本历史'})).toBeVisible();
 await page.getByRole('button',{name:'查看差异 v1',exact:true}).click();
 await expect(page.locator('.version-diff')).toContainText('-旧正文');
 await page.getByRole('button',{name:'恢复 v1',exact:true}).click();
 await expect(page.getByRole('button',{name:'确认恢复版本',exact:true})).toBeVisible();
 expect(m.calls.filter(c=>c.path.endsWith('/restore'))).toHaveLength(0);
 await page.getByRole('button',{name:'确认恢复版本',exact:true}).click();
 await expect(page.getByLabel('管理密码',{exact:true})).toBeVisible();
 expect(m.calls.filter(c=>c.path.endsWith('/restore'))).toHaveLength(1);
 await page.getByLabel('管理密码',{exact:true}).fill('MOCK_ADMIN_ONLY');
 await page.getByRole('button',{name:'验证管理权限',exact:true}).click();
 await page.getByRole('button',{name:'确认重试一次',exact:true}).click();
 await expect(page.locator('.preview h1')).toHaveText('旧正文');
 expect(m.calls.filter(c=>c.path.endsWith('/restore'))).toHaveLength(2);
 expect(m.calls.filter(c=>c.method==='PUT'&&c.path.startsWith('/documents/'))).toHaveLength(0);
 await page.screenshot({path:out+'/version-restored.png',fullPage:true});
});

test('quick capture creates in current workspace and opens the actual rich editor',async({page})=>{
 const m=await mock(page);await page.goto('/notes');
 await page.getByRole('button',{name:'快捷记录',exact:true}).click();
 expect(m.calls.filter(c=>c.path==='/notes-tools/quick-record')).toHaveLength(0);
 await page.getByLabel('记录标题',{exact:true}).fill('灵感记录');
 await page.getByLabel('记录正文',{exact:true}).fill('# 快捷灵感\n\n不丢正文');
 await page.getByRole('button',{name:'保存并打开',exact:true}).click();
 await expect(page.locator('.preview h1')).toHaveText('快捷灵感');
 expect(m.calls.filter(c=>c.path==='/notes-tools/quick-record')[0]?.body.workspace_id).toBe(ws);
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 await expect(page.locator('.rich-editor .ProseMirror')).toContainText('不丢正文');
 await page.screenshot({path:out+'/quick-record-rich-editor.png',fullPage:true});
});

test('note node association exposes existing record timeline without dispatch',async({page})=>{
 const m=await mock(page);await page.goto('/notes');
 await page.getByRole('button',{name:'关联时间线',exact:true}).click();
 await expect(page.getByText('心跳超时',{exact:true})).toBeVisible();
 await expect(page.getByLabel('关联节点',{exact:true})).toHaveValue('1');
 expect(m.calls.filter(c=>c.path==='/timeline')).toHaveLength(1);
 expect(m.calls.filter(c=>c.method==='POST'&&c.path.includes('/tasks'))).toHaveLength(0);
 await page.screenshot({path:out+'/note-timeline.png',fullPage:true});
});

test('global palette keyboard metadata search and quick capture reach the real editor',async({page})=>{
 const m=await mock(page);await page.goto('/notes');
 await expect(page.locator('.preview h1')).toBeVisible();
 const mounted=await page.evaluate(async()=>{const path='/e2e/palette-mount.ts';const mod=await import(path);return mod.mountPaletteHarness();});
 console.log('Palette integration:',mounted?'test-only mount (App.vue owned by parent)':'actual App.vue mount');
 await page.keyboard.press('Control+k');
 await expect(page.getByRole('dialog',{name:'统一搜索与快捷命令'})).toBeVisible();
 await page.getByLabel('统一搜索',{exact:true}).fill('版本');
 await expect(page.getByRole('option').filter({hasText:'版本验收'})).toBeVisible();
 expect(m.calls.filter(c=>c.path==='/search')).toHaveLength(1);
 await page.screenshot({path:out+'/unified-search.png',fullPage:true});
 await page.getByRole('button',{name:'快捷记录',exact:true}).last().click();
 await page.getByLabel('记录标题',{exact:true}).fill('全局灵感');
 await page.getByLabel('记录正文',{exact:true}).fill('# 全局面板记录');
 await page.getByRole('button',{name:'保存并打开',exact:true}).click();
 await expect(page.locator('.preview h1')).toHaveText('全局面板记录');
 expect(m.calls.filter(c=>c.path==='/notes-tools/quick-record')).toHaveLength(1);
});

test('read-only version history does not save dirty content and closes on leaving notes',async({page})=>{
 const m=await mock(page);await page.goto('/notes');
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 const editor=page.locator('.rich-editor .ProseMirror');
 await editor.locator('h1').click();await page.keyboard.press('End');await page.keyboard.type(' unsaved');
 await page.getByRole('button',{name:'版本历史',exact:true}).click();
 await expect(page.getByRole('button',{name:'恢复 v1',exact:true})).toBeDisabled();
 expect(m.calls.filter(c=>c.method==='PUT'&&c.path.startsWith('/documents/'))).toHaveLength(0);
 await page.evaluate(async()=>{const app=(document.querySelector('#app') as any).__vue_app__;await app.config.globalProperties.$router.push('/settings');});
 await expect(page.getByRole('dialog',{name:'版本历史'})).toHaveCount(0);
});

test('successful quick capture still opens when list refresh fails',async({page})=>{
 const m=await mock(page);await page.goto('/notes');
 await expect(page.locator('.preview h1')).toBeVisible();
 await page.route('**/documents/**',async route=>{if(new URL(route.request().url()).pathname==='/documents/'&&route.request().method()==='GET')return route.fulfill({status:500,json:{detail:'mock list failure'}});return route.fallback();});
 await page.getByRole('button',{name:'快捷记录',exact:true}).click();
 await page.getByLabel('记录标题',{exact:true}).fill('已保存的记录');await page.getByLabel('记录正文',{exact:true}).fill('# 已保存但列表失败');
 await page.getByRole('button',{name:'保存并打开',exact:true}).click();
 await expect(page.locator('.preview h1')).toHaveText('已保存但列表失败');
 expect(m.calls.filter(c=>c.path==='/notes-tools/quick-record')).toHaveLength(1);
});
