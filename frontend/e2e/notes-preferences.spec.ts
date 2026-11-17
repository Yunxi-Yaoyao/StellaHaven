import {test,expect,type Page} from '@playwright/test';
import {scopeFixture} from './notes-delete-scope-fixture';
const ROOT='http://127.0.0.1:15316',ws='11111111-1111-4111-8111-111111111111',id='22222222-2222-4222-8222-222222222222';
const out=process.env.NOTES_ARTIFACTS!;
async function fixture(page:Page,children=false){
 const doc={id,title:'知识库 · 删除习惯',workspace_id:ws,parent_id:null as string|null,content:'# 知识库\n\n记录可以整理，删除也应该由自己选择。',updated_at:'2026-10-15T00:00:00Z',created_at:'2026-10-14T00:00:00Z',has_draft:false,is_favorite:false,status:'published',file_path:'/fixture.md',content_hash:'fixture',is_folder:false,is_pinned:false,draft_updated_at:null,draft_device:null};
 const state={docs:[doc,...(children?[{...doc,id:'33333333-3333-4333-8333-333333333333',title:'子页面',parent_id:id}]:[])],trash:[] as typeof doc[],prefs:{revision:0,delete_action:'trash',ask_before_delete:true},conflict:false,failPrefGet:0,failPrefPatch:false,holdDelete:false,finishDelete:null as null|(()=>void)};
 const scopes=scopeFixture(()=>state.docs,()=>state.trash);
 const calls:{path:string;method:string;body:any}[]=[],errors:string[]=[],nativeDialogs:string[]=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',async d=>{nativeDialogs.push(d.type());await d.dismiss();});
 await page.routeWebSocket('**/*',()=>{});
 await page.route('**/*',async r=>{
  const q=r.request(),u=new URL(q.url()),p=u.pathname,method=q.method();
  if(u.origin===ROOT&&(p==='/notes'||p==='/settings'||p==='/'||p.startsWith('/static/')||p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||/\.(svg|woff2|png)$/.test(p)))return r.continue();
  if(method==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.href))return r.fulfill({json:{ip:'192.0.2.1',region:'Fixture',country:'ZZ'}});
  if(u.origin!==ROOT){errors.push('Blocked external '+q.url());return r.abort();}
  calls.push({path:p+u.search,method,body:q.postData()});const ok=(json:any)=>r.fulfill({json});
  if(p==='/auth/status')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'fixture-owner',username:'fixture',display_name:'测试账号',is_admin:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/navigation')return ok({entries:[]});
  if(p==='/external-modules')return ok([]);
  if(p==='/workspaces/'||p===`/workspaces/${ws}`)return ok(p.endsWith('/')?[{id:ws,name:'笔记本',user_id:'fixture-owner'}]:{id:ws,name:'笔记本',user_id:'fixture-owner'});
  if(p==='/notes-preferences'){
   if(method==='GET'){if(state.failPrefGet-->0)return r.fulfill({status:503,json:{detail:'fixture unavailable'}});return ok(state.prefs);}
   const b=q.postDataJSON();if(state.failPrefPatch)return r.fulfill({status:503,json:{detail:'fixture write failure'}});
   if(b.expected_revision!==state.prefs.revision)return r.fulfill({status:409,json:{detail:{code:'revision_conflict'}}});
   state.prefs={revision:state.prefs.revision+1,delete_action:b.delete_action??state.prefs.delete_action,ask_before_delete:b.ask_before_delete??state.prefs.ask_before_delete};return ok(state.prefs);
  }
  if(p==='/documents/delete-preview'&&method==='POST')return ok(scopes.preview(q.postDataJSON()));
  if(p==='/documents/'&&method==='GET')return ok(state.docs);
  if(p==='/documents/trash')return ok(state.trash);
  if(p==='/documents/recent')return ok([]);
  if(p==='/documents/trash/empty'&&method==='POST'){if(!scopes.valid(u.searchParams.get('scope_token'),{workspace_id:ws,mode:'empty-trash',cascade:true}))return r.fulfill({status:409,json:{detail:{code:'delete_scope_changed'}}});if(state.conflict)return r.fulfill({status:409,json:{detail:{code:'attachment_reference_conflict'}}});const purged=state.trash.length;state.trash=[];return ok({purged});}
  const match=p.match(/^\/documents\/([^/]+)(\/permanent)?$/);
  if(match){const target=match[1];if(method==='DELETE'){
   if(state.holdDelete)await new Promise<void>(resolve=>state.finishDelete=resolve);
   if(state.conflict)return r.fulfill({status:409,json:{detail:{code:'attachment_reference_conflict'}}});
   if(!scopes.valid(u.searchParams.get('scope_token'),{workspace_id:ws,doc_id:target,mode:match[2]?'permanent':'trash',cascade:u.searchParams.get('cascade')==='true'}))return r.fulfill({status:409,json:{detail:{code:'delete_scope_changed'}}});
   const collection=[...state.docs,...state.trash],found=collection.find(d=>d.id===target);
   const ids=new Set([target]);if(u.searchParams.get('cascade')==='true'){let changed=true;while(changed){changed=false;for(const d of collection)if(d.parent_id&&ids.has(d.parent_id)&&!ids.has(d.id)){ids.add(d.id);changed=true;}}}else for(const d of collection)if(d.parent_id===target)d.parent_id=found?.parent_id??null;
   if(match[2]){state.docs=state.docs.filter(d=>!ids.has(d.id));state.trash=state.trash.filter(d=>!ids.has(d.id));}
   else{state.trash.push(...state.docs.filter(d=>ids.has(d.id)));state.docs=state.docs.filter(d=>!ids.has(d.id));}
   return r.fulfill({status:204});
  }const found=state.docs.find(d=>d.id===target);return found?ok(found):r.fulfill({status:404,json:{detail:'not found'}});}
  if(p==='/document-versions/')return ok([]);
  if(p==='/notifications/unread-count')return ok({count:0});
  if(['/config/public-host','/config/site-background','/config/home'].includes(p))return ok({value:''});
  if(p==='/auth/activity')return ok({ok:true});
  if(p==='/auth/email-service')return ok({ready:false});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(['/tags/','/doc-tags/','/attachments/','/document-links/','/documents/recent','/auth/sessions','/auth/avatars','/homebg/'].includes(p)||p.endsWith('/backlinks'))return ok([]);
  errors.push('Unexpected fixture request '+method+' '+p);return r.fulfill({status:501,json:{detail:'unhandled fixture'}});
 });
 await page.addInitScript(({ws})=>{localStorage.clear();localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'fixture-owner',workspaceId:ws}));localStorage.setItem('stella_list_fold','1');localStorage.setItem('stella_note_edit_mode','markdown');},{ws});
 await page.goto('/notes');await expect(page.locator('.preview h1')).toBeVisible();
 return {state,calls,errors,nativeDialogs};
}
async function deleteEditor(page:Page){await page.getByRole('button',{name:'更多',exact:true}).click();await page.locator('.note-more-menu').getByRole('button',{name:'删除',exact:true}).click();}
for(const width of [1440,393,320])test(`actual notes modal and independent settings ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});const f=await fixture(page,true);await deleteEditor(page);
 const dialog=page.getByRole('dialog',{name:'删除「知识库 · 删除习惯」'});await expect(dialog).toBeVisible();
 await expect(dialog.getByRole('button',{name:'确认移入回收站'})).toBeDisabled();await dialog.getByRole('radio',{name:/永久删除/}).check();await dialog.getByRole('radio',{name:/仅删此篇/}).check();await dialog.getByRole('checkbox',{name:'下次不再询问'}).check();
 await page.screenshot({path:`${out}/notes-ui-delete-${width}.png`,fullPage:true});
 expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true);
 for(let n=0;n<10;n++){await page.keyboard.press('Tab');expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);}
 await dialog.getByRole('button',{name:'取消'}).click();await expect(dialog).toHaveCount(0);expect(f.calls.filter(c=>c.method==='DELETE'||c.method==='PATCH')).toHaveLength(0);
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.getByRole('link',{name:'笔记设置',exact:true}).click();await expect(page).toHaveURL(/section=notes/);await expect(page.locator('.notes-settings')).toBeVisible();
 await page.locator('.notes-settings input[value=permanent]').check();await expect(page.locator('.notes-settings')).toContainText('已同步');await page.getByRole('checkbox',{name:'删除前询问'}).uncheck();await expect(page.locator('.notes-settings')).toContainText('已同步');expect(f.state.prefs.delete_action).toBe('permanent');expect(f.state.prefs.ask_before_delete).toBe(false);
 await page.screenshot({path:`${out}/notes-ui-settings-${width}.png`,fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('checkbox',{name:'删除前询问'}).check();await expect(page.locator('.notes-settings')).toContainText('已同步');expect(f.state.prefs.ask_before_delete).toBe(true);expect(f.nativeDialogs).toEqual([]);expect(f.errors).toEqual([]);
});
test('editor soft delete, trash permanent conflict and empty all use clear scopes without admin UI',async({page})=>{
 const f=await fixture(page);await deleteEditor(page);await page.getByRole('button',{name:'确认移入回收站',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.state.trash).toHaveLength(1);expect(f.state.docs).toHaveLength(0);
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.locator('.trash-entry').filter({hasText:'回收站'}).click();await expect(page.locator('.trash-panel')).toBeVisible();await page.getByRole('button',{name:'永久删除',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('此笔记已在回收站');f.state.conflict=true;await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await expect(page.getByRole('alert')).toContainText('引用');expect(f.state.trash).toHaveLength(1);await page.screenshot({path:out+'/notes-ui-reference-conflict.png'});await page.getByRole('button',{name:'取消',exact:true}).click();
 f.state.conflict=false;await page.getByRole('button',{name:'清空回收站',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('1 篇');await page.getByRole('button',{name:'确认永久清空',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.state.trash).toHaveLength(0);expect(f.calls.filter(c=>c.path.startsWith('/auth/admin/'))).toHaveLength(0);expect(f.nativeDialogs).toEqual([]);expect(f.errors).toEqual([]);
});
test('remember permanent, skip next leaf modal, then reverse in settings',async({page})=>{
 const f=await fixture(page,true);await deleteEditor(page);const modal=page.getByRole('dialog');await modal.getByRole('radio',{name:/永久删除/}).check();await modal.getByRole('radio',{name:/仅删此篇/}).check();await modal.getByRole('checkbox',{name:'下次不再询问'}).check();await modal.getByRole('button',{name:'确认永久删除'}).click();await expect(modal).toHaveCount(0);expect(f.state.prefs).toMatchObject({delete_action:'permanent',ask_before_delete:false});await expect(page.locator('.title-readonly')).toContainText('子页面');await deleteEditor(page);await expect(page.locator('.blank')).toBeVisible();await expect(modal).toHaveCount(0);expect(f.calls.filter(c=>c.path.includes('/permanent')&&c.method==='DELETE')).toHaveLength(2);expect(f.nativeDialogs).toEqual([]);expect(f.errors).toEqual([]);
});
test('tree entry uses unified choice and Escape returns focus without changing preference',async({page})=>{
 const f=await fixture(page,true);await page.getByRole('button',{name:'笔记目录',exact:true}).click();const row=page.locator('.doc-list .node .row').first();await row.hover();const trigger=row.getByTitle('删除',{exact:true});await trigger.click();await expect(page.getByRole('dialog')).toContainText('子页面');await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);await expect(trigger).toBeFocused();expect(f.calls.filter(c=>c.method==='DELETE'||c.method==='PATCH')).toHaveLength(0);expect(f.nativeDialogs).toEqual([]);expect(f.errors).toEqual([]);
});
test('failed remember is recoverable without replaying successful deletion',async({page})=>{
 const f=await fixture(page);await deleteEditor(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();f.state.failPrefPatch=true;await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('button',{name:'重新读取偏好'})).toBeEnabled();expect(f.state.docs).toHaveLength(0);await page.getByRole('button',{name:'重新读取偏好'}).click();await expect(page.getByRole('alert')).toContainText('已保留');f.state.failPrefPatch=false;await page.getByRole('button',{name:'重新应用偏好'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);expect(f.state.prefs.ask_before_delete).toBe(false);expect(f.errors).toEqual([]);
});
test('settings revision conflict preserves choice and supports explicit reapply',async({page})=>{
 const f=await fixture(page);await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.getByRole('link',{name:'笔记设置'}).click();await expect(page.locator('.notes-settings')).toContainText('已同步');f.state.prefs.revision++;
 await page.locator('.notes-settings input[value=permanent]').check();await expect(page.getByRole('alert')).toContainText('已保留');await expect(page.locator('.notes-settings input[value=permanent]')).toBeChecked();await page.getByRole('button',{name:'重新应用我的选择'}).click();await expect(page.locator('.notes-settings')).toContainText('已同步');expect(f.state.prefs.delete_action).toBe('permanent');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);expect(f.errors).toEqual([]);
});
test('KeepAlive route change closes the dialog and held result cannot write preference',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.getByRole('link',{name:'笔记设置',exact:true}).click();await expect(page.locator('.notes-settings')).toBeVisible();await page.locator('a[href="/notes"]').first().click();
 await deleteEditor(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();f.state.holdDelete=true;await page.getByRole('button',{name:'确认移入回收站'}).click();await expect.poll(()=>!!f.state.finishDelete).toBe(true);
 // Browser Back is public navigation and deactivates Notes while the dialog
 // still owns focus and the deletion response is held. No private Vue fields.
 await page.goBack();
 await expect(page.locator('.notes-settings')).toBeVisible();await expect(page.getByRole('dialog')).toHaveCount(0);f.state.finishDelete!();await expect.poll(()=>f.state.docs.length).toBe(0);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(0);expect(f.nativeDialogs).toEqual([]);expect(f.errors).toEqual([]);
});
