import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';import {execFileSync} from 'node:child_process';
import {createServer} from 'vite';import vue from '@vitejs/plugin-vue';import ts from 'typescript';import {chromium} from '@playwright/test';
const root=process.cwd(),port=15584,MAIN=`http://127.0.0.1:${port}`,out=process.env.HOME_SETTINGS_EVIDENCE,modelDir=process.env.HOME_LIVE2D_MODEL_DIR;
assert(out&&modelDir,'Explicit evidence and read-only model paths required');fs.mkdirSync(out,{recursive:true});
const manifest=JSON.parse(fs.readFileSync(path.join(modelDir,'miku.model3.json'),'utf8'));const refs=manifest.FileReferences;
const files=['miku.model3.json',refs.Moc,refs.Physics,refs.DisplayInfo,...refs.Textures,...refs.Expressions.map(e=>e.File),...Object.values(refs.Motions).flat().map(e=>e.File)].filter(Boolean);
assert(files.every(f=>!f.includes('..')&&!path.isAbsolute(f)),'bounded manifest file names');
const resources=files.map(f=>({file:f,bytes:fs.statSync(path.join(modelDir,f)).size,sha256:createHash('sha256').update(fs.readFileSync(path.join(modelDir,f))).digest('hex')}));
const harness=path.join(root,'node_modules/.tmp/home-background-live2d-harness.mjs');fs.writeFileSync(harness,ts.transpileModule(fs.readFileSync(root+'/e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);const {setup}=await import(harness);
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),modelDir,resources,cases:[],failures:[]};
const server=await createServer({root,configFile:false,plugins:[vue()],cacheDir:out+'/vite',server:{host:'127.0.0.1',port,strictPort:true,proxy:{},hmr:false}});let browser;
try{
 await server.listen();browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
 for(const width of [1440,393]){
 const context=await browser.newContext({viewport:{width,height:width===1440?1000:852}}),page=await context.newPage();const h=await setup(page,{storage:{stella_home_theme:'nightfall'}});const fetched=[];
 await context.route(MAIN+'/live2dcubismcore.min.js',r=>r.fulfill({path:root+'/public/live2dcubismcore.min.js',contentType:'application/javascript'}));
 await context.route(MAIN+'/assets/miku-l2d/**',r=>{const file=decodeURIComponent(new URL(r.request().url()).pathname.slice('/assets/miku-l2d/'.length));if(r.request().method()!=='GET'||!files.includes(file)){h.unknown.push(r.request().url());return r.abort();}fetched.push(file);return r.fulfill({path:path.join(modelDir,file),contentType:file.endsWith('.png')?'image/png':file.endsWith('.json')?'application/json':'application/octet-stream'});});
 await context.route(MAIN+'/avatar.png',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="#7b7188"/></svg>'}));
 const toggle=async()=>{await page.getByRole('button',{name:'主页设置',exact:true}).click();await page.getByRole('switch',{name:'Live2D 挂件（Miku）'}).click();await page.keyboard.press('Escape');};
 try{
  await page.goto(MAIN);await page.getByRole('button',{name:'主页设置',exact:true}).waitFor();await toggle();
  await page.waitForFunction(()=>window.__miku?.internalModel?.coreModel&&window.__mikuApp?.stage?.children?.length>0,{},{timeout:30000});await page.waitForTimeout(1300);
  const initial=await page.evaluate(()=>({textures:window.__miku.textures.length,children:window.__mikuApp.stage.children.length,canvas:document.querySelectorAll('.live2d-host canvas').length,parameters:window.__miku.internalModel.coreModel.getParameterCount?.()}));assert.equal(initial.textures,refs.Textures.length);assert.equal(initial.canvas,1);await page.screenshot({path:out+`/live2d-nightfall-${width}.png`});report.cases.push({name:`actual model rendered ${width}`,initial,status:'pass'});
  await page.evaluate(()=>{window.__oldMiku=window.__miku;window.__oldMikuApp=window.__mikuApp;});
  await page.getByRole('button',{name:'主页设置',exact:true}).click();await page.getByRole('button',{name:/经典.*夜色星空/}).click();await page.keyboard.press('Escape');
  await page.waitForFunction(()=>window.__miku!==window.__oldMiku&&window.__mikuApp?.stage?.children.length>0,{},{timeout:30000});await page.waitForTimeout(1300);await page.screenshot({path:out+`/live2d-classic-${width}.png`});report.cases.push({name:`theme change reloads actual model ${width}`,status:'pass'});
  await page.evaluate(()=>{window.__oldMiku=window.__miku;window.__oldMikuApp=window.__mikuApp;});await toggle();await page.waitForTimeout(1000);assert.equal(await page.locator('.live2d-host canvas').count(),0);
  const cleanup=await page.evaluate(()=>({modelDestroyed:window.__oldMiku._destroyed??window.__oldMiku.destroyed,renderer:!!window.__oldMikuApp.renderer,debugStillOwned:window.__miku===window.__oldMiku}));report.cases.push({name:`off/unmount ${width}`,cleanup,status:cleanup.modelDestroyed?'pass':'fail'});if(!cleanup.modelDestroyed)report.failures.push({name:`model lifecycle ${width}`,cleanup});
  await toggle();await page.waitForFunction(()=>window.__miku!==window.__oldMiku&&window.__mikuApp?.stage?.children.length>0,{},{timeout:30000});report.cases.push({name:`toggle on reload ${width}`,status:'pass'});
 }catch(e){report.failures.push({name:`Live2D ${width}`,error:e.stack});await page.screenshot({path:out+`/failed-${width}.png`});}
 report.cases.push({width,fetched,unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors});if(h.unknown.length||h.errors.length)report.failures.push({name:`diagnostics ${width}`,unknown:h.unknown,errors:h.errors});await context.close();
 }
}finally{await browser?.close();await server.close();fs.rmSync(harness,{force:true});fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));if(report.failures.length)process.exitCode=1;
