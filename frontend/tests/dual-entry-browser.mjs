// Owned HTTPS ingress + deny-by-default CONNECT proxy. No production DNS.
import assert from 'node:assert/strict';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import {readFileSync} from 'node:fs';
import {chromium} from 'playwright';
const spec=JSON.parse(process.env.STELLA_DUAL_BROWSER_FIXTURE);
assert.match(spec.backend,/^http:\/\/127\.0\.0\.1:\d+$/);
const hosts=new Set(spec.lanes.flatMap(lane=>[new URL(lane.source_origin).host,new URL(lane.target_origin).host]));
const connections=[];
const ingress=https.createServer({key:readFileSync(spec.key),cert:readFileSync(spec.cert)},(request,response)=>{
 const host=request.headers.host;
 if(!hosts.has(host)){response.writeHead(421);response.end();return;}
 const lane=spec.lanes.find(l=>new URL(l.source_origin).host===host);
 if(lane&&request.url==='/'){
  response.writeHead(200,{'content-type':'text/html'});
  response.end(`<!doctype html><title>Stella isolated entry boundary</title><h1>${lane.source_origin}</h1><iframe name="module" width="900" height="600"></iframe><form method="POST" target="module" action="${lane.url}"><input name="ticket" value="${lane.fields.ticket}"><button>Open module</button></form>`);return;
 }
 if(lane){response.writeHead(404);response.end();return;}
 const upstream=http.request(spec.backend+request.url,{method:request.method,headers:request.headers},res=>{
  response.writeHead(res.statusCode,res.headers);res.pipe(response);
 });upstream.on('error',()=>{response.writeHead(502);response.end();});request.pipe(upstream);
});
await new Promise(resolve=>ingress.listen(0,'127.0.0.1',resolve));
const proxy=http.createServer((req,res)=>{res.writeHead(403);res.end();});
proxy.on('connect',(req,client,head)=>{
 if(!hosts.has(req.url.replace(/:443$/,''))||!req.url.endsWith(':443')){client.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
 const upstream=net.connect(ingress.address().port,'127.0.0.1',()=>{
  assert.equal(upstream.remoteAddress,'127.0.0.1');connections.push({host:req.url,ip:upstream.remoteAddress});
  client.write('HTTP/1.1 200 Connection Established\r\n\r\n');if(head.length)upstream.write(head);client.pipe(upstream);upstream.pipe(client);
 });upstream.on('error',()=>client.destroy());client.on('error',()=>upstream.destroy());client.on('close',()=>upstream.destroy());
});
await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));
// Trust only the freshly generated synthetic test certificate's SPKI, not all TLS.
const browser=await chromium.launch({headless:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`},args:['--no-sandbox','--disable-dev-shm-usage','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',`--ignore-certificate-errors-spki-list=${spec.spki}`]});
try{
 for(const lane of spec.lanes){
  const context=await browser.newContext({viewport:{width:1100,height:760},deviceScaleFactor:2,serviceWorkers:'block'});
  const page=await context.newPage();await page.goto(lane.source_origin+'/');await page.getByRole('button',{name:'Open module'}).click();
  const frame=page.frame({name:'module'});await frame.waitForURL(lane.target_origin+'/html');await frame.getByText('private synthetic page').waitFor();
  const grant=(await context.cookies(lane.target_origin)).find(c=>c.name==='__Host-stella_integration');
  assert.ok(grant);assert.ok(grant.secure&&grant.httpOnly);assert.equal(grant.sameSite,'Strict');assert.equal(grant.domain,new URL(lane.target_origin).hostname);
  assert.equal((await context.cookies(lane.source_origin)).length,0);
  await frame.evaluate(()=>location.reload());await frame.getByText('private synthetic page').waitFor();
  await page.screenshot({path:spec.evidence+'/'+lane.name+'-browser.png',fullPage:true});
  await page.getByRole('button',{name:'Open module'}).click();await frame.getByText('启动票据失效',{exact:false}).waitFor();
  console.log(JSON.stringify({lane:lane.name,bootstrap:true,hostOnlySecureCookie:true,refresh:true,replayDenied:true,connections}));
  await context.close();
 }
}finally{await browser.close();proxy.close();ingress.close();}
