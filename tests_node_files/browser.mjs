import {createServer} from '../frontend/node_modules/vite/dist/node/index.js';
import vue from '../frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
const repo=dirname(dirname(fileURLToPath(import.meta.url)));
const cfg=JSON.parse(await readFile(process.argv[2],'utf8'));
const sourceFiles=['frontend/src/modules/servers/NodeFilesView.vue','frontend/src/shell/Dropdown.vue','frontend/src/shell/Icon.vue','frontend/src/style.css','frontend/src/main.ts','tests_node_files/browser.mjs'];
async function sourceHashes(){return Object.fromEntries(await Promise.all(sourceFiles.map(async file=>[file,createHash('sha256').update(await readFile(join(repo,file))).digest('hex')])))}
const before=await sourceHashes(),commit=execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim(),dirty=execFileSync('git',['status','--porcelain=v1'],{cwd:repo,encoding:'utf8'}).trim();
await writeFile(join(cfg.evidence,'polish-source.json'),JSON.stringify({commit,dirty,files:before},null,2));
const server=await createServer({root:join(repo,'frontend'),configFile:false,appType:'custom',plugins:[vue()],cacheDir:join(dirname(cfg.root),'vite-cache'),optimizeDeps:{entries:[],include:['vue']},server:{host:'127.0.0.1',port:0,proxy:{'/node-files':{target:cfg.backend,changeOrigin:false}}},logLevel:'error'});
server.middlewares.use('/__node_files',async(_req,res,next)=>{try{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/__node_files',`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><div id="app"></div><script type="module">import {createApp,ref,h} from 'vue';import '@fontsource-variable/inter';import '/src/style.css';import View from '/src/modules/servers/NodeFilesView.vue';const scope=ref('synthetic-owner-session');window.rotateFileScope=()=>scope.value+='-next';createApp({setup(){return()=>h(View,{scopeKey:scope.value})}}).mount('#app');</script>`));}catch(e){next(e)}});
await server.listen();
const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.STELLA_CHROMIUM||'/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome',args:['--no-sandbox']});
 const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:900}});
 await context.addCookies([{name:'stella_at',value:cfg.cookie,url:origin,httpOnly:true,sameSite:'Lax'}]);
 const page=await context.newPage(),errors=[],consoleErrors=[],requests=[],geometry=[];
 page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
 page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/node-files/requests')requests.push(r.postDataJSON())});
 const picker=name=>page.locator('.dd').and(page.getByLabel(name,{exact:true}));
 async function pick(name,label){const dd=picker(name);await dd.locator('.dd-btn').click();await dd.getByRole('option',{name:label,exact:true}).click();}
 async function waitIdle(){await page.getByRole('button',{name:'刷新',exact:true}).waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('.node-files>header button').disabled);}
 page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(origin+'/__node_files');
 await page.getByRole('button',{name:'hello.txt',exact:true}).waitFor();
 if(await page.locator('select').count())throw Error('native select remains');
 // Select a real offline node and a distinct real read-only worker root, then
 // return to the writable root. Every readback below comes from actual APIs.
 await pick('节点','离线文件节点 · 离线');await waitIdle();
 await page.getByText('节点文件服务离线。',{exact:true}).waitFor();
 if(!await page.getByRole('button',{name:'新建文件',exact:true}).isDisabled())throw Error('offline dropdown enabled writes');
 if(requests.at(-1).node_id!==930003)throw Error('node dropdown value not sent as number');
 await pick('节点','隔离文件节点');await waitIdle();
 await page.getByRole('button',{name:'hello.txt',exact:true}).waitFor();
 await pick('允许根','只读目录');await waitIdle();
 await page.getByRole('button',{name:'read-only.txt',exact:true}).waitFor();
 if(requests.at(-1).root!=='readonly'||await page.getByRole('button',{name:'hello.txt',exact:true}).count())throw Error('root dropdown kept old entries');
 if(!await page.getByRole('button',{name:'新建文件',exact:true}).isDisabled())throw Error('read-only dropdown enabled writes');
 await page.getByRole('button',{name:'read-only.txt',exact:true}).click();
 await page.getByRole('region',{name:'文本预览'}).waitFor();
 if(!(await page.locator('pre').textContent()).includes('真实只读允许根回读'))throw Error('root dropdown readback missing');
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await pick('允许根','验收目录');await waitIdle();
 await page.getByRole('button',{name:'hello.txt',exact:true}).click();
 await page.getByRole('region',{name:'文本预览'}).waitFor();
 if(!(await page.locator('pre').textContent()).includes('真实 worker'))throw Error('worker preview missing');
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('checkbox',{name:'隐藏文件'}).check();
 await page.getByRole('button',{name:'.hidden',exact:true}).waitFor();
 // Keyboard and pointer both operate the shared Dropdown; hold a real list
 // receipt to prove native fieldset disabling covers all three trigger buttons.
 let releaseSort,sortReady;
 const sortGate=new Promise(r=>releaseSort=r),sortReadyGate=new Promise(r=>sortReady=r);
 await page.route('**/node-files/requests',async route=>{
  const data=route.request().postDataJSON();
  if(data?.op==='list'&&data.sort==='size'){
   const actual=await route.fetch();sortReady();await sortGate;await route.fulfill({response:actual});
  }else await route.continue();
 });
 const sortTrigger=picker('排序').locator('.dd-btn');await sortTrigger.focus();await sortTrigger.press('ArrowDown');
 await page.getByRole('option',{name:'大小',exact:true}).click();await sortReadyGate;
 for(const name of ['节点','允许根','排序'])if(!await picker(name).locator('.dd-btn').isDisabled())throw Error('busy Dropdown remains enabled: '+name);
 releaseSort();await waitIdle();await page.unroute('**/node-files/requests');
 if(requests.at(-1).sort!=='size'||requests.at(-1).root!=='fixture'||requests.at(-1).node_id!==930001)throw Error('sort/root/node request readback differs');
 const sized=await page.locator('tbody tr').evaluateAll(rows=>rows.map(row=>({name:row.querySelector('.filename').textContent.trim(),size:Number(row.children[1].textContent.replace(/[^0-9]/g,''))})).filter(x=>x.size));
 if(sized.some((entry,index)=>index&&entry.size<sized[index-1].size))throw Error('worker size sort readback not ordered');
 await sortTrigger.focus();await sortTrigger.press('ArrowDown');await page.getByRole('option',{name:'大小',exact:true}).press('Escape');
 if(await sortTrigger.getAttribute('aria-expanded')!=='false'||!await sortTrigger.evaluate(el=>el===document.activeElement))throw Error('Dropdown Escape/focus restoration failed');
 await page.getByRole('button',{name:'folder',exact:true}).click();
 await page.getByText('此目录为空。',{exact:true}).waitFor();
 await page.getByRole('navigation',{name:'路径'}).getByRole('button',{name:'验收目录',exact:true}).click();
 await page.getByRole('button',{name:'hello.txt',exact:true}).waitFor();
 await page.evaluate(()=>{Response.prototype.blob=function(){throw Error('native downloads must not buffer Blob')};});
 const event=page.waitForEvent('download');
 await page.getByRole('button',{name:'下载 download.bin',exact:true}).click();
 const download=await event;const destination=join(cfg.evidence,'F2-download.bin');await download.saveAs(destination);
 const bytes=await readFile(destination),sha=createHash('sha256').update(bytes).digest('hex');
 if(bytes.length!==cfg.bytes||sha!==cfg.sha256)throw Error('actual download mismatch');
 await page.getByRole('button',{name:'新建文件',exact:true}).click();
 await page.getByLabel('名称',{exact:true}).fill('browser-new.txt');
 await page.getByRole('button',{name:'确认创建',exact:true}).click();
 await page.getByRole('button',{name:'browser-new.txt',exact:true}).waitFor();
 await page.getByLabel('上传文件',{exact:true}).setInputFiles({name:'browser-upload.txt',mimeType:'text/plain',buffer:Buffer.from('browser real upload\\n')});
 await page.getByRole('button',{name:'browser-upload.txt',exact:true}).waitFor();
 await page.getByRole('button',{name:'browser-upload.txt',exact:true}).click();
 await page.getByRole('button',{name:'编辑文本',exact:true}).click();
 await page.getByLabel('文件内容',{exact:true}).fill('browser CAS saved\\n');
 await page.getByRole('button',{name:'保存文件',exact:true}).click();
 await page.getByText('文件已保存。',{exact:true}).waitFor();
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 for(const [op,target] of [['改名','browser-renamed.txt'],['复制','browser-copy.txt'],['移动','folder/browser-moved.txt']]){
  const source=op==='改名'?'browser-upload.txt':op==='复制'?'browser-renamed.txt':'browser-copy.txt';
  await page.getByRole('button',{name:`${op} ${source}`,exact:true}).click();
  await page.getByLabel('目标路径',{exact:true}).fill(target);
  await page.getByRole('button',{name:'确认操作',exact:true}).click();
  await page.getByText('操作已完成。',{exact:true}).waitFor();
 }
 if((await readFile(join(cfg.root,'folder/browser-moved.txt'),'utf8'))!=='browser CAS saved\\n')throw Error('browser F2 bytes differ');
 // Same-name creation must fail visibly and retain the entered name.
 await page.getByRole('button',{name:'新建文件',exact:true}).click();
 await page.getByLabel('名称',{exact:true}).fill('browser-new.txt');
 await page.getByRole('button',{name:'确认创建',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'目标已存在'}).waitFor();
 if(await page.getByLabel('名称',{exact:true}).inputValue()!=='browser-new.txt')throw Error('failed input lost');
 await page.getByRole('button',{name:'取消表单',exact:true}).click();
 // CAS conflict: mutate only the task-owned synthetic file after its preview.
 await page.getByRole('button',{name:'hello.txt',exact:true}).click();
 await page.getByRole('button',{name:'编辑文本',exact:true}).click();
 await page.getByLabel('文件内容',{exact:true}).fill('retained conflict draft');
 await writeFile(join(cfg.root,'hello.txt'),'external browser conflict');
 await page.getByRole('button',{name:'保存文件',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'草稿已保留'}).waitFor();
 if(await page.getByLabel('文件内容',{exact:true}).inputValue()!=='retained conflict draft')throw Error('CAS draft lost');
 if(await readFile(join(cfg.root,'hello.txt'),'utf8')!=='external browser conflict')throw Error('CAS overwrote external data');
 page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'关闭',exact:true}).click();
 // Drop a REAL admitted create response, then reload. Reconciliation is GET
 // only; it must never replay the write. No synthetic response is fulfilled.
 let ackCreates=0;
 await page.route('**/node-files/requests',async route=>{
  const data=route.request().postDataJSON();
  if(data?.op==='create'&&data?.path==='ack-uncertain.txt'){
   ackCreates++;const upstream=await route.fetch();if(upstream.status()!==201)throw Error('real create was not admitted');
   const job=await upstream.json();
   for(let i=0;i<100;i++){
    const actual=await context.request.get(origin+'/node-files/requests/'+job.id);
    if((await actual.json()).state==='done')break;
    await new Promise(r=>setTimeout(r,50));
   }
   await route.abort('failed');
  }else await route.continue();
 });
 await page.getByRole('button',{name:'新建文件',exact:true}).click();
 await page.getByLabel('名称',{exact:true}).fill('ack-uncertain.txt');
 await page.getByRole('button',{name:'确认创建',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'回执未明'}).waitFor();
 if(!await page.getByRole('button',{name:'新建文件',exact:true}).isDisabled())throw Error('ambiguous ACK did not fence writes');
 await page.reload();
 await page.getByRole('button',{name:'核对回执',exact:true}).waitFor();
 if(!await page.getByRole('button',{name:'新建文件',exact:true}).isDisabled())throw Error('reload removed unknown fence');
 await page.getByRole('button',{name:'核对回执',exact:true}).click();
 await page.getByText('回执已确认操作完成，请刷新核对文件。',{exact:true}).waitFor();
 if(ackCreates!==1)throw Error('ambiguous create was replayed');
 if(!await page.getByRole('button',{name:'新建文件',exact:true}).isEnabled())throw Error('authoritative readback failed to release completed request');
 await page.getByRole('button',{name:'刷新',exact:true}).click();
 await page.getByRole('button',{name:'ack-uncertain.txt',exact:true}).waitFor();
 // Deliver only actual worker metadata, held across a real component scope change.
 let releasePreview, previewReady, previewSettled;
 const releaseGate=new Promise(r=>releasePreview=r),readyGate=new Promise(r=>previewReady=r),settledGate=new Promise(r=>previewSettled=r);
 let heldActualPreview=false;
 await page.route('**/node-files/requests/*',async route=>{
  if(route.request().method()!=='GET'||!/\/requests\/[a-f0-9-]+$/.test(new URL(route.request().url()).pathname)){await route.continue();return;}
  const actual=await route.fetch();const body=await actual.json();
  if(!heldActualPreview&&body.state==='done'&&body.op==='preview'&&body.result?.text==='external browser conflict'){
   heldActualPreview=true;previewReady();await releaseGate;
   try{await route.fulfill({response:actual})}catch{}finally{previewSettled()}
  }else await route.fulfill({response:actual});
 });
 await page.getByRole('button',{name:'hello.txt',exact:true}).click();
 await readyGate;await page.evaluate(()=>window.rotateFileScope());
 await page.getByRole('button',{name:'ack-uncertain.txt',exact:true}).waitFor();
 releasePreview();await settledGate;
 if(await page.getByRole('region',{name:'文本预览'}).count())throw Error('old scope preview committed late');
 // Long unbroken data is created through the same real write/readback path.
 const longName='node-files-'+('very-long-'.repeat(9))+'name.txt';
 await page.getByRole('button',{name:'新建文件',exact:true}).click();
 await page.getByLabel('名称',{exact:true}).fill(longName);
 await page.getByRole('button',{name:'确认创建',exact:true}).click();
 await page.getByRole('button',{name:longName,exact:true}).waitFor();
 await page.evaluate(()=>document.fonts.ready);
 async function captureGeometry(label){
  const data=await page.evaluate(()=>{
   const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
   const rect=box(document.querySelector('.node-files')),table=document.querySelector('.table-wrap'),style=getComputedStyle(document.querySelector('.node-files'));
   const controls=[...document.querySelectorAll('.dd-btn,.dd-menu,.dd-item,.filename,.actions button,.action-form input,.preview textarea')].filter(el=>el.getBoundingClientRect().width&&el.getBoundingClientRect().height).map(el=>{
    const parent=el.closest('.dd-menu')&& !el.matches('.dd-menu')?el.closest('.dd-menu'):el.matches('.dd-menu')?document.querySelector('.node-files'):el.matches('.dd-btn')?el.closest('.picker'):el.matches('.filename')?el.closest('td'):el.closest('.actions,.action-form,.preview');
    const style=getComputedStyle(el);return {tag:el.tagName,text:el.textContent.trim().slice(0,120),rect:box(el),parent:box(parent),font:style.fontFamily,opacity:style.opacity,color:style.color,background:style.backgroundColor};
   });
   const tokens=Object.fromEntries(['--text-hi','--text-lo','--text-faint','--bg-base','--bg-panel','--bg-raised','--accent','--accent-dim','--font-ui'].map(name=>[name,style.getPropertyValue(name).trim()]));
   const toolbar=[...document.querySelectorAll('.toolbar>.picker,.toolbar>.toggle')].map(box);
   return {toolbar,viewport:{width:innerWidth,height:innerHeight},documentWidth:document.documentElement.scrollWidth,pane:rect,table:{...box(table),clientWidth:table.clientWidth,scrollWidth:table.scrollWidth},font:style.fontFamily,fontSize:style.fontSize,tokens,controls};
  });
  geometry.push({label,...data});
  await writeFile(join(cfg.evidence,'polish-geometry.json'),JSON.stringify(geometry,null,2));
  await page.screenshot({path:join(cfg.evidence,label+'.png')});
  if(data.documentWidth>data.viewport.width||data.table.scrollWidth>data.table.clientWidth+1)throw Error(label+': horizontal overflow');
  for(const c of data.controls)if(c.rect.x<c.parent.x-1||c.rect.right>c.parent.right+1)throw Error(label+': control outside parent '+c.text);
  for(let i=0;i<data.toolbar.length;i++)for(let j=i+1;j<data.toolbar.length;j++){
   const a=data.toolbar[i],b=data.toolbar[j];if(Math.min(a.right,b.right)-Math.max(a.x,b.x)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1)throw Error(label+': toolbar fields overlap');
  }
  for(const token of Object.values(data.tokens))if(!token)throw Error('undefined shared token');
  if(!data.font.startsWith('"Inter Variable"'))throw Error('loaded Inter font stack not active');
 }
 for(const [width,height] of [[1440,900],[393,852],[320,852]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));await page.mouse.move(0,0);
  await captureGeometry('polish-'+width+'-list');
  await page.screenshot({path:join(cfg.evidence,'polish-'+width+'-list-full.png'),fullPage:true});
  const dd=picker('排序');await dd.locator('.dd-btn').click();
  await page.getByRole('option',{name:'修改时间',exact:true}).waitFor();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.dd-menu')).opacity==='1');
  await captureGeometry('polish-'+width+'-dropdown');
  await page.getByRole('option',{name:'修改时间',exact:true}).press('Escape');
  await page.waitForFunction(()=>!document.querySelector('.dd-menu'));
 }
 // Compact create form stays operable at 320; the already-tested file is not
 // created again. Preserve the actual placeholder and control geometry.
 await page.getByRole('button',{name:'新建文件',exact:true}).click();
 await page.getByLabel('名称',{exact:true}).fill('手机新建示例.txt');
 await captureGeometry('polish-320-create-form');
 await page.getByRole('button',{name:'取消表单',exact:true}).click();
 await page.setViewportSize({width:393,height:852});
 const cdp=await context.newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
 const document=await cdp.send('DOM.getDocument');const filenameNode=await cdp.send('DOM.querySelector',{nodeId:document.root.nodeId,selector:'.filename span'});
 const actualFonts=await cdp.send('CSS.getPlatformFontsForNode',{nodeId:filenameNode.nodeId});
 await writeFile(join(cfg.evidence,'polish-platform-fonts.json'),JSON.stringify(actualFonts,null,2));
 if(!actualFonts.fonts.some(font=>font.isCustomFont&&font.familyName.includes('Inter')))throw Error('Latin filename not rendered with loaded Inter');
 await page.evaluate(()=>{Response.prototype.blob=function(){throw Error('mobile native download buffered Blob')};});
 const mobileEvent=page.waitForEvent('download');await page.getByRole('button',{name:'下载 browser-renamed.txt',exact:true}).click();
 const mobile=await mobileEvent;await mobile.saveAs(join(cfg.evidence,'F2-mobile-download.txt'));
 if((await readFile(join(cfg.evidence,'F2-mobile-download.txt'),'utf8'))!==await readFile(join(cfg.root,'browser-renamed.txt'),'utf8'))throw Error('mobile download mismatch');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('mobile document overflow');
 const after=await sourceHashes();if(JSON.stringify(before)!==JSON.stringify(after))throw Error('source changed during browser evidence');
 if(consoleErrors.some(message=>message.includes('[Vue warn]')||/ReferenceError|TypeError|Unhandled/.test(message)))throw Error(consoleErrors.join('\n'));
 if(errors.length)throw Error(errors.join('\n'));
 await writeFile(join(cfg.evidence,'F2-browser.json'),JSON.stringify({kind:'real Vue → FastAPI → file worker → owned Linux files; real cookie validation + PostgreSQL',native_download:true,mobile_native_download:true,cas_draft_retained:true,ambiguous_ack_create_count:ackCreates,ack_reconciled_after_reload:true,late_scope_preview_fenced:heldActualPreview,bytes:bytes.length,sha256:sha,expected_sha256:cfg.sha256,errors,consoleErrors,viewport:['1440x900','393x852','320x852'],dropdown:{native_select_count:0,node_number_readback:true,readonly_root_readback:true,sort_readback:true,busy_triggers_disabled:true,keyboard_escape_focus:true},geometry_samples:geometry.length,commit,dirty,source:before},null,2));
 console.log('native Vue list/preview/hidden/sort/breadcrumb/download PASS',bytes.length,sha);
}finally{await browser?.close();await server.close()}
