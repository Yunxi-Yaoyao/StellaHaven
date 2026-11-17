import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import {writeFileSync} from 'node:fs';
import {chromium} from 'playwright';
const s=JSON.parse(process.env.STELLA_TIMELINE_FIXTURE);
const results={passed:false,boundary:'full production-built Vue, TLS/HTTP and isolated PG; synthetic session; no API fulfill',views:[]};
const traffic=[],errors=[],sockets=new Set();
const save=()=>{writeFileSync(s.evidence+'/results.json',JSON.stringify(results,null,2));writeFileSync(s.evidence+'/http.json',JSON.stringify(traffic,null,2));writeFileSync(s.evidence+'/browser-errors.json',JSON.stringify(errors,null,2));};
const proxy=http.createServer((req,res)=>{res.writeHead(403);res.end();});
proxy.on('connect',(req,client,head)=>{
 client.on('error',()=>client.destroy());
 if(req.url!==new URL(s.source).host){client.end('HTTP/1.1 403 Forbidden\r\n\r\n');return;}
 const up=net.connect(s.port,'127.0.0.1',()=>{client.write('HTTP/1.1 200 Connection Established\r\n\r\n');if(head.length)up.write(head);client.pipe(up);up.pipe(client);});
 for(const socket of [client,up]){sockets.add(socket);socket.on('close',()=>sockets.delete(socket));}
 up.on('error',()=>client.destroy());client.on('close',()=>up.destroy());
});
await new Promise(r=>proxy.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,proxy:{server:`http://127.0.0.1:${proxy.address().port}`},args:['--no-sandbox','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',`--ignore-certificate-errors-spki-list=${s.spki}`]});
try{
 for(const width of [1440,393]){
  const context=await browser.newContext({viewport:{width,height:width===393?852:1000},deviceScaleFactor:2});
  await context.addCookies([{name:'stella_at',value:s.token,url:s.source,secure:true,httpOnly:true,sameSite:'Strict'}]);
  const page=await context.newPage();page.setDefaultTimeout(15000);
  page.on('pageerror',e=>errors.push({type:'pageerror',message:e.message}));
  page.on('console',m=>{if(m.type()==='error')errors.push({type:'console',message:m.text().slice(0,500)});});
  page.on('request',r=>traffic.push({method:r.method(),path:new URL(r.url()).pathname,query:new URL(r.url()).search}));
  await page.goto(s.source+'/notes?doc='+s.doc);
  await page.locator('.preview h1').filter({hasText:'F02普通笔记'}).waitFor();
  await page.getByRole('button',{name:'更多',exact:true}).click();
  const count=await page.getByRole('button',{name:'关联时间线',exact:true}).count();
  results.views.push({width,timelineMenuCount:count});save();
  await page.screenshot({path:s.evidence+`/${width}-more.png`,fullPage:true});
  assert.equal(count,0,'ordinary Notes must not re-add unrelated operational timeline');
  for(const label of ['文档信息与标签','大纲','文内查找','版本历史','设为星标','导出'])assert.equal(await page.locator('#note-more-menu').getByRole('button',{name:label,exact:true}).count(),1,label+' retained');
  await page.getByRole('button',{name:'版本历史',exact:true}).click();
  const history=page.getByRole('dialog',{name:'版本历史'});await history.waitFor();
  await history.getByRole('button',{name:'查看差异 v1',exact:true}).click();
  await page.locator('.version-diff').filter({hasText:'F02旧版本保留'}).waitFor();
  assert.equal(await page.getByRole('dialog',{name:'关联时间线'}).count(),0);
  await page.screenshot({path:s.evidence+`/${width}-history.png`,fullPage:true});
  await history.getByRole('button',{name:'关闭版本历史'}).click();
  await page.getByRole('button',{name:'更多',exact:true}).click();
  await page.getByRole('button',{name:'文档信息与标签',exact:true}).click();
  await page.getByRole('dialog',{name:'文档信息',exact:true}).waitFor();
  await page.keyboard.press('Escape');
  await page.reload();await page.locator('.preview h1').filter({hasText:'F02普通笔记'}).waitFor();
  assert.equal(await page.getByRole('dialog',{name:'关联时间线'}).count(),0);
  assert.deepEqual(traffic.filter(r=>r.path==='/timeline'||r.path.endsWith('/node')),[],'no timeline/association reads or writes from ordinary notes');
  assert.deepEqual(traffic.filter(r=>r.method==='POST'&&r.path.includes('/tasks')),[]);
  results.views.at(-1).historyAndInfoRetained=true;save();
  await context.close();
 }
 assert.deepEqual(errors.filter(e=>e.type==='pageerror'),[]);results.passed=true;save();
}catch(e){results.failure=e.stack;save();throw e;}
finally{await browser.close();for(const socket of sockets)socket.destroy();await new Promise(r=>proxy.close(r));}
