import assert from 'node:assert/strict';
import http from 'node:http';
import {resolveConfig,createServer} from 'vite';
const config=await resolveConfig({},'serve');
const paths=['/notes-preferences','/documents/delete-preview'];
for(const path of paths){const key=Object.keys(config.server.proxy).find(k=>path.startsWith(k));assert.ok(key,`proxy missing: ${path}`);assert.equal(config.server.proxy[key].target,'http://127.0.0.1:12031');}
const received=[];
const stub=http.createServer(async(req,res)=>{let body='';for await(const chunk of req)body+=chunk;received.push({path:req.url,method:req.method,body});res.setHeader('content-type','application/json');res.end(JSON.stringify({fixture:true}));});
await new Promise(r=>stub.listen(0,'127.0.0.1',r));
const target=`http://127.0.0.1:${stub.address().port}`;
// Every configured proxy is redirected to this disposable local stub. Never hit 12031.
const proxy=Object.fromEntries(Object.keys(config.server.proxy).map(key=>[key,{target,xfwd:true}]));
const server=await createServer({server:{host:'127.0.0.1',port:0,strictPort:true,proxy}});
try{
 await server.listen();const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 for(const [method,path,body] of [['GET','/notes-preferences',undefined],['PATCH','/notes-preferences','{"expected_revision":0}'],['POST','/documents/delete-preview','{"mode":"trash"}']]){
  const r=await fetch(origin+path,{method,body,headers:{'content-type':'application/json'}});assert.equal(r.status,200);assert.deepEqual(await r.json(),{fixture:true});
 }
 assert.deepEqual(received.map(r=>[r.method,r.path]),[['GET','/notes-preferences'],['PATCH','/notes-preferences'],['POST','/documents/delete-preview']]);
 assert.equal(received[1].body,'{"expected_revision":0}');assert.equal(received[2].body,'{"mode":"trash"}');console.log('PASS actual Vite development GET/PATCH preferences and POST delete-preview',received);
}finally{await server.close();await new Promise(r=>stub.close(r));}
