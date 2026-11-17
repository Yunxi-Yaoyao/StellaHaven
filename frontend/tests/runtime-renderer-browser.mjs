import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join,extname} from 'node:path';
import {chromium} from '../node_modules/@playwright/test/index.mjs';
const root=process.cwd();
const logs=process.env.RENDERER_LOGS || '/opt/hermes-workstation/docs/Stella-API/remediation/runtime-renderer-20261016';
await mkdir(logs,{recursive:true});
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,'http://local').pathname;const file=path.startsWith('/static/')||path.endsWith('.js')?path:'/index.html';const data=await readFile(join(root,'dist',file));res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.html':'text/html'})[extname(file)]||'application/octet-stream');res.end(data);}catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const results={browser:browser.version(),cases:[],requests:[],pageErrors:[]};
try {
 const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
 await context.routeWebSocket('**/*',socket=>socket.close());
 const page=await context.newPage();
 page.on('pageerror',e=>results.pageErrors.push(e.message));page.on('request',r=>results.requests.push(r.url()));
 let content='# Plain Markdown\n\nText **bold** and [safe link](https://example.com).';
 const doc=()=>({id:'doc-a',title:'Renderer acceptance',file_path:'/test.md',workspace_id:'ws-a',parent_id:null,content,updated_at:'2026-10-16T00:00:00Z',created_at:'2026-10-16T00:00:00Z',has_draft:false,status:'published',is_folder:false});
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url()),p=u.pathname;const fulfill=body=>route.fulfill({json:body});
  if(u.origin!==origin)return route.abort();
  if(p==='/auth/me'||p==='/auth/refresh')return fulfill({id:'user-a',username:'fixture',role:'admin',is_admin:true});
  if(p.startsWith('/workspaces/'))return fulfill(p==='/workspaces/'?[{id:'ws-a',name:'fixture',user_id:'user-a'}]:{id:'ws-a',name:'fixture'});
  if(p==='/documents/doc-a')return fulfill(doc());
  if(p==='/documents/')return fulfill([{...doc(),content:undefined}]);
  if(p.startsWith('/documents/')||p.startsWith('/tags')||p.startsWith('/doc-tags')||p.startsWith('/attachments')||p.startsWith('/document-links'))return fulfill([]);
  if(p==='/auth/sessions')return fulfill([]);
  if(p.startsWith('/auth/')||p.startsWith('/api/')||p.startsWith('/config/')||p.startsWith('/website-settings')||p.startsWith('/navigation'))return fulfill({});
  return route.continue();
 });
 await page.addInitScript(()=>{localStorage.clear();localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'user-a',workspaceId:'ws-a'}));localStorage.setItem('stella_note_edit_mode','markdown');localStorage.setItem('stella_ipinfo',JSON.stringify({ip:'127.0.0.1',region:'fixture',at:Date.now()}));});
 await page.goto(origin+'/notes');await page.waitForSelector('.preview h1',{state:'attached'});
 results.plainRequests=[...results.requests];
 assert.equal(await page.locator('.preview strong').textContent(),'bold');
 assert.equal(results.plainRequests.some(u=>u.includes('mermaid.core')),false,'plain notes must not fetch Mermaid');
 const cases=[
 ['flowchart','flowchart LR\nA[Start]-->B[End]','Start'],
 ['sequence','sequenceDiagram\nAlice->>Bob: Hello\nBob-->>Alice: Hi','Hello'],
 ['class','classDiagram\nAnimal <|-- Duck\nAnimal : +int age','Animal'],
 ['state','stateDiagram-v2\n[*] --> Still\nStill --> Moving','Still'],
 ['math','flowchart LR\nA["$$x^2 + \\frac{1}{2}$$"] --> B[End]','End'],
 ['invalid','flowchart LR\nA--',null],
 ['html','flowchart LR\nA["<img src=https://evil.test/x onerror=alert(1)>"]',null],
 ['image','flowchart LR\nA@{ img: "https://evil.test/x" }',null],
 ['css','flowchart LR\nA-->B\nclassDef default fill:url(https://evil.test/x)',null],
 ['directive','%%{init: {"securityLevel":"loose","themeCSS":"@import url(https://evil.test/css)"}}%%\nflowchart LR\nA-->B',null],
 ['encoded','flowchart LR\nA["&lt;img src=https://evil.test/x&gt;"]',null],
 ['math-css','flowchart LR\nA-->B\nclassDef default fill:/*$$*/url(https://evil.test/x)/*$$*/',null],
 ['math-include','flowchart LR\nA["$$\\includegraphics{https://evil.test/x}$$"] --> B[End]',null],
 ['class-stereotype','classDiagram\nclass Animal {\n<<interface>>\n+eat()\n}','Animal'],
 ['link','flowchart LR\nA[Start]-->B[End]\nclick A "javascript:alert(1)"\nclick B "https://evil.test/link"','Start'],
 ];
 for(const [name,code,label] of cases){
  content='# '+name+'\n\n```mermaid\n'+code+'\n```';const start=performance.now();await page.reload();
  await page.waitForSelector('.preview .mermaid[data-processed]',{state:'attached',timeout:30000});
  const detail=await page.locator('.preview .mermaid').evaluate(el=>({svg:!!el.querySelector('svg'),text:el.textContent,math:el.querySelectorAll('math').length,foreign:el.querySelectorAll('foreignObject').length,paths:el.querySelectorAll('path').length,unsafe:el.querySelectorAll('script,image,use,animate,[onload],[onerror],[href],[xlink\\:href]').length,html:el.innerHTML}));
  results.cases.push({name,elapsedMs:performance.now()-start,...detail});
  if(label){assert.ok(detail.svg,name);assert.ok(detail.text.includes(label),name);assert.equal(detail.unsafe,0,name);}else assert.equal(detail.svg,false,name);
  if(name==='math'){await page.screenshot({path:join(logs,'math.png'),fullPage:true});assert.ok(detail.math>0,'Math must be typeset, not raw dollar-delimited source');}
  if(label)assert.ok(detail.html.includes('<style>'),'renderer colors must survive');
 }
 results.exports={};
 for(const format of ['md','html','png','pdf']){
  await page.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'导出',exact:true}).click();
  await page.locator(`.fmt-opt input[value="${format}"]`).check();const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'确定导出',exact:true}).click();const download=await downloading;
  const bytes=await readFile(await download.path());const text=bytes.toString('utf8');results.exports[format]={filename:download.suggestedFilename(),bytes:bytes.length};
  if(format==='md')assert.equal(text,'# Renderer acceptance\n\n'+content);
  if(format==='html'){assert.ok(text.includes('class="mermaid"'));assert.ok(!text.includes('<script'));assert.ok(!text.includes('cdn.jsdelivr'));}
  if(format==='png')assert.equal(bytes.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  if(format==='pdf')assert.equal(text.slice(0,5),'%PDF-');
  await page.waitForSelector('.export-mask',{state:'hidden'});
 }
 results.resources=await page.evaluate(()=>performance.getEntriesByType('resource').map(e=>({name:e.name,bytes:e.transferSize,duration:e.duration})));
 assert.deepEqual(results.requests.filter(u=>!u.startsWith(origin)),[]);
 assert.deepEqual(results.pageErrors,[]);
 await page.screenshot({path:join(logs,'production.png'),fullPage:true});
 console.log(JSON.stringify(results.cases.map(({html,...c})=>c),null,2));
} finally {await writeFile(join(logs,'production-browser.json'),JSON.stringify(results,null,2));await browser.close();await new Promise(r=>server.close(r));}
