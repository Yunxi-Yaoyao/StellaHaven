// Real factory regression: retain the independent review's two texture gates and assertions.
// Run from an isolated frontend export with an empty envDir, private cache, and explicit paths.
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import {chromium} from '@playwright/test';
const root=process.cwd(), base=path.dirname(root), port=15787, MAIN=`http://127.0.0.1:${port}`;
const out=process.env.HOME_SETTINGS_EVIDENCE, modelDir=process.env.HOME_LIVE2D_MODEL_DIR;
assert(out && modelDir, 'Explicit evidence and read-only model paths required');
fs.mkdirSync(out,{recursive:true});
const refs=JSON.parse(fs.readFileSync(modelDir+'/miku.model3.json')).FileReferences;
const files=[...new Set(['miku.model3.json',refs.Moc,refs.Physics,refs.DisplayInfo,...refs.Textures,...refs.Expressions.map(e=>e.File),...Object.values(refs.Motions).flat().map(e=>e.File)].filter(Boolean))];
const resources=files.map(file=>{assert(!file.includes('..')&&!path.isAbsolute(file));const real=fs.realpathSync(path.join(modelDir,file));assert(real.startsWith(fs.realpathSync(modelDir)+path.sep));const body=fs.readFileSync(real);return {file,bytes:body.length,sha256:createHash('sha256').update(body).digest('hex')};});
const harness=root+'/node_modules/.tmp/live2d-partial-load-harness.mjs';
fs.writeFileSync(harness,ts.transpileModule(fs.readFileSync(root+'/e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(harness);
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),resources,cases:[],failures:[]};
const server=await createServer({root,configFile:false,envDir:base+'/empty-env',plugins:[vue()],cacheDir:base+'/partial-vite',server:{host:'127.0.0.1',port,strictPort:true,proxy:{},hmr:false}});
let browser;
try{
 await server.listen(); browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
 for(const mode of ['import-pending','runtime-error','fit-error','cleanup-error','texture-error','late-texture-error','settings-error','moc-error','late-moc-error']){
  const early=mode==='settings-error'||mode.includes('moc-error');
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
  const h=await setup(page,{storage:{stella_home_theme:'nightfall'}}),warnings=[];
  page.on('console',m=>{if(m.type()==='warning')warnings.push(m.text());});
  let release,requested=false; const gate=new Promise(r=>release=r);
  await context.route(MAIN+'/avatar.png',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg"/>'}));
  await context.route(MAIN+'/live2dcubismcore.min.js',r=>mode==='runtime-error'?r.abort('failed'):r.fulfill({path:root+'/public/live2dcubismcore.min.js',contentType:'application/javascript'}));
  await context.route(MAIN+'/assets/miku-l2d/**',async r=>{
   const file=decodeURIComponent(new URL(r.request().url()).pathname.slice('/assets/miku-l2d/'.length));
   if(r.request().method()!=='GET'||!files.includes(file)){h.unknown.push(r.request().url());return r.abort();}
   if((mode==='settings-error'&&file==='miku.model3.json')||(mode.includes('moc-error')&&file===refs.Moc)){
    requested=true;await gate;return r.abort('failed');
   }
   if(mode.includes('texture-error')&&file===refs.Textures[0]){requested=true;await gate;return r.abort('failed');}
   return r.fulfill({path:path.join(modelDir,file),contentType:file.endsWith('.png')?'image/png':file.endsWith('.json')?'application/json':'application/octet-stream'});
  });
  const toggle=async()=>{await page.getByRole('button',{name:'主页设置',exact:true}).click();await page.getByRole('switch',{name:'Live2D 挂件（Miku）'}).click();await page.keyboard.press('Escape');};
  let e={};
  try{
   await page.goto(MAIN);await page.getByRole('button',{name:'主页设置',exact:true}).waitFor();
   const transformed=await server.transformRequest('/src/modules/home/Live2dWidget.vue');
   const modelURL=transformed.code.match(/import\(["']([^"']*cubism4[^"']*)["']\)/)?.[1];assert(modelURL);
   if(mode==='import-pending'){
    await context.route(MAIN+modelURL,async r=>{requested=true;await gate;return r.continue();});
    await toggle(); for(let i=0;i<150&&!requested;i++)await page.waitForTimeout(20);assert(requested,'actual dynamic import HTTP gate');
    await toggle();release();await page.waitForTimeout(1500);
    e=await page.evaluate(()=>({canvases:document.querySelectorAll('.live2d-host canvas').length,handles:['__miku','__mikuApp','__mikuForm','__mikuState'].filter(k=>k in window)}));
    assert.equal(e.canvases,0);assert.deepEqual(e.handles,[]);
   }else if(mode==='runtime-error'){
    await toggle();await page.waitForFunction(()=>!document.querySelector('script[src="/live2dcubismcore.min.js"]'));await page.waitForTimeout(400);
    e=await page.evaluate(()=>({canvases:document.querySelectorAll('.live2d-host canvas').length,model:!!window.__miku}));assert.equal(e.canvases,0);assert(!e.model);assert(warnings.some(s=>s.includes('Live2D initialization failed')));
   }else{
    await page.evaluate(()=>new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='/live2dcubismcore.min.js';s.onload=resolve;s.onerror=reject;document.head.append(s);}));
    const pixiURL=transformed.code.match(/from\s+["']([^"']*pixi[^"']*)["']/)?.[1];assert(pixiURL);
    await page.evaluate(async ({modelURL,pixiURL,mode})=>{
     const {Live2DFactory}=await import(modelURL),{Ticker}=await import(pixiURL);window.__ticker=Ticker.shared;window.__ticks=0;window.__sentinel=()=>window.__ticks++;Ticker.shared.add(window.__sentinel);
     const setup=Live2DFactory.setupLive2DModel;window.__rows=[];
     Live2DFactory.setupLive2DModel=function(model,...args){
      const row={model,destroyCalls:0,settled:false};window.__rows.push(row);
      const destroy=model.destroy;model.destroy=function(...opts){row.destroyCalls++;return destroy.apply(this,opts);};
      if(mode==='fit-error')model.getLocalBounds=()=>{throw new Error('review injected fit failure');};
      return setup.call(this,model,...args).then(v=>{row.settled=true;return v;},err=>{row.settled=true;row.rejected=String(err);throw err;});
     };
     const NativeRO=window.ResizeObserver;window.__ros=[];
     window.ResizeObserver=class extends NativeRO{constructor(cb){super(cb);window.__ros.push(this);}disconnect(){super.disconnect();if(mode==='cleanup-error')throw new Error('review injected observer disconnect failure');}};
    },{modelURL,pixiURL,mode});
    await toggle();
    if(early){
     for(let i=0;i<150&&!requested;i++)await page.waitForTimeout(20);
     assert(requested,'real settings/moc HTTP gate');
     e.internalAbsentBeforeFailure=await page.evaluate(()=>!window.__rows[0].model.internalModel);
     assert(e.internalAbsentBeforeFailure);
     if(mode==='late-moc-error')await toggle();
     release();await page.waitForFunction(()=>window.__rows[0].settled);await page.waitForTimeout(600);
    }else if(mode.includes('texture-error')){
     await page.waitForFunction(()=>window.__rows[0]?.model.internalModel?.coreModel);assert(requested);
     e.coreAllocatedBeforeFailure=await page.evaluate(()=>!!window.__rows[0].model.internalModel.coreModel);
     if(mode==='late-texture-error')await toggle();
     release();await page.waitForFunction(()=>window.__rows[0].settled);await page.waitForTimeout(600);
    }else if(mode==='cleanup-error'){
     await page.waitForFunction(()=>window.__miku?.internalModel?.coreModel);await toggle();await page.waitForTimeout(500);
    }else{await page.waitForFunction(()=>window.__rows[0]?.settled);await page.waitForTimeout(500);}
    const before=await page.evaluate(()=>window.__ticks);await page.waitForTimeout(100);
    Object.assign(e,await page.evaluate(()=>({destroyed:!!window.__rows[0].model.destroyed,internalDestroyed:!!window.__rows[0].model.internalModel?.destroyed,coreReleased:!window.__rows[0].model.internalModel?.coreModel,destroyCalls:window.__rows[0].destroyCalls,autoUpdate:window.__rows[0].model.autoUpdate,rejected:window.__rows[0].rejected,canvases:document.querySelectorAll('.live2d-host canvas').length,handles:['__miku','__mikuApp','__mikuForm','__mikuState'].filter(k=>k in window),ticks:window.__ticks,ownTickerContexts:(()=>{const a=[];let n=window.__ticker._head.next;while(n){if(n.fn!==window.__sentinel)a.push({name:n.fn?.name,context:n.context?.constructor.name});n=n.next;}return a;})()})));
    assert(e.ticks>before);assert.equal(e.canvases,0);assert.deepEqual(e.handles,[]);assert.deepEqual(e.ownTickerContexts,[]);
    if(early){
     assert(e.destroyed&&e.coreReleased&&!e.internalDestroyed,'uninitialized Container must be released without invoking unsafe model destroy');
     assert.equal(e.destroyCalls,0);
     assert.equal(await page.evaluate(()=>window.__rows[0].model.eventNames().length),0);
     assert(!warnings.some(s=>s.includes('Live2D cleanup failed')));
    }else{
     assert(e.destroyed&&e.internalDestroyed&&e.coreReleased&&e.destroyCalls===1,'real allocated model/core must be released after failure');
    }
   }
   assert.deepEqual(h.unknown,[]);assert.deepEqual(h.errors,[]);
   report.cases.push({name:mode,status:'pass',evidence:e,unknown:h.unknown,pageErrors:h.errors,consoleErrors:h.consoleErrors,warnings});
  }catch(err){report.failures.push({name:mode,error:err.stack,evidence:e,unknown:h.unknown,pageErrors:h.errors,consoleErrors:h.consoleErrors,warnings});}
  finally{release();await context.close();}
 }
}finally{await browser?.close();await server.close();fs.rmSync(harness,{force:true});fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));if(report.failures.length)process.exitCode=1;
