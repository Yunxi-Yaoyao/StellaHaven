// Compare the actual API/CSS/font surface across the 0.x compatibility boundary
// before changing Mermaid's dependency. No backend, CDN or shared browser realm.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {build} from 'vite';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdtemp,mkdir} from 'node:fs/promises';
import {join,dirname,extname} from 'node:path';
import {tmpdir} from 'node:os';
import {chromium} from '@playwright/test';
const require=createRequire(import.meta.url),consumer=createRequire(require.resolve('mermaid'));
const current=dirname(consumer.resolve('katex/package.json'));
const candidate=process.env.KATEX_CANDIDATE;
const logs=process.env.RENDERER_LOGS;assert.ok(logs);await mkdir(logs,{recursive:true});
const variants=candidate?[['current',current],['candidate',candidate]]:[['installed',current]];
const results=[];
for(const [name,pkg] of variants){
 const out=await mkdtemp(join(tmpdir(),'katex-browser-'));
 await build({configFile:false,resolve:{alias:[{find:'katex/dist/katex.css',replacement:join(pkg,'dist/katex.css')},{find:'katex',replacement:join(pkg,'dist/katex.mjs')}]},build:{outDir:out,rollupOptions:{input:'tests/fixtures/runtime-katex.html'}},logLevel:'error'});
 const server=createServer(async(req,res)=>{try{const file=new URL(req.url,'http://local').pathname;res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.html':'text/html'})[extname(file)]||'application/octet-stream');res.end(await readFile(join(out,file)));}catch{res.writeHead(404);res.end();}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const context=await browser.newContext({serviceWorkers:'block'});const requests=[],external=[],errors=[];
  await context.route('**/*',r=>{const u=r.request().url();requests.push(u);if(new URL(u).origin!==origin){external.push(u);return r.abort();}return r.continue();});
  await context.routeWebSocket('**/*',s=>s.close());
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/tests/fixtures/runtime-katex.html');await page.waitForFunction(()=>window.mathFixture);
  const layout=await page.evaluate(async()=>{
   const {katex}=window.mathFixture,host=document.querySelector('#math'),results=[];
   for(const output of ['mathml','htmlAndMathml']){
    host.innerHTML=katex.renderToString(String.raw`x^2+\frac{1}{2}+\sqrt{y}+\sum_{i=1}^n i`,{throwOnError:true,displayMode:true,output});
    await document.fonts.ready;const box=host.getBoundingClientRect();
    const frac=host.querySelector('mfrac');results.push({output,width:box.width,height:box.height,frac:!!frac,html:!!host.querySelector('.katex-html'),text:host.textContent});
   }
   return {version:katex.version,cases:results,fonts:[...document.fonts].filter(f=>f.status==='loaded').map(f=>({family:f.family,style:f.style,weight:f.weight}))};
  });
  assert.ok(layout.cases.every(c=>c.frac&&c.width>50&&c.height>30));assert.ok(layout.cases[1].html);assert.ok(layout.fonts.some(f=>f.family==='KaTeX_Main'));
  if(!candidate){
   // Pollution is limited to this fresh browser realm and always restored before
   // returning to Playwright. Inspect raw KaTeX output, without our sanitizer.
   const pollution=await page.evaluate(()=>{
    const host=document.querySelector('#math'),katex=window.mathFixture.katex;
    const rows=[];
    for(const mode of ['options-prototype','global-prototype']){
     const options=mode==='options-prototype'?Object.create({trust:true}):{};
     Object.assign(options,{throwOnError:true,displayMode:true,output:'htmlAndMathml'});
     if(mode==='global-prototype')Object.prototype.trust=true;
     try{
      host.innerHTML=katex.renderToString(String.raw`\href{javascript:alert(1)}{click}+\includegraphics{https://evil.test/image.png}`,options);
      rows.push({mode,unsafe:host.querySelectorAll('a[href],img,mglyph,[href]').length});
     }finally{if(mode==='global-prototype')delete Object.prototype.trust;}
    }
    return rows;
   });
   assert.ok(pollution.every(p=>p.unsafe===0));layout.pollution=pollution;
  }
  assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
  await page.screenshot({path:join(logs,`katex-${name}.png`)});
  results.push({name,...layout,requests,external,errors});
 }finally{await browser.close();await new Promise(r=>server.close(r));}
}
if(candidate){for(let i=0;i<2;i++){for(const axis of ['width','height']){assert.ok(Math.abs(results[0].cases[i][axis]-results[1].cases[i][axis])<2,`formula ${axis} changed across migration`);}}}
await writeFile(join(logs,'katex-browser.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results.map(({requests,...rest})=>rest),null,2));
