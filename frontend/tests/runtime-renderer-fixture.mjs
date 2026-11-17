import assert from 'node:assert/strict';
import {build} from 'vite';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdtemp} from 'node:fs/promises';
import {join,extname} from 'node:path';
import {tmpdir} from 'node:os';
import {chromium} from '@playwright/test';
const root=await mkdtemp(join(tmpdir(),'renderer-fixture-'));
const logs=process.env.RENDERER_LOGS||'/opt/hermes-workstation/docs/Stella-API/remediation/runtime-renderer-20261016';
await build({build:{outDir:root,rollupOptions:{input:'tests/fixtures/runtime-renderer.html'}},logLevel:'error'});
const server=createServer(async(req,res)=>{try{const file=new URL(req.url,'http://local').pathname;res.setHeader('Content-Type',extname(file)==='.js'?'text/javascript':'text/html');res.end(await readFile(join(root,file)));}catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const result={requests:[],blocked:[],webSockets:[]};
try{
 const context=await browser.newContext({serviceWorkers:'block'});
 context.on('request',request=>result.requests.push(request.url()));
 await context.route('**/*',route=>{const url=route.request().url();if(new URL(url).origin===origin)return route.continue();result.blocked.push(url);return route.abort();});
 await context.routeWebSocket('**/*',socket=>{result.webSockets.push(socket.url());socket.close();});
 const page=await context.newPage();let failed=false;
 await page.route('**/*mermaid.core*.js',route=>{if(!failed){failed=true;return route.abort();}return route.continue();});
 await page.goto(origin+'/tests/fixtures/runtime-renderer.html');await page.waitForFunction(()=>window.fixture);
 result.retry=await page.evaluate(async()=>{
  let firstError=false,secondError=false;try{await window.fixture.loadMermaid();}catch{firstError=true;}
  try{await window.fixture.loadMermaid();}catch{secondError=true;}return {firstError,secondError};
 });
 console.log('retry',result.retry);
 const failedPage=await context.newPage();
 await failedPage.route('**/*mermaid.core*.js',route=>route.abort());
 await failedPage.goto(origin+'/tests/fixtures/runtime-renderer.html');await failedPage.waitForFunction(()=>window.fixture);
 result.loadFailure=await failedPage.evaluate(async()=>{
  const host=document.getElementById('host'),block=document.createElement('div');block.className='mermaid';block.textContent='flowchart LR\nA-->B';host.append(block);
  await window.fixture.renderMermaidBlocks(host,()=>true);
  return {text:block.textContent,processed:block.hasAttribute('data-processed'),svg:!!block.querySelector('svg')};
 });
 assert.equal(result.loadFailure.text,'flowchart LR\nA-->B');assert.equal(result.loadFailure.processed,false);assert.equal(result.loadFailure.svg,false);await failedPage.close();
 await page.unroute('**/*mermaid.core*.js');await page.reload();await page.waitForFunction(()=>window.fixture);
 await page.addScriptTag({url:origin+'/live2dcubismcore.min.js'});
 result.cubism=await page.evaluate(async()=>{
  const {Cubism4ModelSettings,Live2DModel}=await window.fixture.loadCubism();
  const settings=new Cubism4ModelSettings({url:'https://models.example/base/model3.json?token=a%2Bb',Version:3,FileReferences:{Moc:'body.moc3',Textures:['texture.png?cache=a%2Bb']}});
  const url=window.fixture.url;const parsed=url.parse('https://models.example/model3.json?token=a%2Bb&texture[]=one&texture[]=two',true);
  return {core:!!window.Live2DCubismCore,modelAPI:typeof Live2DModel.from,texture:settings.resolveURL(settings.textures[0]),moc:settings.resolveURL(settings.moc),query:parsed.query};
 });
 assert.equal(result.cubism.core,true);assert.equal(result.cubism.modelAPI,'function');assert.equal(result.cubism.texture,'https://models.example/base/texture.png?cache=a%2Bb');assert.equal(result.cubism.moc,'https://models.example/base/body.moc3');assert.deepEqual(result.cubism.query,{token:'a+b',texture:['one','two']});
 result.ownership=await page.evaluate(async()=>{
  const fixture=window.fixture,host=document.getElementById('host');
  const dirty='<a href="https://example.com" target="_blank">normal</a><a data-temp-href-target="injected">marker</a>';
  const before=fixture.sanitizeNoteHtml(dirty),mermaid=await fixture.loadMermaid();
  const original=mermaid.render.bind(mermaid),cases=[];
  try{
   for(const boundary of ['generation','session','source','detach']){
    host.innerHTML='<div class="mermaid">flowchart LR\nA[Start]-->B[End]</div>';
    const block=host.firstElementChild;let live=true,release,started;
    const ready=new Promise(r=>started=r);
    mermaid.render=async(...args)=>{const svg=await original(...args);started();await new Promise(r=>release=r);return svg;};
    const work=fixture.renderMermaidBlocks(host,()=>live);await ready;
    if(boundary==='generation'||boundary==='session')live=false;
    if(boundary==='source')block.textContent='new source';
    if(boundary==='detach')block.remove();
    release();await work;cases.push({boundary,staleSvg:!!block.querySelector('svg'),processed:block.hasAttribute('data-processed')});
   }
  }finally{mermaid.render=original;}
  return {cases,before,after:fixture.sanitizeNoteHtml(dirty)};
 });
 assert.equal(result.ownership.before,result.ownership.after,'Mermaid must not modify note sanitization policy');
 assert.ok(result.ownership.cases.every(c=>!c.staleSvg&&!c.processed));
 const external=[];page.on('request',r=>{if(!r.url().startsWith(origin))external.push(r.url());});
 await page.route('https://evil.test/**',r=>r.abort());
 result.sanitizer=await page.evaluate(()=>{
  const dirty='<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://evil.test/css";</style><image href="https://evil.test/img"/><use href="https://evil.test/u#x"/><foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><img src="https://evil.test/html"/><math xmlns="http://www.w3.org/1998/Math/MathML"><mi href="https://evil.test/m">x</mi></math></div></foreignObject><path fill="url(https://evil.test/p)"/><animate attributeName="href" values="https://evil.test/a"/></svg>';
  const host=document.getElementById('host');host.innerHTML=window.fixture.sanitizeNoteSvg(dirty,true);
  return {unsafe:host.querySelectorAll('image,img,use,animate,[href],[onload],[onerror]').length,html:host.innerHTML};
 });
 await page.waitForTimeout(100);assert.equal(result.sanitizer.unsafe,0);assert.ok(!result.sanitizer.html.includes('evil.test'));assert.deepEqual(external,[]);
 console.log('cubism',result.cubism);
 assert.equal(result.retry.firstError,true);assert.equal(result.retry.secondError,false);
 assert.deepEqual(result.blocked,[]);assert.ok(result.requests.every(url=>new URL(url).origin===origin));
}finally{await writeFile(join(logs,'fixture-browser.json'),JSON.stringify(result,null,2));await browser.close();await new Promise(r=>server.close(r));}
