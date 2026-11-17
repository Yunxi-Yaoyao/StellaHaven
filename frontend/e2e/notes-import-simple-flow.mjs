// Isolated UI acceptance. Fixture receipts are NOT production persistence evidence.
// STELLA_IMPORT_SOURCE_ZIP is required; never copy private package contents into git.
import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile,mkdtemp,rm} from 'node:fs/promises';
import {basename,dirname,join,resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import JSZip from 'jszip';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const source=process.env.STELLA_IMPORT_SOURCE_ZIP;
assert(source,'Set STELLA_IMPORT_SOURCE_ZIP to the actual package ZIP');
const out=resolve(process.env.STELLA_IMPORT_EVIDENCE??join(tmpdir(),'stella-import-simple-flow'));
await mkdir(out,{recursive:true});
const cache=await mkdtemp(join(tmpdir(),'import-ui-'));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const bytes=await readFile(source),sourceHash=sha(bytes),archive=await JSZip.loadAsync(bytes);
const sourceEntries=Object.values(archive.files).map(e=>e.name);
const uploads=[],unknown=[],runs=[],errors=[];
const modules={
 [resolve(root,'src/stores/notes')]:`export const useNotesStore=()=>({workspaces:[{id:'fixture-ws',name:'资料'}],refreshList:async()=>{}});`,
 [resolve(root,'src/api/notes')]:`export const listDocs=async()=>[];`,
 [resolve(root,'src/modules/home/auth')]:`import {reactive} from 'vue';export const auth=reactive({me:{id:'fixture-owner'},checked:true,sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});export const refreshAccess=async()=>false;`,
};
const entry=`import {createApp,h,ref} from 'vue';import '@fontsource-variable/inter';import '/src/style.css';import ImportDialog from '/src/modules/notes/ImportDialog.vue';createApp({setup(){const show=ref(false);return()=>h('main',[h('button',{id:'entry-import',onClick:()=>show.value=true},'导入'),show.value?h(ImportDialog,{files:[],workspaceId:'fixture-ws',parentId:null,onClose:()=>show.value=false,onOpen:id=>window.opened=id}):null]);}}).mount('#app');`;
const html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div><script type="module" src="/@import-entry"></script></html>';
const fixture={name:'isolated-import-ui',enforce:'pre',resolveId(id,importer){
 if(id==='/@import-entry')return '\0import-entry';
 if(importer&&id.startsWith('.')){const path=resolve(dirname(importer.split('?')[0]),id).replace(/\.ts$/,'');if(path in modules)return '\0fixture:'+path;}
},load(id){if(id==='\0import-entry')return entry;if(id.startsWith('\0fixture:'))return modules[id.slice(9)];},configureServer(server){server.middlewares.use(async(req,res,next)=>{
 try{
  const path=req.url?.split('?')[0];
  if(path==='/'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(html);return;}
  const allowed=['/web-projects/import/preview','/web-projects/import','/documents/import/html/preview','/documents/import/html','/documents/import/zip/preview','/documents/import/zip','/documents/','/documents/import/finalize'];
  if(!path||!allowed.includes(path)){if(/^\/(documents|web-projects|workspaces|auth|attachments)\b/.test(path??'')){unknown.push([req.method,path]);res.statusCode=403;res.end('Unknown fixture API');return;}next();return;}
  assert.equal(req.method,'POST');
  const request=new Request('http://127.0.0.1'+path,{method:'POST',headers:req.headers,body:req,duplex:'half'});
  let data;
  if(path==='/documents/import/finalize')data={synced:1};
  else if(path==='/documents/'){const body=await request.json();uploads.push({path,body});data={id:'fixture-text-id'};}
  else {
   const form=await request.formData(),file=form.get('file'),payload=Buffer.from(await file.arrayBuffer());
   const zip=/\.zip$/i.test(file.name)?await JSZip.loadAsync(payload):null;
   const entries=zip?Object.values(zip.files).map(e=>e.name):[file.name];
   const files=entries.map(path=>({path,size:0,kind:'text'})),htmlEntries=entries.filter(name=>/\.html?$/i.test(name));
   uploads.push({path,filename:file.name,hash:sha(payload),entries,workspace:form.get('workspace_id'),parent:form.get('parent_id'),id:form.get('import_id'),entry:form.get('entry')});
   if(path==='/web-projects/import/preview')data={files,entries:htmlEntries,suggested_entry:htmlEntries.find(p=>/(^|\/)index\.html$/i.test(p))??htmlEntries[0],warnings:[]};
   else if(path==='/web-projects/import')data={id:'fixture-project-id',reused:false};
   else if(path==='/documents/import/html/preview')data={converted_count:htmlEntries.length,documents:htmlEntries.map(source=>({source,target:source.replace(/\.html?$/i,'.md'),markdown:'',losses:[]})),warnings:[]};
   else if(path==='/documents/import/html')data={documents:[{id:'fixture-html-note-id',title:'资料'}]};
   else if(path==='/documents/import/zip/preview')data={entries:entries.map(path=>({path,title:basename(path),kind:path.endsWith('/')?'directory':/\.(md|txt)$/i.test(path)?'document':'attachment',parent_path:dirname(path)==='.'?null:dirname(path)+'/'})),warnings:[],counts:{documents:entries.filter(p=>/\.(md|txt)$/i.test(p)||p.endsWith('/')).length,attachments:entries.filter(p=>/\.png$/i.test(p)).length}};
   else data={documents:[{id:'fixture-zip-note-id',title:'正文',path:'原目录/正文.md',parent_id:'fixture-folder-id'}],attachments:1,warnings:[],reused:false};
  }
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));
 }catch(error){errors.push(String(error));res.statusCode=500;res.end(JSON.stringify({detail:String(error)}));}
 });}};
const server=await createServer({root,configFile:false,appType:'custom',plugins:[fixture,vue()],cacheDir:cache,optimizeDeps:{entries:[],include:['vue','jszip','marked','dompurify']},server:{host:'127.0.0.1',port:0,hmr:false,proxy:{}}});
let browser,lastPage;
try{
 await server.listen();const address=server.httpServer.address(),origin=`http://127.0.0.1:${address.port}`;
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 async function pageAt(viewport){const context=await browser.newContext({viewport});await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());const page=await context.newPage();lastPage=page;page.on('pageerror',e=>errors.push(String(e)));page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text());});await page.goto(origin);return {context,page};}
 async function select(page,file){
  const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'导入',exact:true}).click();
  // Chromium path assignment drops this Unicode source path in this environment.
  // Use the real chooser with byte-identical FilePayload, retaining its original name.
  await(await chooser).setFiles(typeof file==='string'?{name:basename(file),mimeType:'application/zip',buffer:await readFile(file)}:file);
 }
 async function reachable(page,locator){await locator.scrollIntoViewIfNeeded();assert.equal(await locator.evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth&&el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),true);}
 for(const viewport of [{width:1280,height:900},{width:375,height:812}])for(const mode of ['渲染HTML','转为MD笔记']){
  const {context,page}=await pageAt(viewport),start=uploads.length;
  await select(page,source);
  for(const name of ['渲染HTML','转为MD笔记']){const action=page.getByRole('button',{name,exact:true});await action.waitFor({state:'visible'});await reachable(page,action);assert.equal(await action.evaluate(el=>!!el.closest('details')),false);}
  assert.equal(uploads.length,start);assert.equal(await page.getByRole('button',{name:/预览转换|预览网页项目|预览 ZIP/}).count(),0);
  const label=`${viewport.width}-${mode==='渲染HTML'?'html':'md'}`;
  await page.screenshot({path:join(out,`${label}-choices.png`)});
  await page.getByRole('button',{name:mode,exact:true}).click();
  await page.getByRole('button',{name:'完成',exact:true}).waitFor();
  const done=page.getByRole('button',{name:'完成',exact:true});await reachable(page,done);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:join(out,`${label}-done.png`)});
  const expected=mode==='渲染HTML'?'/web-projects/import':'/documents/import/html';
  assert.deepEqual(uploads.slice(start).map(r=>r.path),[expected+'/preview',expected]);
  for(const request of uploads.slice(start)){assert.equal(request.hash,sourceHash);assert.equal(request.filename,basename(source));assert.deepEqual(request.entries,sourceEntries);assert.equal(request.workspace,'fixture-ws');}
  assert.match(uploads.at(-1).id,/^[0-9a-f-]{36}$/);if(mode==='渲染HTML')assert.equal(uploads.at(-1).entry,'index.html');
  await page.getByRole('button',{name:'打开首篇',exact:true}).click();assert.equal(await page.evaluate(()=>window.opened),mode==='渲染HTML'?'fixture-project-id':'fixture-html-note-id');
  runs.push({label,mode,viewport,requests:uploads.slice(start),pickerOpenedFromEntry:true});await context.close();
 }
 const structured=await new JSZip().file('原目录/正文.md','# 正文\n![原图](附件/原图.png)').file('原目录/附件/原图.png',Buffer.from([137,80,78,71,13,10,26,10])).generateAsync({type:'nodebuffer'});
 for(const name of ['普通.md','普通.txt','结构资料.zip']){
  const {context,page}=await pageAt({width:375,height:812}),start=uploads.length;
  const content=name.endsWith('.zip')?structured:Buffer.from('# 原始正文\n普通文本');
  await select(page,{name,mimeType:name.endsWith('.zip')?'application/zip':'text/plain',buffer:content});
  assert.equal(await page.getByRole('button',{name:'渲染HTML',exact:true}).count(),0);
  const action=page.getByRole('button',{name:name.endsWith('.zip')?'导入此 ZIP':'导入 1 篇',exact:true});await action.waitFor();await reachable(page,action);await action.click();await page.getByRole('button',{name:'完成',exact:true}).waitFor();
  if(name.endsWith('.zip')){assert.deepEqual(uploads.slice(start).map(r=>r.path),['/documents/import/zip/preview','/documents/import/zip']);for(const request of uploads.slice(start)){assert.equal(request.hash,sha(content));assert(request.entries.includes('原目录/附件/原图.png'));assert(request.entries.includes('原目录/正文.md'));}}
  else {assert.deepEqual(uploads.slice(start).map(r=>r.path),['/documents/']);assert.equal(uploads.at(-1).body.visibility,'private');}
  runs.push({name,requests:uploads.slice(start)});await context.close();
 }
 assert.deepEqual(unknown,[]);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(source)),sourceHash);
 const tracked=['ImportDialog.vue','HtmlConversionRow.vue','WebProjectImportRow.vue','ZipImportDialog.vue'];
 const hashes=Object.fromEntries(await Promise.all(tracked.map(async name=>[name,sha(await readFile(join(root,'src/modules/notes',name)))])));
 await writeFile(join(out,'browser-results.json'),JSON.stringify({scope:'Isolated real SFC UI with fixture API receipts; no backend writes or production conversion claims',commit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--short'],{cwd:root,encoding:'utf8'}),hashes,source:{name:basename(source),sha256:sourceHash,bytes:bytes.length,entries:sourceEntries},runs,unknown,errors},null,2));
 console.log(JSON.stringify({passed:runs.length,sourceHash,sourceEntries:sourceEntries.length,evidence:out,unknown,errors}));
}catch(error){if(lastPage&&!lastPage.isClosed()){await lastPage.screenshot({path:join(out,'failure.png')});await writeFile(join(out,'failure.json'),JSON.stringify({error:String(error),errors,unknown,uploads,text:await lastPage.locator('body').innerText(),state:await lastPage.evaluate(()=>{const c=document.querySelector('.import-dialog')?.__vueParentComponent?.setupState;return c?{preparing:c.preparing,busy:c.busy,frozen:c.frozen,rows:c.rows,zip:c.zipFiles,html:c.htmlFiles}:null;})},null,2));}throw error;}finally{await browser?.close();await server.close();await rm(cache,{recursive:true,force:true});}
