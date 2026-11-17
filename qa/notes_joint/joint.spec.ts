import {test,expect,request,type Page} from '@playwright/test';
import fs from 'node:fs';import {execFileSync,spawn} from 'node:child_process';
const auth=JSON.parse(fs.readFileSync('/root/.hermes/cache/scratch/notes-joint-6b01e8e/auth-private.json','utf8'));
const URL=auth.url,OUT='/opt/hermes-workstation/docs/Stella-API/remediation/review-notes-joint-browser';
fs.mkdirSync(OUT,{recursive:true});
function bridge(op:string,id:string,content?:string){return JSON.parse(execFileSync('/opt/Yunxi-workstation/Stella/.venv/bin/python',['/opt/hermes-workstation/stella-notes-final-joint-20261016/qa/notes_joint/db_bridge.py'],{input:JSON.stringify({op,id,content}),encoding:'utf8'}));}
async function setup(page:Page){
 const admin=await request.newContext({baseURL:URL,extraHTTPHeaders:{Origin:URL,Cookie:Object.entries(auth.elevated).map(([k,v])=>`${k}=${v}`).join('; ')}});
 const api=await request.newContext({baseURL:URL,extraHTTPHeaders:{Origin:URL,Cookie:Object.entries(auth.ordinary).map(([k,v])=>`${k}=${v}`).join('; ')}});
 const wr=await admin.post('/workspaces/',{data:{name:'browser-'+Date.now(),user_id:auth.uid}});expect(wr.status()).toBe(201);const w=(await wr.json()).id;
 for(const d of await (await api.get('/documents/',{params:{workspace_id:w}})).json())expect((await api.delete(`/documents/${d.id}/permanent`)).status()).toBe(204);
 const pref=await(await api.get('/notes-preferences')).json();expect((await api.patch('/notes-preferences',{data:{expected_revision:pref.revision,delete_action:'trash',ask_before_delete:true}})).status()).toBe(200);
 async function create(title='Joint browser note',parent_id:string|null=null){const r=await api.post('/documents/',{data:{workspace_id:w,parent_id,title,file_path:'/joint/'+Date.now()+Math.random(),content:'# Joint browser\n\nOriginal body'}});expect(r.status()).toBe(201);return r.json();}
 const doc=await create();
 await page.context().addCookies(Object.entries(auth.ordinary).map(([name,value])=>({name,value:String(value),url:URL,httpOnly:true,sameSite:'Lax' as const})));
 const calls:any[]=[],errors:string[]=[],previews:any[]=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{const u=new globalThis.URL(r.url());if(u.origin===URL&&['PUT','DELETE','POST','PATCH'].includes(r.method()))calls.push({path:u.pathname,query:u.search,method:r.method(),body:r.postData()});});
 page.on('response',async r=>{if(r.url().endsWith('/documents/delete-preview')&&r.status()===200)try{previews.push(await r.json());}catch{}});
 await page.route('**/*',r=>new globalThis.URL(r.request().url()).origin===URL?r.continue():r.abort('blockedbyclient'));
 await page.addInitScript(({uid,w})=>{localStorage.clear();localStorage.setItem('stella_bootstrap',JSON.stringify({userId:uid,workspaceId:w}));localStorage.setItem('stella_list_fold','1');localStorage.setItem('stella_note_edit_mode','markdown');},{uid:auth.uid,w});
 async function visit(id=doc.id){await page.goto(URL+'/notes?doc='+id);await expect(page.locator('.title-readonly')).toBeVisible();}
 async function done(name:string){await page.screenshot({path:OUT+'/'+name+'.png',fullPage:true});fs.writeFileSync(OUT+'/'+name+'.json',JSON.stringify({calls,previews,errors},null,2));expect(errors).toEqual([]);await admin.dispose();await api.dispose();}
 return {api,admin,w,doc,create,calls,previews,errors,visit,done};
}
async function del(page:Page){await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'删除',exact:true}).click();}
async function edit(page:Page,txt:string){await page.getByRole('button',{name:'编辑',exact:true}).click();await page.locator('.cm-content[contenteditable=true]').click();await page.keyboard.press('Control+End');await page.keyboard.insertText(txt);}
async function empty(page:Page){await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.locator('.trash-entry').filter({hasText:'回收站'}).click();await expect(page.locator('.trash-panel')).toBeVisible();await page.getByRole('button',{name:'清空回收站',exact:true}).click();}

test('F2 current editor PUT precedes token DELETE and PG retains body',async({page})=>{
 const f=await setup(page);await f.visit();await edit(page,' CURRENT_UNSAVED');await del(page);await page.getByRole('button',{name:'确认移入回收站',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 const writes=f.calls.filter(c=>['PUT','DELETE'].includes(c.method));expect(writes.map(c=>c.method)).toEqual(['PUT','DELETE']);expect(writes[1].query).toContain('scope_token=');expect(bridge('read',f.doc.id).content).toContain('CURRENT_UNSAVED');expect(bridge('read',f.doc.id).deleted_at).not.toBeNull();await f.done('current-save');
});

test('F2 ancestor cascade saves active child before deletion',async({page})=>{
 const f=await setup(page),child=await f.create('Joint child',f.doc.id);await f.visit(child.id);await edit(page,' CHILD_UNSAVED');await page.getByRole('button',{name:'笔记目录',exact:true}).click();const row=page.locator('.doc-list .node .row').filter({hasText:'Joint browser note'}).first();await row.hover();await row.getByTitle('删除',{exact:true}).click();await page.getByRole('radio',{name:/一起删除/}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.calls.filter(c=>['PUT','DELETE'].includes(c.method)).map(c=>c.method)).toEqual(['PUT','DELETE']);expect(bridge('read',child.id).content).toContain('CHILD_UNSAVED');expect(bridge('read',child.id).deleted_at).not.toBeNull();await f.done('ancestor-save');
});

test('F2 actual save request failure blocks DELETE without discarding text',async({page})=>{
 const f=await setup(page);await f.visit();await edit(page,' SAVE_BLOCKED');await page.route(URL+'/documents/'+f.doc.id,r=>r.request().method()==='PUT'?r.abort('failed'):r.fallback());await del(page);await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toContainText('已阻止删除');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);expect(bridge('read',f.doc.id).deleted_at).toBeNull();await page.getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('.cm-content')).toContainText('SAVE_BLOCKED');await f.done('save-blocked');
});

test('F3 cold trash child defeats remembered leaf shortcut; real permanent no elevation',async({page})=>{
 const f=await setup(page),child=await f.create('Cold trash child',f.doc.id);expect((await f.api.delete('/documents/'+child.id)).status()).toBe(204);const p=await(await f.api.get('/notes-preferences')).json();await f.api.patch('/notes-preferences',{data:{expected_revision:p.revision,delete_action:'permanent',ask_before_delete:false}});await f.visit();await del(page);await expect(page.getByRole('dialog')).toContainText('1 篇子页面');await expect(page.getByRole('button',{name:'确认永久删除'})).toBeDisabled();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);await page.getByRole('radio',{name:/仅删此篇/}).check();await page.getByRole('button',{name:'确认永久删除'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(bridge('read',f.doc.id)).toBeNull();expect(bridge('read',child.id).parent_id).toBeNull();expect((await(await f.api.get('/auth/security')).json()).elevated).toBe(false);await f.done('cold-child');
});

test('external deletion of current folded editor keeps Notes navigation accessible',async({page})=>{
 const f=await setup(page);await f.visit();await expect(page.locator('.preview h1')).toContainText('Joint browser');expect((await f.api.delete('/documents/'+f.doc.id)).status()).toBe(204);await expect.poll(async()=>await page.getByRole('button',{name:'笔记目录',exact:true}).isVisible()||await page.locator('.doc-list').isVisible()).toBe(true);await f.done('external-current-delete');
});

test('concurrent deletion during initial document GET keeps Notes navigation accessible',async({page})=>{
 const f=await setup(page);let release:any,held=false;const gate=new Promise<void>(r=>release=r);await page.route(URL+'/documents/'+f.doc.id,async r=>{if(r.request().method()==='GET'){held=true;await gate;}await r.fallback();});await page.goto(URL+'/notes?doc='+f.doc.id);await expect.poll(()=>held).toBe(true);expect((await f.api.delete('/documents/'+f.doc.id)).status()).toBe(204);release();await expect.poll(()=>page.locator('.loading').count()).toBe(0);await expect.poll(async()=>await page.getByRole('button',{name:'笔记目录',exact:true}).isVisible()||await page.locator('.doc-list').isVisible()).toBe(true);await f.done('delete-during-load');
});

test('F1 committed empty response lost; fresh trash must survive readback',async({page})=>{
 const f=await setup(page);const keeper=await f.create('Active page while clearing trash');await f.visit(keeper.id);expect((await f.api.delete('/documents/'+f.doc.id)).status()).toBe(204);await empty(page);
 await page.route(URL+'/documents/trash/empty?*',async r=>{const response=await r.fetch();expect(response.status()).toBe(200);expect(bridge('read',f.doc.id)).toBeNull();await r.abort('failed');});
 await page.getByRole('button',{name:'确认永久清空'}).click();await expect(page.getByRole('dialog')).toContainText('结果尚未确认');const arrival=await f.create('New arrival');await f.api.delete('/documents/'+arrival.id);await page.getByRole('button',{name:'刷新列表核对'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(bridge('read',arrival.id).deleted_at).not.toBeNull();expect(f.calls.filter(c=>c.path==='/documents/trash/empty')).toHaveLength(1);await f.done('empty-lost-ack');
});

test('F7 uncommitted transport loss readback retains choice and emits no completion',async({page})=>{
 const f=await setup(page);await f.visit();await page.route(URL+'/documents/'+f.doc.id+'?*',r=>r.request().method()==='DELETE'?r.abort('failed'):r.fallback());await del(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toContainText('结果尚未确认');await page.getByRole('button',{name:'刷新列表核对'}).click();await expect(page.getByRole('alert')).toContainText('目标尚未达到');await expect(page.getByRole('checkbox',{name:'下次不再询问'})).toBeChecked();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(0);expect(bridge('read',f.doc.id).deleted_at).toBeNull();await f.done('uncommitted-readback');
});

test('preference failure retries preference only after successful real delete',async({page})=>{
 const f=await setup(page);await f.visit();let fail=true;await page.route(URL+'/notes-preferences',r=>r.request().method()==='PATCH'&&fail?r.abort('failed'):r.fallback());await del(page);await page.getByRole('checkbox',{name:'下次不再询问'}).check();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('button',{name:'重新读取偏好'})).toBeEnabled();expect(bridge('read',f.doc.id).deleted_at).not.toBeNull();await page.getByRole('button',{name:'重新读取偏好'}).click();fail=false;await page.getByRole('button',{name:'重新应用偏好'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);expect(f.calls.filter(c=>c.method==='PATCH')).toHaveLength(2);expect((await(await f.api.get('/notes-preferences')).json()).ask_before_delete).toBe(false);await f.done('preference-only');
});

for(const newer of [false,true])test('F4 actual adoption receipt '+(newer?'preserves newer device slot':'consumes exact slot'),async({page})=>{
 const f=await setup(page);const stamp=bridge('draft',f.doc.id,'ADOPTED_JOINT').stamp;await f.visit();await expect(page.getByRole('button',{name:'采用并保存',exact:true})).toBeVisible();if(newer)await page.route(URL+'/documents/'+f.doc.id,async r=>{if(r.request().method()==='PUT')bridge('draft',f.doc.id,'NEWER_DEVICE_SLOT');await r.fallback();});await page.getByRole('button',{name:'采用并保存',exact:true}).click();await expect.poll(()=>f.calls.filter(c=>c.method==='PUT').length).toBe(1);await expect.poll(()=>bridge('read',f.doc.id).content).toBe('ADOPTED_JOINT');const payload=JSON.parse(f.calls.find(c=>c.method==='PUT').body);expect(payload.consumed_draft.draft_updated_at).toBe(stamp);expect(payload.consumed_draft.content_hash).toMatch(/^[a-f0-9]{64}$/);expect(bridge('read',f.doc.id).draft_content).toBe(newer?'NEWER_DEVICE_SLOT':null);await f.done('adopt-'+newer);
});

test('mode switch invalidates held real preview response',async({page})=>{
 const f=await setup(page);await f.visit();await del(page);await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();let release:any,held=false;
 await page.route(URL+'/documents/delete-preview',async r=>{if(r.request().postDataJSON().mode==='permanent'){const actual=await r.fetch();held=true;await new Promise(res=>release=res);await r.fulfill({response:actual});}else await r.fallback();});
 await page.getByRole('radio',{name:/永久删除/}).check();await expect.poll(()=>held).toBe(true);await page.getByRole('radio',{name:/移入回收站/}).check();await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();release();await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect(bridge('read',f.doc.id).deleted_at).not.toBeNull();expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);await f.done('late-preview');
});

test('F6 real attachment conflict preserves target and explains references',async({page})=>{
 const f=await setup(page),other=await f.create('Attachment referrer');const upload=await f.api.post('/attachments/'+f.doc.id,{multipart:{file:{name:'joint.txt',mimeType:'text/plain',buffer:Buffer.from('joint attachment')}}});expect(upload.status()).toBe(200);const att=await upload.json();expect((await f.api.put('/documents/'+other.id,{data:{updated_at:other.updated_at,content:att.url}})).status()).toBe(200);await f.visit();await del(page);await page.getByRole('radio',{name:/永久删除/}).check();await page.getByRole('button',{name:'确认永久删除'}).click();await expect(page.getByRole('alert')).toContainText('引用');expect(bridge('read',f.doc.id)).not.toBeNull();await f.done('attachment-conflict');
});

test('F6 real invalid-tree conflict is not an attachment error',async({page})=>{
 const f=await setup(page);await f.visit();await del(page);await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();bridge('parent',f.doc.id,f.doc.id);try{await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('alert')).toContainText('树结构异常');expect(bridge('read',f.doc.id).deleted_at).toBeNull();await f.done('invalid-tree');}finally{bridge('parent',f.doc.id);}
});

test('F6 real empty-trash active-child conflict offers child recovery',async({page})=>{
 const f=await setup(page),child=await f.create('Active child',f.doc.id);await f.visit(child.id);bridge('trash',f.doc.id);await empty(page);await page.getByRole('button',{name:'确认永久清空'}).click();await expect(page.getByRole('alert')).toContainText('子页');expect(bridge('read',child.id).deleted_at).toBeNull();expect(bridge('read',f.doc.id)).not.toBeNull();await f.done('active-child-conflict');
});

test('F6 real PG preview lock budget yields incomplete-tree recovery',async({page})=>{
 const f=await setup(page);await f.visit();const holder=spawn('/opt/Yunxi-workstation/Stella/.venv/bin/python',['/opt/hermes-workstation/stella-notes-final-joint-20261016/qa/notes_joint/lock_holder.py'],{stdio:['pipe','pipe','pipe']});await new Promise<void>((resolve,reject)=>{holder.stdout.once('data',()=>resolve());holder.once('error',reject);});try{await del(page);await expect(page.getByRole('alert')).toContainText('树检查未完成');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(0);await f.done('tree-budget');}finally{holder.stdin.end('\n');await new Promise(resolve=>holder.once('exit',resolve));}
});

test('real scope 409 is differentiated and reconfirm needs fresh plan',async({page})=>{
 const f=await setup(page);await f.visit();await del(page);await expect(page.getByRole('button',{name:'确认移入回收站'})).toBeEnabled();const child=await f.create('Arrived after preview',f.doc.id);await page.getByRole('button',{name:'确认移入回收站'}).click();await expect(page.getByRole('alert')).toContainText('范围已变化');expect(bridge('read',f.doc.id).deleted_at).toBeNull();expect(bridge('read',child.id).deleted_at).toBeNull();await page.getByRole('button',{name:'重新读取范围'}).click();await expect(page.getByRole('dialog')).toContainText('1 篇子页面');expect(f.calls.filter(c=>c.method==='DELETE')).toHaveLength(1);await f.done('scope-drift');
});
