// Real browser/native download over a deliberately slow real FastAPI route.
import {createServer} from '../frontend/node_modules/vite/dist/node/index.js';
import vue from '../frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';
import {readFile,writeFile,stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const root=dirname(dirname(fileURLToPath(import.meta.url)));
const cfg=JSON.parse(await readFile(process.argv[2],'utf8'));
const proxy={target:cfg.backend,changeOrigin:false,headers:{host:'127.0.0.1:'+cfg.frontend_port}};
const server=await createServer({root:join(root,'frontend'),configFile:false,appType:'custom',plugins:[vue()],server:{host:'127.0.0.1',port:cfg.frontend_port,strictPort:true,proxy:{'/operations':proxy,'/auth':proxy}},logLevel:'error'});
server.middlewares.use('/__native_test',async(_req,res,next)=>{
 try{res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/__native_test',`<!doctype html><meta charset="utf-8"><button id="download">下载ZIP</button><p id="status"></p><script type="module">
 import {auth} from '/src/modules/home/auth.ts';
 import {startNativeBackupDownload} from '/src/api/backupDownload.ts';
 auth.me=await fetch('/auth/me').then(r=>r.json());
 document.querySelector('#download').onclick=async()=>{try{await startNativeBackupDownload(${JSON.stringify(cfg.id)});document.querySelector('#status').textContent='dispatched';}catch(e){document.querySelector('#status').textContent='error:'+e;}};
 window.nativeReady=true;</script>`));}catch(e){next(e);}
});
await server.listen();
let browser;
try{
 browser=await chromium.launch({headless:true,args:['--no-sandbox'],executablePath:cfg.chrome});
 const context=await browser.newContext({acceptDownloads:true});
 const origin='http://127.0.0.1:'+cfg.frontend_port;
 for(const [path,data] of [
  ['/auth/register',{username:'native-download-fixture',password:'synthetic-daily-password'}],
  ['/auth/admin/setup',{user_password:'synthetic-daily-password',new_password:'synthetic-independent-admin'}],
  ['/auth/admin/unlock',{password:'synthetic-independent-admin'}],
 ]){const r=await context.request.post(origin+path,{data});if(!r.ok())throw Error('fixture real auth failed '+path+' '+r.status());}
 const page=await context.newPage();const requests=[];const runtime=[];
 page.on('request',r=>{if(r.url().includes('/operations/backups/'))requests.push({method:r.method(),url:r.url()});});
 page.on('pageerror',e=>runtime.push(String(e)));
 await page.goto(origin+'/__native_test');await page.waitForFunction(()=>window.nativeReady);
 await page.evaluate(()=>{window.__blobBuffered=false;Response.prototype.blob=function(){window.__blobBuffered=true;throw Error('ZIP must remain native');};});
 const started=Date.now();const pending=page.waitForEvent('download',{timeout:90000});
 await page.locator('#download').click();const download=await pending;
 await page.locator('#status').filter({hasText:'dispatched'}).waitFor();
 await download.saveAs(cfg.destination);
 const elapsed=Date.now()-started;const size=(await stat(cfg.destination)).size;
 const sha=createHash('sha256').update(await readFile(cfg.destination)).digest('hex');
 if(elapsed<=30000)throw Error('test did not cross former 30s transfer cap');
 if(size!==cfg.bytes || sha!==cfg.sha256)throw Error('native download bytes/hash mismatch');
 if(await page.evaluate(()=>window.__blobBuffered))throw Error('native download used Blob');
 if(runtime.length)throw Error('runtime errors '+runtime);
 if(!requests.some(x=>x.method==='HEAD'))throw Error('missing metadata preflight');
 // Chromium may dispatch attachment GET outside page request events. Python
 // separately asserts the real ASGI server received both HEAD and native GET.
 await writeFile(cfg.report,JSON.stringify({elapsed_ms:elapsed,bytes:size,sha256:sha,expected_sha256:cfg.sha256,native_filename:download.suggestedFilename(),requests,runtime_errors:runtime,blob_buffered:false,kind:'real PG-backed management auth + actual signed ZIP + slow FastAPI native stream; synthetic content only, not production/full database backup'},null,2));
 console.log(JSON.stringify({passed:true,elapsed_ms:elapsed,bytes:size,report:cfg.report}));
}finally{await browser?.close();await server.close();}
