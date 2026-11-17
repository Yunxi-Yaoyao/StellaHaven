// Native unchanged Vue → dedicated HTTP → owned PG → independent FileWorker.
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const cfg=JSON.parse(await readFile(process.argv[2],'utf8'));
const load=path=>import(pathToFileURL(join(cfg.dependencies,path)).href);
const {createServer}=await load('vite/dist/node/index.js');
const {default:vue}=await load('@vitejs/plugin-vue/dist/index.mjs');
const {chromium}=await load('playwright/index.mjs');
// Exercise the exact integrated component and its shared controls, without
// changing dependency files or using any cache outside owned scratch.
// Use the actual integrated frontend root so shared Dropdown/Icon imports
// resolve to the same production files; Vite cache remains owned scratch.
const ui=join(cfg.repo,'frontend');
const component=await readFile(join(ui,'src/modules/servers/NodeFilesView.vue'));
const source_sha256=createHash('sha256').update(component).digest('hex');
const server=await createServer({root:ui,configFile:false,appType:'custom',plugins:[vue()],
 cacheDir:join(cfg.scratch,'vite-acl-cache'),resolve:{alias:{vue:join(cfg.dependencies,'vue/dist/vue.runtime.esm-bundler.js')}},
 optimizeDeps:{entries:[],include:['vue']},server:{host:'127.0.0.1',port:0,fs:{allow:[ui,cfg.dependencies]},
 proxy:{'/node-files':{target:cfg.backend,changeOrigin:false}}},logLevel:'error'});
server.middlewares.use('/__acl',async(_req,res,next)=>{try{
 res.setHeader('Content-Type','text/html; charset=utf-8');
 res.end(await server.transformIndexHtml('/__acl',`<!doctype html><meta charset="utf-8"><div id="app"></div><script type="module">import {createApp,h} from 'vue';import View from '/src/modules/servers/NodeFilesView.vue';createApp({render:()=>h(View,{scopeKey:'acl-owned-session'})}).mount('#app');</script>`));
}catch(e){next(e)}});
let browser;
try{
 await server.listen();
 const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 browser=await chromium.launch({headless:true,executablePath:process.env.STELLA_CHROMIUM||'/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome',args:['--no-sandbox']});
 const context=await browser.newContext();
 await context.addCookies([{name:'stella_at',value:cfg.cookie,url:origin,httpOnly:true,sameSite:'Lax'}]);
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(origin+'/__acl');
 await page.getByRole('button',{name:'private.txt',exact:true}).click();
 await page.getByRole('button',{name:'编辑文本',exact:true}).click();
 const draft='retained ACL refusal draft · 不丢草稿';
 await page.getByLabel('文件内容',{exact:true}).fill(draft);
 const refused=page.waitForResponse(async r=>{
  if(r.request().method()!=='GET'||! /\/node-files\/requests\/[a-f0-9-]+$/.test(new URL(r.url()).pathname))return false;
  const body=await r.json();return body.state==='failed'&&body.error==='metadata_preservation_denied';
 });
 await page.getByRole('button',{name:'保存文件',exact:true}).click();
 const receipt=await (await refused).json();
 await page.getByRole('alert').filter({hasText:'无法保持原文件权限或属主，未保存。'}).waitFor();
 if(await page.getByLabel('文件内容',{exact:true}).inputValue()!==draft)throw Error('ACL refusal discarded draft');
 if(!await page.getByRole('button',{name:'保存文件',exact:true}).isEnabled())throw Error('known safe refusal left unknown write lock');
 if(await page.getByText('文件已保存。',{exact:true}).count())throw Error('ACL refusal presented as saved');
 const readback=await context.request.get(origin+'/node-files/requests/'+receipt.id);
 if(JSON.stringify(await readback.json())!==JSON.stringify(receipt))throw Error('durable readback differs');
 await page.screenshot({path:join(cfg.evidence,'acl-draft.png'),fullPage:true});
 // A separate fresh mount is the positive control; retaining a failed draft
 // across selecting a different file is outside this ACL refusal test.
 await page.reload();
 await page.getByRole('button',{name:'hello.txt',exact:true}).click();
 await page.getByRole('button',{name:'编辑文本',exact:true}).click();
 await page.getByLabel('文件内容',{exact:true}).fill('plain no ACL browser save');
 await page.getByRole('button',{name:'保存文件',exact:true}).click();
 await page.getByText('文件已保存。',{exact:true}).waitFor();
 if(await readFile(join(cfg.root,'hello.txt'),'utf8')!=='plain no ACL browser save')throw Error('ordinary edit broken');
 if(errors.length)throw Error(errors.join('\n'));
 await writeFile(join(cfg.evidence,'acl-browser.json'),JSON.stringify({source_sha256,draft_retained:true,known_failure_not_unknown:true,plain_no_acl_saved:true,receipt,errors},null,2));
 console.log('native unchanged Vue ACL refusal draft retained; ordinary edit saved');
}finally{await browser?.close();await server.close()}
