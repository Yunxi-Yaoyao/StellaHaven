// Built Vue + current real HTTP API + owned tiny PG; no route.fulfill, no production.
import assert from 'node:assert/strict';
import http from 'node:http';import net from 'node:net';
import {readFileSync,writeFileSync} from 'node:fs';
import {basename} from 'node:path';import {chromium} from 'playwright';
const s=JSON.parse(process.env.STELLA_PROJECT_FIXTURE),e=s.evidence;
const result={passed:false,boundary:'real built App, real routers, disposable PG, seeded authentication only',source_sha:s.source_sha,steps:[]};
const sockets=new Set(),requests=[],errors=[];
const allowed=new Set([new URL(s.source).host,new URL(s.target).host]);
const proxy=http.createServer((_,res)=>{res.writeHead(403);res.end();});
proxy.on('connect',(req,client,head)=>{
 if(!allowed.has(req.url)){client.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
 const up=net.connect(s.port,'127.0.0.1',()=>{client.write('HTTP/1.1 200 Connection Established\r\n\r\n');if(head.length)up.write(head);client.pipe(up);up.pipe(client);});
 for(const sk of [up,client]){sockets.add(sk);sk.on('error',()=>sk.destroy());sk.on('close',()=>sockets.delete(sk));}
});
await new Promise(r=>proxy.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`},args:['--no-sandbox','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',`--ignore-certificate-errors-spki-list=${s.spki}`]});
let page;
const save=()=>{writeFileSync(e+'/browser-results.json',JSON.stringify(result,null,2));writeFileSync(e+'/requests.json',JSON.stringify(requests,null,2));writeFileSync(e+'/errors.json',JSON.stringify(errors,null,2));};
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addCookies([{name:'stella_at',value:s.token,url:s.source,secure:true,httpOnly:true,sameSite:'Strict'}]);
 page=await context.newPage();page.setDefaultTimeout(20000);
 page.on('pageerror',err=>errors.push(err.message));page.on('response',r=>requests.push({method:r.request().method(),url:r.url().replace(/\/p\/[^/]+\//,'/p/[capability]/'),status:r.status()}));
 await page.goto(s.source+'/notes');await page.locator('.notes-page[aria-busy="false"]').waitFor();
 const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'导入',exact:true}).click();await(await chooser).setFiles({name:basename(s.zip),mimeType:'application/zip',buffer:readFileSync(s.zip)});
 await page.getByRole('button',{name:'渲染HTML',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:/预览网页项目|预览 ZIP|预览转换/}).count(),0);
 await page.getByRole('button',{name:'渲染HTML',exact:true}).click();await page.getByRole('button',{name:'完成',exact:true}).waitFor();
 const projects=await page.evaluate(async w=>{const r=await fetch('/web-projects/workspace/'+w);if(!r.ok)throw Error('catalog '+r.status);return r.json();},s.workspace);
 assert.equal(projects.length,1);result.project_id=projects[0].id;assert.equal(projects[0].entry,'index.html');assert.equal(projects[0].files.length,40);result.steps.push('original ZIP committed through real UI/routers/PG, 40 files and exact index.html');
 await page.getByRole('button',{name:'打开首篇',exact:true}).click();
 const frame=page.frameLocator('iframe[title*="网页视图"]');await frame.locator('#schedule').waitFor();
 assert.equal(await frame.locator('aside a[href^="#"]').count(),32);
 await frame.locator('a[href="#N01"]').first().click();await frame.locator('#N01').waitFor();assert.equal(await frame.locator('#schedule').isVisible(),false);
 assert.equal(await frame.locator('body').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(20, 23, 31)');
 assert.equal(await page.locator('.web-project-pane nav[aria-label="网页项目文件"]').count(),0);
 await page.getByRole('button',{name:'项目文件',exact:true}).click();await page.locator('.web-project-pane nav[aria-label="网页项目文件"]').waitFor();
 await page.getByRole('button',{name:'项目文件',exact:true}).click();await page.locator('.web-project-pane nav[aria-label="网页项目文件"]').waitFor({state:'detached'});
 const fold=page.locator('.doc-list .fold-list-btn');if(await fold.isVisible())await fold.click();
 await page.mouse.move(1400,950);
 await page.screenshot({path:e+'/render-desktop.png',fullPage:true});result.steps.push('original CSS and HTML hash navigation render inside actual WebProjectPane; optional project files do not permanently occupy a second sidebar');
 for(const width of [1440,393]){
  await page.setViewportSize({width,height:900});await page.mouse.move(width-15,700);
  await page.waitForTimeout(400); // complete existing drawer/layout transitions before geometry assertions
  if(await page.locator('#site-sidebar.mobile-open').count()){await page.getByRole('button',{name:'收起导航',exact:true}).click();await page.waitForTimeout(300);}
  const box=await page.locator('iframe[title*="网页视图"]').boundingBox();assert.ok(box&&box.height>300&&box.x>=0&&box.x+box.width<=width+1,JSON.stringify({width,box}));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  const visible=await frame.locator('#N01').isVisible();assert.ok(visible);
  await page.screenshot({path:e+`/render-${width}.png`,fullPage:true});
 }
 result.steps.push('desktop/narrow actual pane has usable iframe and no horizontal page overflow');
 // Import original package by conversion into a separate target, without changing source project.
 const dir=page.getByRole('button',{name:'导入',exact:true});if(!await dir.isVisible())await page.getByRole('button',{name:'笔记目录',exact:true}).click();
 const chooser2=page.waitForEvent('filechooser');await page.getByRole('button',{name:'导入',exact:true}).click();await(await chooser2).setFiles({name:basename(s.zip),mimeType:'application/zip',buffer:readFileSync(s.zip)});
 await page.getByRole('button',{name:'转为MD笔记',exact:true}).click();await page.getByRole('button',{name:'完成',exact:true}).waitFor();
 await page.getByRole('button',{name:'打开首篇',exact:true}).click();await page.locator('.markdown-body').waitFor();
 assert.ok((await page.locator('.markdown-body').innerText()).length>1000);await page.screenshot({path:e+'/markdown-converted.png',fullPage:true});
 result.steps.push('same original ZIP converted through real backend and opens ordinary Markdown renderer');
 result.passed=true;save();console.log(JSON.stringify(result));
}catch(error){result.failure=String(error);if(page&&!page.isClosed()){result.last_text=(await page.locator('body').innerText()).slice(-5000);await page.screenshot({path:e+'/failure.png',fullPage:true});}save();throw error;}
finally{await browser.close();for(const sk of sockets)sk.destroy();await new Promise(r=>proxy.close(r));}
