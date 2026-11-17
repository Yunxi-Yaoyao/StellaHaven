import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import {writeFileSync,readFileSync} from 'node:fs';
import {chromium} from 'playwright';

const s=JSON.parse(process.env.STELLA_PROJECT_FIXTURE);
const evidence=s.evidence;
const results={boundary:'real built App / real HTTP routers / seeded authenticated test session / real isolated PG; not production main or real login',passed:false,steps:[],projects:{},screenshots:[]};
const traffic=[],errors=[],connections=[];
const save=()=>{writeFileSync(evidence+'/results.json',JSON.stringify(results,null,2));writeFileSync(evidence+'/http.json',JSON.stringify(traffic,null,2));writeFileSync(evidence+'/browser-errors.json',JSON.stringify(errors,null,2));};
const record=(name,details={})=>{results.steps.push({name,passed:true,...details});save();console.log('PASS',name,JSON.stringify(details));};
const scrub=u=>u.replace(/\/p\/[^/]+\//,'/p/[capability]/');
const allowed=new Set([new URL(s.source).host,new URL(s.target).host]);
const sockets=new Set();
const proxy=http.createServer((req,res)=>{res.writeHead(403);res.end();});
proxy.on('connect',(req,client,head)=>{
 client.on('error',()=>client.destroy());
 if(!allowed.has(req.url)){client.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
 const up=net.connect(s.port,'127.0.0.1',()=>{connections.push(req.url);client.write('HTTP/1.1 200 Connection Established\r\n\r\n');if(head.length)up.write(head);client.pipe(up);up.pipe(client);});
 for(const socket of [client,up]){sockets.add(socket);socket.on('close',()=>sockets.delete(socket));}
 up.on('error',()=>client.destroy());client.on('error',()=>up.destroy());client.on('close',()=>up.destroy());
});
await new Promise(r=>proxy.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`},args:['--no-sandbox','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',`--ignore-certificate-errors-spki-list=${s.spki}`]});
let context,page;
async function fresh(width=1440){
 context=await browser.newContext({viewport:{width,height:width===393?852:1000},deviceScaleFactor:2});
 await context.addCookies([{name:'stella_at',value:s.token,url:s.source,secure:true,httpOnly:true,sameSite:'Strict'},...(process.env.FINAL_EXPERIENCE==='1'?[{name:'stella_rt',value:'final-experience-test-refresh',url:s.source,secure:true,httpOnly:true,sameSite:'Strict'}]:[])]);
 page=await context.newPage();page.setDefaultTimeout(15000);
 page.on('pageerror',e=>errors.push({type:'pageerror',message:e.message}));
 page.on('console',m=>{if(m.type()==='error')errors.push({type:'console',message:scrub(m.text()).slice(0,600)});});
 page.on('response',r=>{traffic.push({method:r.request().method(),url:scrub(r.url()),status:r.status()});});
 await page.goto(s.source+'/notes');
 await page.locator('.notes-page[aria-busy="false"]').waitFor();
}
async function directory(){if(!await page.getByRole('button',{name:'导入',exact:true}).isVisible())await page.getByRole('button',{name:'笔记目录',exact:true}).click();await page.getByRole('button',{name:'导入',exact:true}).waitFor();}
async function screenshot(name){const path=evidence+'/'+name+'.png';await page.screenshot({path,fullPage:true});results.screenshots.push({path,width:page.viewportSize().width,scale:2});save();}
async function read(path){const r=await page.evaluate(async p=>{const r=await fetch(p);return {status:r.status,data:await r.json()};},path);assert.equal(r.status,200,JSON.stringify(r));return r.data;}
async function importProject(file,entry,label){
 await page.getByRole('button',{name:'导入',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'导入笔记 / 网页'});await dialog.waitFor();
 await dialog.getByRole('button',{name:'选择文件 / 继续添加',exact:true}).waitFor();
 await page.waitForFunction(()=>!document.querySelector('.file-drop button')?.disabled);
 await dialog.locator('input[type=file]').setInputFiles(file);
 await dialog.getByRole('button',{name:'保留原版网页',exact:true}).click();
 const preview=page.waitForResponse(r=>r.url().endsWith('/web-projects/import/preview')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'预览网页项目',exact:true}).click();
 const report=await (await preview).json();assert.ok(report.entries.includes(entry));
 await dialog.getByRole('radio',{name:entry,exact:true}).check();
 await screenshot(label+'-entry-selection');
 const committed=page.waitForResponse(r=>r.url().endsWith('/web-projects/import')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'导入网页项目',exact:true}).click();
 const response=await committed;assert.equal(response.status(),200,await response.text());
 const project=await response.json();results.projects[label]=project;save();
 await dialog.getByRole('button',{name:'网页项目已导入',exact:true}).waitFor();
 await dialog.getByRole('button',{name:'完成',exact:true}).click();
 record(label+' UI import / entry choice',{entry,entries:report.entries,id:project.id});
 return project;
}
async function openRoot(project){
 const row=page.locator(`[data-import-parent="${project.id}"]`);
 await directory();
 await row.waitFor({state:'visible'});
 await row.click();await page.locator('.web-project-pane iframe').waitFor();
}
const frame=()=>page.frameLocator('.web-project-pane iframe');
try{
 await fresh();record('full built Vue App mounted with real auth/me and workspace');
 const project=await importProject(s.zip,'quiz.html','zip');
 await openRoot(project);
 await frame().locator('#version').filter({hasText:'JS-v1'}).waitFor();
 await frame().locator('#pixel').evaluate(img=>{if(!img.complete||img.naturalWidth!==240)throw Error('Relative image did not decode');});
 assert.equal(await frame().locator('body').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(244, 240, 250)');
 assert.equal(await frame().locator('body').evaluate(()=>{try{void parent.document.cookie;return false;}catch{return true;}}),true);
 record('directory click renders chosen entry / relative module CSS image / parent isolated');
 await frame().getByRole('button',{name:'选择 B'}).click();
 await page.getByRole('status').filter({hasText:'网页进度已保存到 Stella'}).waitFor();
 assert.equal((await read(`/web-projects/${project.id}/state`)).data.answer,'B');
 record('answer uses ordinary localStorage and commits through Vue HTTP state API');
 await screenshot('desktop-1440-answer-saved');
 await context.close();record('first browser context fully closed; no storageState copied');
 await fresh();assert.equal(await page.evaluate(()=>localStorage.getItem('answer')),null);
 await openRoot(project);await frame().locator('#score').filter({hasText:'B'}).waitFor();
 record('new empty browser context restores answer from server');
 await screenshot('desktop-1440-fresh-context-restored');
 if(process.env.PROJECT_RENAME_ONLY==='1'){
  await (await import('./project-rename-journeys.mjs')).renameJourneys({page,s,results,record,screenshot,read,directory,project});
 }else{
 // CodeMirror is exercised through actual keyboard input, not internal dispatch.
 let manifest=await read(`/web-projects/${project.id}`);
 const edit=async(path,transform)=>{
  const file=manifest.files.find(f=>f.path===path);assert.ok(file);
  const source=await read(`/web-projects/${project.id}/files/${file.id}`);
  // Real project directory view now shows one level at a time; traverse it.
  const parts=path.split('/');let prefix='';
  for(const part of parts.slice(0,-1)){
   prefix=prefix?prefix+'/'+part:part;
   const directory=manifest.directories.find(d=>d.path===prefix);assert.ok(directory);
   await page.locator(`[data-project-file="${directory.id}"]`).click();
   assert.equal(await page.locator('.editor').count(),0,'Project folder must not become Markdown');
  }
  await page.locator(`[data-project-file="${file.id}"]`).click();
  const editor=page.locator('.project-code .cm-content');await editor.waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.project-code .cm-content span[class]').length>2);
  const colors=await editor.locator('span[class]').evaluateAll(items=>[...new Set(items.map(el=>getComputedStyle(el).color))]);assert.ok(colors.length>1,'Source syntax colors missing');
  assert.equal(await page.locator('.editor').count(),0);
  await editor.click();await page.keyboard.press('Control+A');await page.keyboard.insertText(transform(source.content));
  await page.getByRole('status').filter({hasText:'源码已保存'}).waitFor();
  const saved=await read(`/web-projects/${project.id}/files/${file.id}`);assert.equal(saved.content,transform(source.content));
  record(path+' auto-save via real highlighted source editor',{syntax_colors:colors,background:await page.locator('.project-code .cm-editor').evaluate(el=>getComputedStyle(el).backgroundColor)});await editor.click();await page.keyboard.press('Control+Home');await screenshot(path.replaceAll('/','-')+'-source-saved');
  await page.getByRole('button',{name:'网页视图',exact:true}).click();await frame().locator('#score').filter({hasText:'B'}).waitFor();
 };
 await edit('js/app.js',src=>src+"\ndocument.querySelector('#version').textContent='JS-v2';\n");
 await edit('quiz.html',src=>src.replace('隔离答题原网页','HTML-v2 答题原网页'));
 const oldUrl=await page.locator('.web-project-pane iframe').getAttribute('src');
 await page.getByRole('button',{name:'刷新网页',exact:true}).click();
 await frame().locator('h1').filter({hasText:'HTML-v2'}).waitFor();await frame().locator('#version').filter({hasText:'JS-v2'}).waitFor();
 assert.notEqual(await page.locator('.web-project-pane iframe').getAttribute('src'),oldUrl);
 assert.equal(await frame().locator('#score').textContent(),'B');record('return web view and manual refresh render saved JS/HTML without clearing answer');
 // Change the actual persisted entry, then manually refresh; no API mutation substitute.
 const chooseEntry=async name=>{await page.getByRole('button',{name:'网页入口',exact:true}).click();await page.getByRole('option',{name,exact:true}).click();const entrySaved=page.waitForResponse(r=>r.url().endsWith(`/web-project-files/${project.id}/entry`)&&r.request().method()==='PATCH');await page.getByRole('button',{name:'设为入口',exact:true}).click();assert.equal((await entrySaved).status(),200);await page.getByRole('status').filter({hasText:'入口已保存'}).waitFor();assert.equal((await read(`/web-projects/${project.id}`)).entry,name);assert.equal((await read(`/web-projects/${project.id}/state`)).data.answer,'B');};
 await chooseEntry('index.html');
 await page.getByRole('button',{name:'刷新网页',exact:true}).click();await frame().getByRole('heading',{name:'不要选的默认入口'}).waitFor();
 assert.equal((await read(`/web-projects/${project.id}/state`)).data.answer,'B');
 await chooseEntry('quiz.html');await page.getByRole('button',{name:'刷新网页',exact:true}).click();await frame().locator('#score').filter({hasText:'B'}).waitFor();
 record('named W01/W06 actual entry changed index then quiz via picker and manual refresh; answer retained');await screenshot('named-entry-changed-state-retained');
 const before={};manifest=await read(`/web-projects/${project.id}`);
 for(const f of manifest.files)before[f.id]=await read(`/web-projects/${project.id}/files/${f.id}`);
 await page.getByRole('button',{name:'清空运行数据',exact:true}).click();
 const confirm=page.getByRole('alertdialog',{name:'清空运行数据'});await confirm.waitFor();
 assert.equal((await read(`/web-projects/${project.id}/state`)).data.answer,'B');
 await confirm.getByRole('button',{name:'取消',exact:true}).click();
 assert.equal((await read(`/web-projects/${project.id}/state`)).data.answer,'B');record('clear state first click and cancel do not mutate persisted data');
 await page.getByRole('button',{name:'清空运行数据',exact:true}).click();
 await confirm.getByRole('button',{name:'确认清空',exact:true}).click();
 await frame().locator('#score').filter({hasText:'未作答'}).waitFor();
 assert.deepEqual((await read(`/web-projects/${project.id}/state`)).data,{});
 const after=await read(`/web-projects/${project.id}`);assert.deepEqual(after,manifest);
 for(const f of after.files)assert.deepEqual(await read(`/web-projects/${project.id}/files/${f.id}`),before[f.id]);
 await frame().locator('#pixel').evaluate(img=>{if(!img.complete||img.naturalWidth!==240)throw Error('Image lost after reset');});
 record('confirmed reset clears only runtime; all source metadata/content and image retained');
 await screenshot('desktop-1440-confirmed-reset');
 // Return to directory explicitly; standalone original HTML is a separate UI upload.
 await directory();
 const standalone=await importProject(s.standalone,'standalone.html','html');
 await openRoot(standalone);await frame().locator('#standalone').filter({hasText:'单文件原版 HTML'}).waitFor();record('standalone original HTML UI import and render');
 // Move through the authenticated real API, then exercise actual source-only UI.
 // This checks identity dispatch/save persistence, not physical tree drag acceptance.
 const standaloneManifest=await read(`/web-projects/${standalone.id}`), exported=standaloneManifest.files.find(f=>f.path==='standalone.html');assert.ok(exported);
 const exportedDoc=await read(`/documents/${exported.id}`);
 const moved=await page.evaluate(async({id,stamp})=>{const response=await fetch(`/documents/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({updated_at:stamp,parent_id:null})});return {status:response.status,body:await response.text()};},{id:exported.id,stamp:exportedDoc.updated_at});assert.equal(moved.status,200,moved.body);
 assert.equal((await read(`/web-projects/${standalone.id}`)).files.some(f=>f.id===exported.id),false);
 await page.goto(s.source+'/notes?doc='+exported.id);
 const detached=page.locator('.detached-source-pane'), detachedEditor=detached.locator('.cm-content');await detachedEditor.waitFor();
 assert.equal(await page.locator('.editor,.web-project-pane iframe').count(),0);
 const detachedBefore=await read(`/detached-sources/${exported.id}`), detachedText=detachedBefore.content+'\n<!-- detached persisted -->';
 await detachedEditor.click();await page.keyboard.press('Control+A');await page.keyboard.insertText(detachedText);await detached.getByRole('button',{name:'保存源码',exact:true}).click();
 await page.waitForFunction(async id=>{const r=await fetch(`/detached-sources/${id}`);return r.ok&&(await r.json()).content.includes('detached persisted');},exported.id);
 assert.equal((await read(`/detached-sources/${exported.id}`)).content,detachedText);
 await page.reload();await detachedEditor.waitFor();assert.equal(await detachedEditor.innerText(),detachedText);
 record('authenticated API move-out retains source-only UI, exact save and reload');await screenshot('detached-source-saved');
 await directory();
 await page.getByRole('button',{name:'导入',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'导入笔记 / 网页'});
 await dialog.waitFor();await page.waitForFunction(()=>!document.querySelector('.file-drop button')?.disabled);
 await dialog.locator('input[type=file]').setInputFiles(s.conversion);
 await dialog.getByRole('button',{name:'此 ZIP 中的 HTML 转为笔记',exact:true}).click();
 await dialog.getByRole('button',{name:'预览转换',exact:true}).click();
 await dialog.getByRole('button',{name:'转换并导入 1 篇',exact:true}).waitFor();
 await dialog.locator('summary').filter({hasText:'article.html'}).click();
 await screenshot('html-conversion-preview');
 const conversionResponse=page.waitForResponse(r=>r.url().endsWith('/documents/import/html')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'转换并导入 1 篇',exact:true}).click();
 const convertedResponse=await conversionResponse;assert.equal(convertedResponse.status(),200,await convertedResponse.text());
 const converted=await convertedResponse.json();results.conversion=converted;save();
 await dialog.getByRole('button',{name:'完成',exact:true}).click();
 const convertedId=converted.documents[0].id;
 await page.locator(`[data-import-parent="${convertedId}"]`).click();
 await page.locator('.editor').waitFor();
 const doc=await read(`/documents/${convertedId}`);assert.match(doc.content,/\/attachments\/[0-9a-f-]+/);assert.ok(!doc.content.includes('<script'));
 const img=page.locator('img[alt="原始图片"]');await img.waitFor();await img.evaluate(img=>{if(!img.complete||img.naturalWidth!==240)throw Error('Converted attachment image failed decode');});
 assert.equal(await page.evaluate(()=>window.conversionMustNotRun),undefined);
 record('ordinary HTML ZIP conversion creates editable note with decoded independent attachment image');
 await screenshot('desktop-1440-converted-note-image');
 await page.getByRole('button',{name:'编辑',exact:true}).click();
 await page.getByRole('button',{name:'Markdown',exact:true}).click();
 const normalEditor=page.locator('.input-wrap .cm-content');await normalEditor.click();await page.keyboard.press('Control+End');await page.keyboard.insertText('\n\n普通笔记编辑验收');
 const noteSave=page.waitForResponse(r=>r.url().endsWith(`/documents/${convertedId}`)&&r.request().method()==='PUT');
 await page.keyboard.press('Control+s');assert.equal((await noteSave).status(),200);
 const editedNote=await read(`/documents/${convertedId}`);assert.ok(editedNote.content.includes('普通笔记编辑验收'));assert.match(editedNote.content,/\/attachments\/[0-9a-f-]+/);
 record('converted note editable in ordinary Markdown editor with real PUT save and retained image reference');
 // Real mouse drag from the actual project-image tree row into ordinary body.
 await directory();
 const imageFile=manifest.files.find(f=>f.path==='images/pixel.png'),imageDir=manifest.directories.find(d=>d.path==='images');
 const rootRow=page.locator(`[data-import-parent="${project.id}"]`);
 if(!await page.locator(`[data-import-parent="${imageDir.id}"]`).isVisible())await rootRow.locator('.caret').click();
 const imageDirRow=page.locator(`[data-import-parent="${imageDir.id}"]`);
 if(!await page.locator(`[data-import-parent="${imageFile.id}"]`).isVisible())await imageDirRow.locator('.caret').click();
 await page.evaluate(()=>{window.namedDragEvents=[];for(const type of ['dragstart','drop'])document.addEventListener(type,e=>window.namedDragEvents.push({type,trusted:e.isTrusted,types:[...e.dataTransfer.types],target:e.target.className}),false);});
 const imageBefore=await read(`/web-projects/${project.id}/files/${imageFile.id}`);
 const assetCopy=page.waitForResponse(r=>r.url().includes('/copy-asset')&&r.request().method()==='POST');
 await page.locator(`[data-import-parent="${imageFile.id}"]`).dragTo(page.locator('.editor .panes'));
 const copiedResponse=await assetCopy;assert.equal(copiedResponse.status(),200,await copiedResponse.text());
 results.dragCopy={response:await copiedResponse.json(),events:await page.evaluate(()=>window.namedDragEvents),method:'Playwright real mouse dragTo; browser-created native DataTransfer; no fabricated MIME or dispatchEvent'};save();
 assert.ok(results.dragCopy.events.some(e=>e.type==='dragstart'&&e.trusted&&e.types.includes('application/x-stella-project-image+json')));
 await page.waitForFunction(()=>document.querySelector('.input-wrap .cm-content')?.textContent.includes('pixel.png'));
 const dragSave=page.waitForResponse(r=>r.url().endsWith(`/documents/${convertedId}`)&&r.request().method()==='PUT');await normalEditor.click();await page.keyboard.press('Control+s');assert.equal((await dragSave).status(),200);
 const dragDoc=await read(`/documents/${convertedId}`);assert.match(dragDoc.content,/!\[pixel\.png\]\([^)]*\/attachments\/[0-9a-f-]+/);assert.ok(!dragDoc.content.includes('/web-projects/'));
 assert.deepEqual(await read(`/web-projects/${project.id}/files/${imageFile.id}`),imageBefore);
 results.dragCopy.document_id=convertedId;results.dragCopy.source_file_id=imageFile.id;save();
 await page.getByRole('button',{name:'阅览',exact:true}).click();await page.locator('img[alt="pixel.png"]:visible').evaluate(img=>{if(!img.complete||img.naturalWidth!==240)throw Error('Dragged attachment failed decode');});
 record('named W02 trusted native project-image drag to ordinary body; independent attachment URL and source unchanged',results.dragCopy);await screenshot('named-image-real-drag-attachment');
 // Template creation uses only public dialogs. Existing seeded template is a real PG record.
 const catalog=await read(`/notes-tools/templates/${s.workspace}`),template=catalog.items.find(t=>!t.is_folder);assert.ok(template);
 const templateDoc=await read(`/documents/${template.id}`);
 async function createTemplateNote(title){
  await directory();await page.getByRole('button',{name:'新建',exact:true}).click();const d=page.getByRole('dialog',{name:'新建笔记',exact:true});await d.waitFor();await d.getByPlaceholder('未命名笔记').fill(title);
  await d.getByRole('button',{name:'完整模板目录',exact:true}).click();await d.getByRole('option',{name:template.title,exact:true}).click();
  await d.getByLabel('模板正文预览').waitFor();const created=page.waitForResponse(r=>r.url().endsWith(`/notes-tools/templates/${s.workspace}/create`)&&r.request().method()==='POST');await d.getByRole('button',{name:'创建',exact:true}).click();
  const response=await created;assert.equal(response.status(),201,await response.text());const note=await response.json();await page.locator('.editor').waitFor();const persisted=await read(`/documents/${note.id}`);assert.equal(persisted.content,templateDoc.content);assert.equal(persisted.parent_id,null);assert.notEqual(note.id,template.id);return note;
 }
 const firstTemplateNote=await createTemplateNote('具名模板新建');
 await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'Markdown',exact:true}).click();
 const draftEditor=page.locator('.input-wrap .cm-content');await draftEditor.click();await page.keyboard.press('Control+End');await page.keyboard.insertText('\n设置抽屉保留正文验收');
 const draftText=await draftEditor.innerText(),routeBefore=page.url(),editorHandle=await draftEditor.elementHandle();
 await directory();await page.getByRole('button',{name:'笔记设置',exact:true}).click();const settings=page.getByRole('dialog',{name:'笔记设置',exact:true});await settings.waitFor();
 assert.equal(page.url(),routeBefore);assert.equal(await draftEditor.innerText(),draftText);assert.equal(await editorHandle.evaluate(el=>el.isConnected),true);
 const hiddenSave=page.waitForResponse(r=>r.url().endsWith('/notes-preferences')&&r.request().method()==='PATCH');await settings.getByRole('checkbox',{name:'模板',exact:true}).check();assert.equal((await hiddenSave).status(),200);
 const preferences=await read('/notes-preferences');assert.ok(preferences.hidden_folders.includes(catalog.root_id));
 await screenshot('named-settings-retains-body-hides-template');await settings.getByRole('button',{name:'关闭笔记设置',exact:true}).click();assert.equal(await draftEditor.innerText(),draftText);assert.equal(page.url(),routeBefore);
 assert.equal(await page.locator(`[data-import-parent="${catalog.root_id}"]`).count(),0);
 const draftSaved=page.waitForResponse(r=>r.url().endsWith(`/documents/${firstTemplateNote.id}`)&&r.request().method()==='PUT');await draftEditor.click();await page.keyboard.press('Control+s');assert.equal((await draftSaved).status(),200);assert.ok((await read(`/documents/${firstTemplateNote.id}`)).content.includes('设置抽屉保留正文验收'));
 const hiddenTemplateNote=await createTemplateNote('隐藏模板后仍可新建');
 results.templates={root_id:catalog.root_id,source_id:template.id,first_id:firstTemplateNote.id,hidden_created_id:hiddenTemplateNote.id};save();
 record('named N02/N05/N07 template copies at workspace root; settings retains mounted body and route; hidden template still creates');await screenshot('named-hidden-template-created');
 // 393px layout and drawer preserve the same body; no viewport-wide overflow.
 await page.setViewportSize({width:393,height:852});await page.getByTitle('收起列表',{exact:true}).click();await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'Markdown',exact:true}).click();const mobileEditor=page.locator('.input-wrap .cm-content');await mobileEditor.click();await page.keyboard.press('Control+End');await page.keyboard.insertText('\n手机抽屉正文');const mobileText=await mobileEditor.innerText();
 await directory();await page.getByRole('button',{name:'笔记设置',exact:true}).click();await settings.waitFor();await page.waitForFunction(()=>{const el=document.querySelector('.notes-settings-drawer');return el&&!el.className.includes('enter-')&&!el.getAnimations({subtree:true}).some(a=>a.playState==='running')&&el.getBoundingClientRect().x>=0&&el.getBoundingClientRect().right<=innerWidth;});const bounds=await settings.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=394,JSON.stringify(bounds));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await screenshot('named-mobile-393-settings-body');
 await settings.getByRole('button',{name:'关闭笔记设置',exact:true}).click();assert.equal(await mobileEditor.innerText(),mobileText);record('named N05 mobile 393 drawer fits viewport and closing retains body',{bounds});
 await directory();await page.getByRole('button',{name:'新建',exact:true}).click();await page.getByRole('dialog',{name:'新建笔记',exact:true}).getByRole('button',{name:'完整模板目录',exact:true}).click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await screenshot('named-mobile-393-template-picker');await page.getByRole('dialog',{name:'新建笔记',exact:true}).getByRole('button',{name:'完整模板目录',exact:true}).click();await page.getByRole('dialog',{name:'新建笔记',exact:true}).getByRole('button',{name:'取消',exact:true}).click();
 await context.close();await fresh(393);await openRoot(project);await frame().locator('h1').filter({hasText:'HTML-v2'}).waitFor();
 await frame().locator('#version').filter({hasText:'JS-v2'}).waitFor();await frame().locator('#score').filter({hasText:'未作答'}).waitFor();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await screenshot('mobile-393-project');
 await page.getByRole('button',{name:'清空运行数据',exact:true}).click();await screenshot('mobile-393-clear-confirmation');
 record('mobile 393px / DPR2 real project and confirmation screenshots; no page horizontal overflow');
 if(process.env.FINAL_EXPERIENCE==='1')await (await import('./final-experience-journeys.mjs')).journeys({page,s,results,record,screenshot,read,directory,project,convertedId});
 }
 results.passed=true;results.loopback_hosts=[...new Set(connections)];save();
}catch(e){results.failure={message:e.message,stack:e.stack};if(page&&!page.isClosed()){await screenshot('failure');writeFileSync(evidence+'/failure-body.txt',await page.locator('body').innerText());}save();console.error(e);process.exitCode=1;}
finally{if(context)await context.close();await browser.close();for(const socket of sockets)socket.destroy();await new Promise(r=>proxy.close(r));save();}
