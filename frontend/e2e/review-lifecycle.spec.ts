import {test,expect,type Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../tests/fixtures/clientPreferences';
import {scopeFixture} from './notes-delete-scope-fixture';
import {createNotesStartupFixture} from '../tests/fixtures/notesStartup.mjs';
const ROOT='http://127.0.0.1:15316',ws='11111111-1111-4111-8111-111111111111',id='22222222-2222-4222-8222-222222222222';
const out=process.env.NOTES_ARTIFACTS!;
async function fixture(page:Page,children=false,draftMode=false){
 const clientPreferences=createClientPreferencesFixture({storage:{stella_list_fold:'1',stella_note_edit_mode:'markdown'},allowWrite:true});
 const doc={id,title:'知识库 · 删除习惯',workspace_id:ws,parent_id:null as string|null,content:'# 知识库\n\n记录可以整理，删除也应该由自己选择。',updated_at:'2026-10-15T00:00:00Z',created_at:'2026-10-14T00:00:00Z',has_draft:draftMode,is_favorite:false,status:'published',file_path:'/fixture.md',content_hash:'fixture',is_folder:false,is_pinned:false,draft_updated_at:draftMode?'2026-10-16T12:00:00':null,draft_device:null};
 const state={docs:[doc,...(children?[{...doc,id:'33333333-3333-4333-8333-333333333333',title:'子页面',parent_id:id}]:[])],trash:[] as typeof doc[],prefs:{revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[] as string[]},conflict:false,conflictCode:'attachment_reference_conflict',failSave:false,holdSave:false,finishSave:null as null|(()=>void),failPreview:false,holdPreview:false,finishPreview:null as null|(()=>void),failRead:false,afterCommit500:false,noCommit500:false,failPrefGet:0,failPrefPatch:false,holdPrefGet:false,finishPrefGet:null as null|(()=>void),holdDelete:false,finishDelete:null as null|(()=>void)};
 const scopes=scopeFixture(()=>state.docs,()=>state.trash);
 const calls:{path:string;method:string;body:any}[]=[],errors:string[]=[],nativeDialogs:string[]=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',async d=>{nativeDialogs.push(d.type());await d.dismiss();});
 await page.routeWebSocket('**/*',()=>{});
 await page.route('**/*',async r=>{
  const q=r.request(),u=new URL(q.url()),p=u.pathname,method=q.method();
  if(u.origin===ROOT&&(p==='/notes'||p==='/settings'||p==='/'||p.startsWith('/static/')||p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||/\.(svg|woff2|png)$/.test(p)))return r.continue();
  if(['ipinfo.io','api.ip.sb'].includes(u.hostname))return r.fulfill({json:{ip:'192.0.2.1',region:'Fixture',country:'ZZ'}});
  if(u.origin!==ROOT){errors.push('Blocked external '+q.url());return r.abort();}
  calls.push({path:p+u.search,method,body:q.postData()});const ok=(json:any)=>r.fulfill({json});
  const preference=clientPreferences.respond(method,p+u.search,q.method()==='PUT'?q.postDataJSON():undefined);if(preference)return r.fulfill(preference);
  if(p!=='/notes-preferences'){const startup=createNotesStartupFixture(ws).respond(method,p+u.search);if(startup)return r.fulfill(startup);}
  if(p==='/auth/status')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'fixture-owner',username:'fixture',display_name:'测试账号',is_admin:true});
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/navigation')return ok({entries:[]});
  if(p==='/external-modules')return ok([]);
  if(p==='/workspaces/'||p===`/workspaces/${ws}`)return ok(p.endsWith('/')?[{id:ws,name:'笔记本',user_id:'fixture-owner'}]:{id:ws,name:'笔记本',user_id:'fixture-owner'});
  if(p==='/notes-preferences'){
   if(method==='GET'){if(state.holdPrefGet)await new Promise<void>(resolve=>state.finishPrefGet=resolve);if(state.failPrefGet-->0)return r.fulfill({status:503,json:{detail:'fixture unavailable'}});return ok(state.prefs);}
   const b=q.postDataJSON();if(state.failPrefPatch)return r.fulfill({status:503,json:{detail:'fixture write failure'}});
   if(b.expected_revision!==state.prefs.revision)return r.fulfill({status:409,json:{detail:{code:'revision_conflict'}}});
   state.prefs={...state.prefs,revision:state.prefs.revision+1,delete_action:b.delete_action??state.prefs.delete_action,ask_before_delete:b.ask_before_delete??state.prefs.ask_before_delete};return ok(state.prefs);
  }
  if(p==='/documents/delete-preview'&&method==='POST'){if(state.failPreview)return r.fulfill({status:503,json:{detail:'preview unavailable'}});const result=scopes.preview(q.postDataJSON());if(state.holdPreview){state.holdPreview=false;await new Promise<void>(resolve=>state.finishPreview=resolve);}return ok(result);}
  if(p==='/documents/'&&method==='GET'){if(state.failRead)return r.fulfill({status:503,json:{detail:'read unavailable'}});return ok(state.docs);}
  if(p==='/documents/trash')return ok(state.trash);
  if(p==='/documents/recent')return ok([]);
  if(p==='/documents/trash/empty'&&method==='POST'){if(!scopes.valid(u.searchParams.get('scope_token'),{workspace_id:ws,mode:'empty-trash',cascade:true}))return r.fulfill({status:409,json:{detail:{code:'delete_scope_changed'}}});if(state.conflict)return r.fulfill({status:409,json:{detail:{code:state.conflictCode}}});if(state.noCommit500)return r.fulfill({status:500,json:{detail:'unknown'}});const purged=state.trash.length;state.trash=[];if(state.afterCommit500)return r.fulfill({status:500,json:{detail:'ack lost'}});return ok({purged});}
  if(p==='/documents/'+id+'/draft')return ok({content:'adopted synthetic draft',updated_at:'2026-10-16T12:00:00',device:'fixture'});
  if(p.startsWith('/documents/')&&method==='PUT'){if(state.holdSave)await new Promise<void>(resolve=>state.finishSave=resolve);if(state.failSave)return r.fulfill({status:503,json:{detail:'save failed'}});const savedId=p.split('/')[2];const found=state.docs.find(d=>d.id===savedId);if(!found)return r.fulfill({status:404,json:{detail:'deleted'}});Object.assign(found,q.postDataJSON());return ok(found); }
  const match=p.match(/^\/documents\/([^/]+)(\/permanent)?$/);
  if(match){const target=match[1];if(method==='DELETE'){
   if(state.holdDelete)await new Promise<void>(resolve=>state.finishDelete=resolve);
   if(state.conflict)return r.fulfill({status:409,json:{detail:{code:state.conflictCode}}});
   if(!scopes.valid(u.searchParams.get('scope_token'),{workspace_id:ws,doc_id:target,mode:match[2]?'permanent':'trash',cascade:u.searchParams.get('cascade')==='true'}))return r.fulfill({status:409,json:{detail:{code:'delete_scope_changed'}}});
   if(state.noCommit500)return r.fulfill({status:500,json:{detail:'unknown'}});
   const collection=[...state.docs,...state.trash],found=collection.find(d=>d.id===target);
   const ids=new Set([target]);if(u.searchParams.get('cascade')==='true'){let changed=true;while(changed){changed=false;for(const d of collection)if(d.parent_id&&ids.has(d.parent_id)&&!ids.has(d.id)){ids.add(d.id);changed=true;}}}else for(const d of collection)if(d.parent_id===target)d.parent_id=found?.parent_id??null;
   if(match[2]){state.docs=state.docs.filter(d=>!ids.has(d.id));state.trash=state.trash.filter(d=>!ids.has(d.id));}
   else{state.trash.push(...state.docs.filter(d=>ids.has(d.id)));state.docs=state.docs.filter(d=>!ids.has(d.id));}
   if(state.afterCommit500)return r.fulfill({status:500,json:{detail:'ack lost'}});
   return r.fulfill({status:204});
  }const found=state.docs.find(d=>d.id===target);return found?ok(found):r.fulfill({status:404,json:{detail:'not found'}});}
  if(p==='/document-versions/')return ok([]);
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p.startsWith('/config/'))return ok({value:''});
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
async function deleteEditor(page:Page){await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'删除',exact:true}).click();}

test('review adopt draft sends exact consumption receipt',async({page})=>{
 const f=await fixture(page,false,true);
 await page.getByRole('button',{name:'采用并保存',exact:true}).click();
 await expect.poll(()=>f.calls.filter(c=>c.method==='PUT').length).toBe(1);
 const payload=JSON.parse(f.calls.find(c=>c.method==='PUT')!.body);
 console.log('ADOPT_PAYLOAD_KEYS',Object.keys(payload));
 expect(payload.content).toBe('adopted synthetic draft');
 expect(payload.consumed_draft,'explicitly adopted draft must include its timestamp and hash').toMatchObject({draft_updated_at:'2026-10-16T12:00:00'});
});

test('review trash preserves unsaved local edit before unmount',async({page})=>{
 const f=await fixture(page);
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 const editor=page.locator('.cm-content[contenteditable=true]');
 await editor.click();await page.keyboard.press('Control+End');await page.keyboard.insertText(' LOCAL_REVIEW_UNSAVED');
 await deleteEditor(page);
 await page.getByRole('button',{name:'确认移入回收站',exact:true}).click();
 await expect(page.locator('.blank')).toBeVisible();
 console.log('DELETE_WRITE_SEQUENCE',f.calls.filter(c=>['PUT','DELETE'].includes(c.method)).map(c=>c.method+' '+c.path));
 expect(f.state.trash).toHaveLength(1);
 expect(f.state.trash[0]!.content,'trash must be recoverable with the current edit, not only the last old body').toContain('LOCAL_REVIEW_UNSAVED');
});

async function editLocal(page:Page,text=' LOCAL_BARRIER'){
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 await page.locator('.cm-content[contenteditable=true]').click();await page.keyboard.press('Control+End');await page.keyboard.insertText(text);
}
async function openEmpty(page:Page){
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.locator('.trash-entry').filter({hasText:'回收站'}).click();
 await expect(page.locator('.trash-panel')).toBeVisible();await page.getByRole('button',{name:'清空回收站',exact:true}).click();
}
test('save failure blocks soft deletion and keeps the editable text',async({page})=>{
 const f=await fixture(page);await editLocal(page);f.state.failSave=true;await deleteEditor(page);await page.getByRole('button',{name:'确认移入回收站',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('已阻止删除');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);expect(f.state.docs[0]!.content).not.toContain('LOCAL_BARRIER');
 await page.screenshot({path:out+'/notes-recovery-save-blocked.png'});await page.getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('.cm-content')).toContainText('LOCAL_BARRIER');expect(f.errors).toEqual([]);
});
test('held save is a barrier before DELETE and remains single flight',async({page})=>{
 const f=await fixture(page);await editLocal(page);f.state.holdSave=true;await deleteEditor(page);await page.getByRole('button',{name:'确认移入回收站',exact:true}).click();
 await expect.poll(()=>!!f.state.finishSave).toBe(true);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);await expect(page.getByRole('dialog').getByRole('button',{name:'处理中…'})).toBeDisabled();
 f.state.finishSave!();await expect(page.locator('.blank')).toBeVisible();expect(f.state.trash[0]!.content).toContain('LOCAL_BARRIER');expect(f.calls.filter(c=>['PUT','DELETE'].includes(c.method)).map(c=>c.method)).toEqual(['PUT','DELETE']);expect(f.errors).toEqual([]);
});
test('ancestor cascade saves the current child before deleting the frozen subtree',async({page})=>{
 const f=await fixture(page,true),child=f.state.docs[1]!.id;
 await page.evaluate(id=>{(document.querySelector('#app') as any).__vue_app__.config.globalProperties.$router.push('/notes?doc='+id);},child);
 await expect(page.locator('.title-readonly')).toContainText('子页面');await editLocal(page,' CHILD_LOCAL');
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();const row=page.locator('.doc-list .node .row').filter({hasText:'知识库 · 删除习惯'}).first();await row.hover();await row.getByTitle('删除',{exact:true}).click();
 await page.getByRole('radio',{name:/一起删除/}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.locator('.blank')).toBeVisible();
 expect(f.state.trash.find(d=>d.id===child)!.content).toContain('CHILD_LOCAL');expect(f.calls.filter(c=>['PUT','DELETE'].includes(c.method)).map(c=>c.method)).toEqual(['PUT','DELETE']);expect(f.errors).toEqual([]);
});
test('committed empty 500 reconciles only frozen ids and preserves new trash',async({page})=>{
 const f=await fixture(page);const original=f.state.docs[0]!;f.state.trash=[original];f.state.docs=[];await openEmpty(page);f.state.afterCommit500=true;
 await page.getByRole('button',{name:'确认永久清空'}).click();await expect(page.getByRole('dialog')).toContainText('结果尚未确认');expect(f.state.trash).toHaveLength(0);
 f.state.trash.push({...original,id:'44444444-4444-4444-8444-444444444444',title:'新回收站笔记'});
 await page.screenshot({path:out+'/notes-recovery-uncertain.png'});await page.getByRole('button',{name:'刷新列表核对'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 expect(f.state.trash).toHaveLength(1);expect(f.calls.filter(c=>c.path.includes('/trash/empty'))).toHaveLength(1);expect(f.calls.find(c=>c.path.includes('/trash/empty'))!.path).toContain('scope_token=');expect(f.errors).toEqual([]);
});
test('uncommitted 500 retains choice and checkbox through failed reads and explicit reconfirm',async({page})=>{
 const f=await fixture(page);f.state.noCommit500=true;await deleteEditor(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toContainText('结果尚未确认');
 f.state.failRead=true;await page.getByRole('button',{name:'刷新列表核对'}).click();await expect(page.getByRole('alert')).toContainText('列表仍未读取成功');
 f.state.failRead=false;await page.getByRole('button',{name:'刷新列表核对'}).click();await expect(page.getByRole('alert')).toContainText('目标尚未达到');await expect(page.getByRole('checkbox',{name:'下次不再询问'})).toBeChecked();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(0);
 await page.getByRole('button',{name:'重新读取范围'}).click();await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);
 f.state.noCommit500=false;await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(2);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(1);expect(f.errors).toEqual([]);
});
test('committed soft-delete 500 remembers once and preference retry never deletes again',async({page})=>{
 const f=await fixture(page);f.state.afterCommit500=true;f.state.failPrefPatch=true;await deleteEditor(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toContainText('结果尚未确认');
 await page.getByRole('button',{name:'刷新列表核对'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.locator('.blank')).toBeVisible();expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(1);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);
 await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.getByRole('button',{name:'笔记设置',exact:true}).click();await expect(page.getByRole('button',{name:'重新应用我的选择'})).toBeEnabled();f.state.failPrefPatch=false;await page.getByRole('button',{name:'重新应用我的选择'}).click();await expect(page.locator('.notes-settings')).toContainText('已同步');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);expect(f.state.prefs.ask_before_delete).toBe(false);expect(f.errors).toEqual([]);
});
test('verified deletion closes while preference GET is held and the next leaf uses remembered permanent without another prompt',async({page})=>{
 const f=await fixture(page,true);await deleteEditor(page);const modal=page.getByRole('dialog');
 await modal.getByRole('radio',{name:/永久删除/}).check();await modal.getByRole('radio',{name:/仅删此篇/}).check();await modal.getByRole('checkbox',{name:'下次不再询问'}).check();f.state.holdPrefGet=true;
 await modal.getByRole('button',{name:'确认永久删除'}).click();await expect.poll(()=>!!f.state.finishPrefGet).toBe(true);
 await expect(modal).toHaveCount(0);await expect(page.locator('.title-readonly')).toContainText('子页面');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);
 await page.screenshot({path:out+'/delete-complete-while-preference-held.png'});
 await deleteEditor(page);await expect(modal).toHaveCount(0);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);
 f.state.holdPrefGet=false;f.state.finishPrefGet!();await expect(page.locator('.blank')).toBeVisible();await expect(modal).toHaveCount(0);
 expect(f.calls.filter(c=>c.method==='DELETE'&&c.path.includes('/permanent'))).toHaveLength(2);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(1);expect(f.nativeDialogs).toEqual([]);expect(f.errors).toEqual([]);
});
test('cold trash child prevents remembered permanent leaf shortcut',async({page})=>{
 const f=await fixture(page,true);f.state.trash=[f.state.docs.pop()!];f.state.prefs={...f.state.prefs,revision:2,delete_action:'permanent',ask_before_delete:false};await deleteEditor(page);
 await expect(page.getByRole('dialog')).toContainText('1 篇子页面');await expect(page.getByRole('button',{name:'确认永久删除'})).toBeDisabled();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);expect(f.calls.filter(c=>c.path.startsWith('/documents/trash?'))).toHaveLength(0);
 await page.getByRole('radio',{name:/仅删此篇/}).check();await page.getByRole('button',{name:'确认永久删除'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.state.trash).toHaveLength(1);expect(f.state.trash[0]!.parent_id).toBeNull();expect(f.errors).toEqual([]);
});
test('scope drift rejects frozen empty without deleting added trash and requires new confirmation',async({page})=>{
 const f=await fixture(page);const original=f.state.docs[0]!;f.state.trash=[original];f.state.docs=[];await openEmpty(page);await expect(page.getByRole('button',{name:'确认永久清空'})).toBeEnabled();
 f.state.trash.push({...original,id:'44444444-4444-4444-8444-444444444444'});await page.getByRole('button',{name:'确认永久清空'}).click();await expect(page.getByRole('alert')).toContainText('范围已变化');expect(f.state.trash).toHaveLength(2);
 await page.getByRole('button',{name:'重新读取范围'}).click();await expect(page.getByRole('dialog')).toContainText('2 篇');expect(f.calls.filter(c=>c.path.includes('/trash/empty'))).toHaveLength(1);await page.getByRole('button',{name:'确认永久清空'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.state.trash).toHaveLength(0);expect(f.errors).toEqual([]);
});
test('late mode preview cannot change selection or authorize a stale token',async({page})=>{
 const f=await fixture(page);await deleteEditor(page);await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();f.state.holdPreview=true;
 await page.getByRole('radio',{name:/永久删除/}).check();await expect.poll(()=>!!f.state.finishPreview).toBe(true);await page.getByRole('radio',{name:/移入回收站/}).check();await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();f.state.finishPreview!();
 await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.state.trash).toHaveLength(1);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);expect(f.errors).toEqual([]);
});
test('failed preview blocks remembered shortcut and successful retry still asks',async({page})=>{
 const f=await fixture(page);f.state.failPreview=true;f.state.prefs={...f.state.prefs,revision:2,delete_action:'permanent',ask_before_delete:false};await deleteEditor(page);await expect(page.getByRole('alert')).toContainText('范围读取失败');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);
 f.state.failPreview=false;await page.getByRole('button',{name:'重新读取范围'}).click();await expect(page.getByRole('button',{name:'确认永久删除'})).toBeEnabled();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);expect(f.errors).toEqual([]);
});
for(const [code,text] of [['attachment_in_use','引用'],['attachment_reference_check_incomplete','引用检查未完成'],['document_has_children','子页'],['document_tree_invalid','树结构异常'],['document_tree_check_incomplete','树检查未完成']])test('browser recovery for '+code,async({page})=>{
 const f=await fixture(page);await deleteEditor(page);f.state.conflict=true;f.state.conflictCode=code!;await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('alert')).toContainText(text!);await expect(page.getByRole('button',{name:'重新读取范围'})).toBeEnabled();expect(f.state.docs).toHaveLength(1);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(0);expect(f.errors).toEqual([]);
});
test('production singleton request epoch fences a held DELETE and preference write',async({page})=>{
 const f=await fixture(page);f.state.holdDelete=true;await deleteEditor(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect.poll(()=>!!f.state.finishDelete).toBe(true);
 // Inspect the actual built module exports, not a replacement auth mock/test bundle.
 const epoch=await page.evaluate(async()=>{const url=performance.getEntriesByType('resource').map(entry=>entry.name).find(url=>/\/static\/auth-[^/]+\.js$/.test(url));if(!url)throw new Error('Built auth chunk not loaded');const exports=await import(url);const auth=Object.values(exports).find((v:any)=>v&&typeof v==='object'&&'requestEpoch' in v&&'sessionGeneration' in v) as any;if(!auth)throw new Error('Built auth singleton not exported');const previous=auth.requestEpoch;auth.requestEpoch++;return [previous,auth.requestEpoch];});
 expect(epoch[1]).toBe(epoch[0]+1);await expect(page.getByRole('dialog')).toHaveCount(0);const reads=f.calls.filter(c=>c.path.startsWith('/documents/?')).length;f.state.finishDelete!();await expect.poll(()=>f.state.docs.length).toBe(0);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(0);expect(f.calls.filter(c=>c.path.startsWith('/documents/?'))).toHaveLength(reads);expect(f.errors).toEqual([]);
});
test('held initial preview cannot reopen after a retained Notes route change',async({page})=>{
 const f=await fixture(page);f.state.holdPreview=true;await deleteEditor(page);await expect.poll(()=>!!f.state.finishPreview).toBe(true);
 await page.evaluate(()=>{(document.querySelector('#app') as any).__vue_app__.config.globalProperties.$router.push('/settings?section=notes');});await expect(page.locator('.notes-settings')).toBeVisible();f.state.finishPreview!();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.calls.filter(c=>c.method==='DELETE'||c.method==='PATCH')).toHaveLength(0);expect(f.errors).toEqual([]);
});
