import assert from 'node:assert/strict';
export async function journeys(h){
 const {page,s,results,record,screenshot,read,directory,project,convertedId}=h;
 const failures=[];results.finalExperience={failures,checks:[]};
 const check=async(name,fn)=>{try{await fn();results.finalExperience.checks.push({name,status:'passed'});record(name);}catch(e){failures.push({name,message:e.message,stack:e.stack});await screenshot('final-failed-'+failures.length);}};
 const write=async(path,method,body)=>page.evaluate(async({path,method,body})=>{const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,body:await r.json()};},{path,method,body});
 await page.getByRole('alertdialog',{name:'清空运行数据'}).getByRole('button',{name:'取消',exact:true}).click();
 await page.setViewportSize({width:1440,height:1000});
 await check('U01 real PG appearance B write read reload and fresh empty context',async()=>{
  await page.goto(s.source+'/settings?section=appearance');
  await page.getByRole('heading',{name:'全站外观'}).waitFor();
  const before=await read('/operations/backups/client-preferences');
  const saved=page.waitForResponse(r=>r.url().endsWith('/operations/backups/client-preferences')&&r.request().method()==='PUT'&&r.request().postDataJSON().appearance==='B');
  await page.getByRole('button',{name:/B · 鸢尾蓝/}).click();assert.equal((await saved).status(),200);
  const after=await read('/operations/backups/client-preferences');assert.equal(after.appearance,'B');assert.ok(after.revision>before.revision);
  await page.reload();await page.waitForFunction(()=>document.documentElement.dataset.appearance==='B');await page.getByRole('heading',{name:'全站外观',exact:true}).waitFor();await page.waitForFunction(()=>document.getAnimations().every(a=>a.playState!=='running'||a.effect?.getComputedTiming().iterations===Infinity));await screenshot('final-desktop-appearance-B');
  const context=await page.context().browser().newContext({viewport:{width:393,height:852},deviceScaleFactor:2});
  await context.addCookies([{name:'stella_at',value:s.token,url:s.source,secure:true,httpOnly:true,sameSite:'Strict'}]);
  const other=await context.newPage();await other.goto(s.source+'/settings?section=appearance');await other.waitForFunction(()=>document.documentElement.dataset.appearance==='B');await other.getByRole('heading',{name:'全站外观',exact:true}).waitFor();await other.getByRole('button',{name:/B · 鸢尾蓝/}).waitFor();assert.equal(await other.getByRole('button',{name:/B · 鸢尾蓝/}).getAttribute('aria-pressed'),'true');assert.equal(await other.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await other.waitForFunction(()=>document.getAnimations().every(a=>a.playState!=='running'||a.effect?.getComputedTiming().iterations===Infinity));
  const path=s.evidence+'/final-mobile-fresh-account-B.png';await other.screenshot({path,fullPage:true});results.screenshots.push({path,width:393,scale:2});
  results.finalExperience.appearance={before,after,freshContext:true};await context.close();
 });
 await check('S01 eight section entries profile authentication Notes single drawer Backup disabled real GET',async()=>{
  await page.goto(s.source+'/settings');await page.getByRole('button',{name:'我的资料',exact:true}).waitFor();
  const labels=['我的资料','外观','认证与安全','导航与网站','笔记','服务与通知','备份与恢复','性能与数据'];
  for(const name of labels)assert.equal(await page.getByRole('button',{name,exact:true}).count(),1,name);
  assert.equal(await page.getByRole('button',{name:'修改密码',exact:true}).count(),0,'profile must not duplicate login security');
  await page.getByRole('button',{name:'认证与安全',exact:true}).click();await page.locator('.sess-group').filter({hasText:/^当前会话$/}).waitFor();
  assert.equal(await page.getByRole('button',{name:'修改密码',exact:true}).count(),1);await screenshot('final-real-authentication');
  await page.getByRole('button',{name:'笔记',exact:true}).click();assert.equal(await page.locator('.notes-settings').count(),0);
  const link=page.getByRole('link',{name:/笔记/});results.finalExperience.notesSettingsLinks=await link.allTextContents();await screenshot('final-notes-settings-entry');
  await page.getByRole('button',{name:'备份与恢复',exact:true}).click();const status=await read('/operations/backups');assert.equal(status.config.enabled,false);assert.deepEqual(status.records,[]);results.finalExperience.backup=status;await screenshot('final-backups-default-disabled');
 });
 await page.goto(s.source+'/notes?doc='+convertedId);await page.locator('.editor').waitFor();
 await check('N08 window before chooser multi add uncheck remove lost ACK retry exact one document',async()=>{
  await directory();let choosers=0;const onChooser=()=>choosers++;page.on('filechooser',onChooser);
  await page.getByRole('button',{name:'导入',exact:true}).click();const d=page.getByRole('dialog',{name:'导入笔记 / 网页'});await d.waitFor();assert.equal(choosers,0);
  const input=d.locator('input[type=file]');await page.waitForFunction(()=>!document.querySelector('.file-drop button')?.disabled);
  const file=(name,text)=>({name,mimeType:'text/markdown',buffer:Buffer.from(text)});
  await input.setInputFiles([file('final-keep.md','# Final keep real PG'),file('final-unchecked.md','# Must not import')]);
  await d.getByRole('checkbox',{name:'选择 final-unchecked.md',exact:true}).uncheck();
  await input.setInputFiles(file('final-remove.md','# Remove me'));await d.getByRole('button',{name:'移除 final-remove.md',exact:true}).click();
  assert.equal(await d.getByRole('checkbox',{name:'选择 final-remove.md'}).count(),0);await screenshot('final-import-multi-selection');
  let lost=false;await page.route('**/documents/',async route=>{if(route.request().method()==='POST'&&!lost){lost=true;const response=await route.fetch({ignoreHTTPSErrors:true});assert.equal(response.status(),201);results.finalExperience.lostAck={committed:await response.json()};await route.abort('failed');}else await route.continue();});
  await d.getByRole('button',{name:'导入 1 篇',exact:true}).click();await d.getByRole('button',{name:'重试未成功文件',exact:true}).waitFor();await screenshot('final-import-lost-ack');
  await d.getByRole('button',{name:'重试未成功文件',exact:true}).click();await d.getByRole('button',{name:'完成',exact:true}).waitFor();
  const all=await read('/documents/?workspace_id='+s.workspace+'&limit=1000');results.finalExperience.importReadback=all.map(x=>({id:x.id,title:x.title,file_path:x.file_path}));assert.equal(all.filter(x=>x.title==='final-keep').length,1);assert.equal(all.filter(x=>['final-unchecked','final-remove'].includes(x.title)).length,0);
  await d.getByRole('button',{name:'完成',exact:true}).click();await page.unroute('**/documents/');page.off('filechooser',onChooser);
 });
 await check('N06 reading controls real PATCH CSS and reload',async()=>{
  await page.goto(s.source+'/notes?doc='+convertedId);await page.locator('.editor').waitFor();await directory();await page.getByRole('button',{name:'笔记设置',exact:true}).click();const d=page.getByRole('dialog',{name:'笔记设置',exact:true});await d.waitFor();
  for(const [name,value] of [['字号','20'],['行距','2'],['阅读宽度','960']]){
   const response=page.waitForResponse(r=>r.url().endsWith('/notes-preferences')&&r.request().method()==='PATCH');await d.getByLabel(name,{exact:true}).fill(value);await d.getByLabel(name,{exact:true}).press('Tab');assert.equal((await response).status(),200);
   await page.waitForFunction(()=>!document.querySelector('.reading-settings')?.disabled);
  }
  for(const [name,checked] of [['代码行号',true],['代码自动换行',false],['删除前询问',false]]){
   const response=page.waitForResponse(r=>r.url().endsWith('/notes-preferences')&&r.request().method()==='PATCH');await d.getByRole('checkbox',{name,exact:true}).setChecked(checked);assert.equal((await response).status(),200);await page.waitForFunction(()=>!document.querySelector('.reading-settings')?.disabled);
  }
  const sorting=page.waitForResponse(r=>r.url().endsWith('/notes-preferences')&&r.request().method()==='PATCH');await d.locator('.sort-row').getByRole('button').click();await d.getByRole('button',{name:'标题',exact:true}).click();assert.equal((await sorting).status(),200);
  const stored=await read('/notes-preferences');assert.equal(stored.code_line_numbers,true);assert.equal(stored.code_wrap,false);assert.equal(stored.ask_before_delete,false);assert.equal(stored.directory_sort,'title');assert.equal(stored.font_size,20);assert.equal(stored.line_height,2);assert.equal(stored.read_width,960);
  assert.equal(await page.locator('.preview.markdown-body').evaluate(el=>getComputedStyle(el).fontSize),'20px');assert.equal(await page.locator('.preview.markdown-body').evaluate(el=>getComputedStyle(el).lineHeight),'40px');await screenshot('final-notes-real-reading-settings');
  await d.getByRole('button',{name:'关闭笔记设置'}).click();await page.reload();await page.locator('.preview.markdown-body').waitFor();assert.equal(await page.locator('.preview.markdown-body').evaluate(el=>getComputedStyle(el).fontSize),'20px');assert.equal(await page.locator('.preview.markdown-body').evaluate(el=>getComputedStyle(el).maxWidth),'960px');results.finalExperience.notesPreferences=stored;
  await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'Markdown',exact:true}).click();await page.locator('.input-wrap .cm-lineNumbers').waitFor();assert.equal(await page.locator('.input-wrap .cm-content').evaluate(el=>getComputedStyle(el).whiteSpace),'pre');await screenshot('final-normal-editor-line-numbers-nowrap');await page.getByRole('button',{name:'阅览',exact:true}).click();
 });
 await check('N07 protected root deletion appends hiding retains old selection and drawer section',async()=>{
  const cat=await read('/notes-tools/templates/'+s.workspace);
  const created=await write('/documents/','POST',{workspace_id:s.workspace,title:'既有隐藏目录',file_path:'/final-hidden-folder',content:'',is_folder:true});assert.equal(created.status,201);
  const prefs=await read('/notes-preferences');const setup=await write('/notes-preferences','PATCH',{expected_revision:prefs.revision,hidden_folders:[created.body.id]});assert.equal(setup.status,200);
  await page.reload();await page.locator('.editor').waitFor();await directory();const row=page.locator(`[data-import-parent="${cat.root_id}"]`);await row.hover();await row.getByTitle('删除',{exact:true}).click();
  const d=page.getByRole('dialog',{name:'笔记设置',exact:true});await d.waitFor();await page.getByRole('alertdialog').filter({hasText:'内置目录不可删除'}).waitFor();
  const saved=await read('/notes-preferences');assert.ok(saved.hidden_folders.includes(cat.root_id));assert.ok(saved.hidden_folders.includes(created.body.id));
  const refused=await page.evaluate(async id=>{const r=await fetch('/documents/'+id,{method:'DELETE'});return {status:r.status,body:await r.text()};},cat.root_id);assert.equal(refused.status,409);results.finalExperience.protectedDelete=refused;
  await screenshot('final-system-root-hidden-guide');await page.getByRole('alertdialog').getByRole('button').click();assert.equal(await d.locator('#notes-hidden-folders').getAttribute('open'),'');
  assert.equal(await d.getByRole('checkbox',{name:'模板',exact:true}).isChecked(),true);await d.getByRole('button',{name:'关闭笔记设置'}).click();assert.equal(await page.locator(`[data-import-parent="${cat.root_id}"]`).count(),0);results.finalExperience.hidden=saved;
 });
 await check('W02 real tree move out keeps source editor reference warning',async()=>{
  await page.goto(s.source+'/notes');await page.locator('.notes-page[aria-busy="false"]').waitFor();await directory();
  const manifest=await read('/web-projects/'+project.id),file=manifest.files.find(f=>f.path==='js/label.js'),dir=manifest.directories.find(d=>d.path==='js');assert.ok(file&&dir);
  const root=page.locator(`[data-import-parent="${project.id}"]`);await root.locator('.caret').click();const dr=page.locator(`[data-import-parent="${dir.id}"]`);await dr.locator('.caret').click();
  const row=page.locator(`[data-import-parent="${file.id}"]`);
  const target=manifest.directories.find(d=>d.path==='assets');const warning=page.waitForEvent('dialog');const movedWithin=page.waitForResponse(r=>r.url().endsWith('/documents/'+file.id)&&r.request().method()==='PUT');const drag=row.dragTo(page.locator(`[data-import-parent="${target.id}"]`));const confirm=await warning;assert.match(confirm.message(),/改变相对引用/);await confirm.accept();await drag;assert.equal((await movedWithin).status(),200);assert.ok((await read('/web-projects/'+project.id)).files.some(f=>f.id===file.id&&f.path==='assets/label.js'));results.finalExperience.treeInternalMove={file:file.id,referenceWarning:confirm.message()};
  await page.reload();await page.locator('.notes-page[aria-busy="false"]').waitFor();await directory();if(!await page.locator(`[data-import-parent="${target.id}"]`).isVisible())await root.locator('.caret').click();const targetRow=page.locator(`[data-import-parent="${target.id}"]`);if(!await row.isVisible())await targetRow.locator('.caret').click();await row.hover();await row.getByTitle('移动到…',{exact:true}).click();const dialog=page.locator('.dialog').filter({hasText:'移动「'});await dialog.waitFor();assert.match(await dialog.innerText(),/改变相对引用/);await screenshot('final-tree-move-reference-warning');
  const before=await read(`/web-projects/${project.id}/files/${file.id}`);const response=page.waitForResponse(r=>r.url().endsWith('/documents/'+file.id)&&r.request().method()==='PUT');await dialog.locator('.opt').filter({hasText:/^（根级）$/}).click();assert.equal((await response).status(),200);
  await page.goto(s.source+'/notes?doc='+file.id);await page.locator('.detached-source-pane .cm-content').waitFor();assert.equal((await read('/detached-sources/'+file.id)).content,before.content);assert.match(await page.locator('.detached-source-pane').innerText(),/相对引用不会自动修复/);await screenshot('final-tree-moved-out-source');results.finalExperience.treeMove={file:file.id,before};
 });
 await check('W02 project file rename public UI exists',async()=>{
  await page.goto(s.source+'/notes');await page.locator('.notes-page[aria-busy="false"]').waitFor();await directory();const manifest=await read('/web-projects/'+project.id),file=manifest.files.find(f=>f.path==='quiz.html');const root=page.locator(`[data-import-parent="${project.id}"]`);if(!await page.locator(`[data-import-parent="${file.id}"]`).isVisible())await root.locator('.caret').click();await page.locator(`[data-import-parent="${file.id}"]`).click();await page.locator('.project-code').waitFor();await screenshot('final-project-file-no-rename');
  const buttons=await page.getByRole('button').allTextContents();results.finalExperience.projectFileButtons=buttons;
  assert.ok(await page.getByRole('button',{name:/重命名/}).count()||await page.getByRole('textbox',{name:/名称|文件名|路径/}).count(),'No project-file rename control in source pane or actual project tree');
 });
 await check('legacy notes-upgrade approved no unrelated timeline action',async()=>{
  await page.goto(s.source+'/notes?doc='+convertedId);await page.locator('.editor').waitFor();await page.getByRole('button',{name:'更多',exact:true}).click();await screenshot('final-real-unrelated-timeline-menu');assert.equal(await page.getByRole('button',{name:'关联时间线',exact:true}).count(),0,'Unrelated operational timeline action still mounted in actual DocEditor');
 });
 assert.equal(failures.length,0,JSON.stringify(failures,null,2));
}
