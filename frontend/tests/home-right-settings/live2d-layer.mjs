// Real local Miku + native Chrome pointer acceptance; all network is fail-closed.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import {chromium} from '@playwright/test';
const root=process.cwd(), port=15884, MAIN=`http://127.0.0.1:${port}`;
const out=process.env.HOME_SETTINGS_EVIDENCE, modelDir=process.env.HOME_LIVE2D_MODEL_DIR;
assert(out&&modelDir); fs.mkdirSync(out,{recursive:true}); fs.mkdirSync(out+'/empty-env',{recursive:true});
const refs=JSON.parse(fs.readFileSync(modelDir+'/miku.model3.json')).FileReferences;
const files=[...new Set(['miku.model3.json',refs.Moc,refs.Physics,refs.DisplayInfo,...refs.Textures,...refs.Expressions.map(e=>e.File),...Object.values(refs.Motions).flat().map(e=>e.File)].filter(Boolean))];
const resources=files.map(file=>{assert(!file.includes('..')&&!path.isAbsolute(file));const real=fs.realpathSync(path.join(modelDir,file));assert(real.startsWith(fs.realpathSync(modelDir)+path.sep));return {file,sha256:createHash('sha256').update(fs.readFileSync(real)).digest('hex')};});
const harness=root+'/node_modules/.tmp/live2d-layer-harness.mjs';
fs.writeFileSync(harness,ts.transpileModule(fs.readFileSync(root+'/e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(harness);
const report={resources,cases:[],failures:[]};
const server=await createServer({root,configFile:false,envDir:out+'/empty-env',plugins:[vue()],cacheDir:out+'/vite',server:{host:'127.0.0.1',port,strictPort:true,proxy:{},hmr:false}});
let browser;
// Scan actual framebuffer and native hit target in the same task, not canvas rectangles.
async function points(page){return page.evaluate(()=>{
 const app=window.__mikuApp, canvas=app.view, r=canvas.getBoundingClientRect(), gl=app.renderer.gl;
 app.renderer.render(app.stage); const w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,buf=new Uint8Array(w*h*4);
 gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,buf);const res=app.renderer.resolution;
 const result={exposed:[],covered:[],transparent:[],rect:{x:r.x,y:r.y,width:r.width,height:r.height}};
 for(let y=3;y<r.height-3;y+=3)for(let x=3;x<r.width-3;x+=3){const sx=r.x+x,sy=r.y+y;if(sx<2||sy<2||sx>innerWidth-2||sy>innerHeight-2)continue;
 const alpha=buf[((h-1-Math.floor(y*res))*w+Math.floor(x*res))*4+3],el=document.elementFromPoint(sx,sy),figure=!!el?.closest('.live2d-host');
 const p={x:sx,y:sy,alpha,target:el?.tagName,cls:el?.getAttribute('class')};
 const solid=alpha>200&&[-5,0,5].every(dy=>[-5,0,5].every(dx=>{const px=Math.floor((x+dx)*res),py=Math.floor((y+dy)*res);return px>=0&&px<w&&py>=0&&py<h&&buf[((h-1-py)*w+px)*4+3]>200;}));if(solid)(figure?result.exposed:result.covered).push(p);else if(alpha===0)result.transparent.push({...p,figure});
 }return result;
});}
try{await server.listen();browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
for(const theme of (process.env.LAYER_RED?['classic']:['daybreak','nightfall','classic'])) for(const [width,height] of (process.env.LAYER_RED?[[390,844]]:[[320,740],[390,844],[844,390],[1440,1000]])){
 const context=await browser.newContext({viewport:{width,height},hasTouch:width<=390}),page=await context.newPage();const h=await setup(page,{storage:{stella_home_theme:theme}});
 await context.route(MAIN+'/live2dcubismcore.min.js',r=>r.fulfill({path:root+'/public/live2dcubismcore.min.js',contentType:'application/javascript'}));
 await context.route(MAIN+'/assets/miku-l2d/**',r=>{const f=decodeURIComponent(new URL(r.request().url()).pathname.slice('/assets/miku-l2d/'.length));if(r.request().method()!=='GET'||!files.includes(f)){h.unknown.push(r.request().url());return r.abort();}return r.fulfill({path:path.join(modelDir,f),contentType:f.endsWith('.png')?'image/png':f.endsWith('.json')?'application/json':'application/octet-stream'});});
 await context.route(MAIN+'/avatar.png',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="#7b7188"/></svg>'}));
 const toggle=async()=>{await page.getByRole('button',{name:'主页设置',exact:true}).click();await page.getByRole('switch',{name:'Live2D 挂件（Miku）'}).click();await page.keyboard.press('Escape');};
 try{await page.goto(MAIN+'/#zones');await toggle();await page.waitForFunction(()=>window.__mikuApp?.stage?.children.length===1);await page.waitForTimeout(1500);
 await page.evaluate(()=>{const i=document.querySelector('.live2d-host').__vueParentComponent;const old=i.vnode.props.onPoke;window.__pokes=0;i.vnode.props.onPoke=(...args)=>{window.__pokes++;return old(...args);};});
 const before=await points(page);assert(before.exposed.length,'visible figure pixels');const p=before.exposed[Math.floor(before.exposed.length/2)];
 await page.screenshot({path:out+`/${theme}-${width}-before.png`,style:'.zone-debug { visibility: hidden !important; }'});if(width<=390)await page.touchscreen.tap(p.x,p.y);else await page.mouse.click(p.x,p.y);
 await page.waitForTimeout(150);const z=await page.locator('.shinano').evaluate(e=>Number(getComputedStyle(e).zIndex));
 assert(z>10,'native click on exposed Miku must raise her above the mobile signature card');
 assert.equal(await page.evaluate(()=>window.__pokes),1,'the first raise click also emits exactly one original poke');
 const toast=await page.locator('.tarot-bubble').boundingBox();assert(toast&&toast.width>=(width<=768?180:100)&&toast.x>=0&&toast.x+toast.width<=width,'tarot toast must not collapse into an offscreen narrow strip');
 await page.screenshot({path:out+`/${theme}-${width}-foreground.png`,style:'.zone-debug { visibility: hidden !important; }'});
 const front=await points(page);
 assert(front.transparent.filter(p=>!p.figure).length>front.transparent.length*0.99,'transparent canvas must not intercept native hit targets');
 // A native click through an actually transparent pixel activates the original button once.
 const gap=front.transparent.find(p=>!p.figure&&p.x>30&&p.x<width-30&&p.y>100&&p.y<height-30);assert(gap);
 await page.evaluate(({x,y})=>{const b=document.createElement('button');b.id='under-alpha';b.textContent='fixture control';b.style.cssText=`position:fixed;left:${x-8}px;top:${y-8}px;width:16px;height:16px;padding:0;z-index:24`;window.__underClicks=0;b.onclick=e=>{window.__underClicks++;e.stopPropagation();};document.querySelector('.home,.daybreak').append(b);},gap);
 assert.equal(await page.evaluate(p=>document.elementFromPoint(p.x,p.y)?.id,gap),'under-alpha');
 await page.mouse.click(gap.x,gap.y);assert.equal(await page.evaluate(()=>window.__underClicks),1);
 assert.equal(await page.locator('.shinano.is-foreground').count(),0);await page.locator('#under-alpha').evaluate(e=>e.remove());
 await page.screenshot({path:out+`/${theme}-${width}-outside.png`,style:'.zone-debug { visibility: hidden !important; }'});
 // Click the real signature-card control on the same click that lowers Miku.
 let fresh=await points(page);let fp=fresh.exposed[Math.floor(fresh.exposed.length/2)];await page.mouse.click(fp.x,fp.y);
 let dialogs=0;page.on('dialog',async d=>{dialogs++;await d.dismiss();});
 if(theme==='classic'){await page.locator('.mood').click();assert.equal(dialogs,1);}else{await page.locator('.mood-line').click();await page.locator('.mp-input').waitFor();await page.getByRole('button',{name:'算了',exact:true}).click();await page.locator('.mp-input').waitFor({state:'detached'});}assert.equal(await page.locator('.shinano.is-foreground').count(),0);
 await page.evaluate(()=>{for(const e of document.querySelectorAll('.home,.daybreak,.content'))e.scrollTop=0;window.scrollTo(0,0);});
 // All following gestures still use native Chrome pointer events.
 const clickZone=async(label,hold=0)=>{const box=await page.locator('.zone-debug').filter({hasText:label}).first().boundingBox();const pts=await points(page);const candidates=pts.exposed.filter(p=>p.x>box.x&&p.x<box.x+box.width&&p.y>box.y&&p.y<box.y+box.height);assert(candidates.length,`native exposed pixels in ${label}`);candidates.sort((a,b)=>Math.hypot(a.x-box.x-box.width/2,a.y-box.y-box.height/2)-Math.hypot(b.x-box.x-box.width/2,b.y-box.y-box.height/2));await page.mouse.move(candidates[0].x,candidates[0].y);await page.mouse.down();if(hold)await page.waitForTimeout(hold);await page.mouse.up();};
 fresh=await points(page);fp=fresh.exposed[Math.floor(fresh.exposed.length/2)];await page.mouse.click(fp.x,fp.y);await page.waitForTimeout(600);
 const previousFace=await page.evaluate(()=>window.__mikuState().faceExpr);const expectedFace=previousFace==='比心'?null:'比心';await page.evaluate(()=>window.__pokes=0);await clickZone('手臂');assert.equal(await page.evaluate(()=>window.__pokes),1);assert.equal(await page.evaluate(()=>window.__mikuState().faceExpr),expectedFace);
 await page.mouse.move(10,10);await page.waitForTimeout(1100);assert.equal(await page.locator('.shinano.is-foreground').count(),1);assert.equal(await page.evaluate(()=>window.__mikuState().faceExpr),expectedFace);
 await page.evaluate(()=>window.__pokes=0);await clickZone('手臂',650);assert.equal(await page.evaluate(()=>window.__pokes),1);assert.equal(await page.evaluate(()=>window.__mikuState().faceExpr),'葱');
 if(height>500){await clickZone('头');await page.waitForTimeout(250);const morph=await points(page);assert(morph.transparent.filter(p=>!p.figure).length>morph.transparent.length*.99,'alpha hit surface follows the morph, including its holes');await page.waitForFunction(()=>window.__mikuForm()===1);await page.waitForTimeout(600);assert((await points(page)).exposed.length>20,'Q-form remains visible and natively clickable');
 await page.screenshot({path:out+`/${theme}-${width}-chibi.png`,style:'.zone-debug { visibility: hidden !important; }'});
 if(width===390&&theme==='nightfall'){await page.setViewportSize({width:320,height:740});await page.waitForTimeout(500);assert.equal(await page.evaluate(()=>window.__mikuForm()),1);assert((await points(page)).exposed.length>20);await page.setViewportSize({width,height});await page.waitForTimeout(500);assert.equal(await page.evaluate(()=>window.__mikuForm()),1);}
 fresh=await points(page);fp=fresh.exposed[Math.floor(fresh.exposed.length/2)];await page.mouse.click(fp.x,fp.y);await page.waitForFunction(()=>window.__mikuForm()===0);}
 await page.getByRole('button',{name:'主页设置',exact:true}).click();assert.equal(await page.locator('.shinano.is-foreground').count(),0);
 const dialog=page.getByRole('dialog',{name:'主页设置',exact:true});await dialog.waitFor();
 assert(await dialog.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),'global drawer is the native top target');
 await page.screenshot({path:out+`/${theme}-${width}-drawer.png`,style:'.zone-debug { visibility: hidden !important; }'});
 const drawer=page.getByRole('switch',{name:'Live2D 挂件（Miku）'});await drawer.click();await page.waitForFunction(()=>!window.__miku);assert.equal(await page.locator('.live2d-hit').count(),0);await drawer.click();await page.keyboard.press('Escape');await page.waitForFunction(()=>window.__mikuApp?.stage.children.length===1);assert.equal(await page.locator('.shinano.is-foreground').count(),0);
 report.cases.push({theme,width,height,status:'pass',before:{rect:before.rect,exposed:before.exposed.length,covered:before.covered.length},foregroundZ:z,headInteraction:height>500?"verified":"not reachable in pre-existing short landscape crop; no composition change"});
 }catch(e){report.failures.push({theme,width,error:e.stack});await page.screenshot({path:out+`/failed-${theme}-${width}.png`});}
 report.cases.push({theme,width,unknown:h.unknown,errors:h.errors});if(h.unknown.length||h.errors.length)report.failures.push({width,diagnostics:h});await context.close();
}
}finally{await browser?.close();await server.close();fs.rmSync(harness,{force:true});fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));if(report.failures.length)process.exitCode=1;
