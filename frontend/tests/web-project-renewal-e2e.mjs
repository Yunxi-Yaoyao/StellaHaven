import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import {writeFileSync,existsSync} from 'node:fs';
import {chromium} from 'playwright';
const s=JSON.parse(process.env.STELLA_PROJECT_FIXTURE);
const results={passed:false,boundary:'real full built Vue App + TLS HTTP + PG; synthetic owner/session/project, accelerated server TTL4s/renew2s',steps:[]};
const traffic=[],sockets=new Set(),allowed=new Set([new URL(s.source).host,new URL(s.target).host]);
const save=()=>{writeFileSync(s.evidence+'/results.json',JSON.stringify(results,null,2));writeFileSync(s.evidence+'/http.json',JSON.stringify(traffic,null,2));};
const record=name=>{results.steps.push(name);console.log('PASS',name);save();};
const proxy=http.createServer((req,res)=>{res.writeHead(403);res.end();});
proxy.on('connect',(req,client,head)=>{
 if(!allowed.has(req.url)){client.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
 const up=net.connect(s.port,'127.0.0.1',()=>{client.write('HTTP/1.1 200 Connection Established\r\n\r\n');if(head.length)up.write(head);client.pipe(up);up.pipe(client);});
 for(const socket of [client,up]){sockets.add(socket);socket.on('close',()=>sockets.delete(socket));}
 up.on('error',()=>client.destroy());client.on('error',()=>up.destroy());client.on('close',()=>up.destroy());
});
await new Promise(r=>proxy.listen(0,'127.0.0.1',r));
let browser,context,page;
try{
 browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`},args:['--no-sandbox','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',`--ignore-certificate-errors-spki-list=${s.spki}`]});
 context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.addCookies([{name:'stella_at',value:s.token,url:s.source,secure:true,httpOnly:true,sameSite:'Strict'}]);
 page=await context.newPage();page.setDefaultTimeout(15000);
 page.on('response',r=>traffic.push({method:r.request().method(),url:r.url().replace(/\/p\/[^/]+\//,'/p/[capability]/'),status:r.status()}));
 await page.goto(s.source+'/notes');await page.locator('.notes-page[aria-busy="false"]').waitFor();
 const row=page.locator(`[data-import-parent="${s.root}"]`);
 if(!await row.isVisible())await page.getByRole('button',{name:'笔记目录',exact:true}).click();
 await row.click();const iframe=page.locator('.web-project-pane iframe');await iframe.waitFor();
 const frame=page.frameLocator('.web-project-pane iframe');await frame.locator('#saved').filter({hasText:'untouched'}).waitFor();
 const initial={url:await iframe.getAttribute('src'),marker:await frame.locator('body').evaluate(()=>window.memoryMarker)};
 await page.evaluate(()=>window.originalIframe=document.querySelector('.web-project-pane iframe'));
 assert.equal(await iframe.getAttribute('sandbox'),'allow-scripts');
 record('real Vue mounted original sandboxed iframe and restored PG answer');
 await page.clock.install();await page.clock.pauseAt(new Date());
 const capability=new URL(initial.url).pathname.split('/')[2];
 writeFileSync(s.evidence+'/expire-request.json',JSON.stringify({capability}));
 const deadline=Date.now()+10000;
 while(!existsSync(s.evidence+'/expire-done.json')&&Date.now()<deadline)await new Promise(r=>setTimeout(r,20));
 assert.ok(existsSync(s.evidence+'/expire-done.json'));
 const moduleURL=new URL('lazy.js',initial.url).href;
 // Error responses intentionally have no CORS grant: opaque iframe fetch
 // rejects rather than exposing the 403 body. Independently verify HTTP status.
 assert.equal(await frame.locator('body').evaluate(async (_,url)=>{try{await fetch(url+'?expired');return 'unexpected';}catch{return 'blocked';}},moduleURL),'blocked');
 assert.equal((await context.request.get(moduleURL+'?expired-http',{ignoreHTTPSErrors:true})).status(),403);
 record('actual expired PG row rejects dynamic HTTP GET while timers paused');
 const renewed=page.waitForResponse(r=>r.url().endsWith('/renew')&&r.request().method()==='POST');
 await page.evaluate(()=>window.dispatchEvent(new Event('online')));
 assert.equal((await renewed).status(),200);
 await page.getByRole('status').filter({hasText:'网页进度已保存到 Stella'}).waitFor();
 assert.equal(await frame.locator('body').evaluate(async (_,url)=>(await import(url+'?restored')).value,moduleURL),'dynamic-module-ok');
 assert.equal(await iframe.getAttribute('src'),initial.url);
 assert.equal(await page.evaluate(()=>window.originalIframe===document.querySelector('.web-project-pane iframe')),true);
 assert.equal(await frame.locator('body').evaluate(()=>window.memoryMarker),initial.marker);
 record('online recovery renews SAME cap URL iframe and JS memory; dynamic import succeeds');
 await page.clock.resume();
 // Real wall time deliberately exceeds the accelerated server TTL. Dynamic
 // imports every second must all succeed without any launch or state writes.
 for(let i=0;i<6;i++){
  await new Promise(r=>setTimeout(r,1000));
  assert.equal(await frame.locator('body').evaluate(async (_,url)=>(await import(url)).value,moduleURL+'?periodic='+i),'dynamic-module-ok');
 }
 assert.equal(await iframe.getAttribute('src'),initial.url);
 assert.equal(await frame.locator('body').evaluate(()=>window.memoryMarker),initial.marker);
 assert.equal(traffic.filter(r=>r.url.endsWith('/launch')).length,1);
 assert.equal(traffic.filter(r=>r.method==='PUT'&&r.url.endsWith('/state')).length,0);
 assert.ok(traffic.filter(r=>r.url.endsWith('/renew')&&r.status===200).length>=3);
 record('real periodic renewal crosses multiple TTLs with continuous dynamic module GET and zero data writes');
 await page.screenshot({path:s.evidence+'/same-iframe-renewed.png',fullPage:true});
 results.passed=true;save();
}catch(e){results.failure={message:e.message,stack:e.stack};save();console.error(e);process.exitCode=1;if(page)await page.screenshot({path:s.evidence+'/failure.png',fullPage:true}).catch(()=>{});}
finally{if(context)await context.close();if(browser)await browser.close();for(const socket of sockets)socket.destroy();await new Promise(r=>proxy.close(r));writeFileSync(s.evidence+'/browser-cleanup.json',JSON.stringify({browser_closed:!browser||!browser.isConnected(),proxy_closed:!proxy.listening}));save();}
