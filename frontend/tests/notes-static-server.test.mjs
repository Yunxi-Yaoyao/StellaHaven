import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';

test('static production server cannot proxy or silently serve API requests as HTML',async()=>{
 const child=spawn(process.execPath,['e2e/notes-refresh-server.mjs'],{cwd:new URL('..',import.meta.url),env:{...process.env,NOTES_REFRESH_PORT:'0'},stdio:['ignore','pipe','pipe']});
 try{
  const output=await new Promise((resolve,reject)=>{
   let text='';const timer=setTimeout(()=>reject(new Error('static server readiness timeout')),5000);
   child.once('error',error=>{clearTimeout(timer);reject(error);});
   child.once('exit',code=>{clearTimeout(timer);reject(new Error('static server exited '+code));});
   child.stdout.on('data',data=>{text+=data;const match=text.match(/loopback (\d+); no proxy/);if(match){clearTimeout(timer);resolve(match[1]);}});
  });
  const origin='http://127.0.0.1:'+output;
  const app=await fetch(origin+'/notes');assert.equal(app.status,200);assert.match(await app.text(),/\/static\/.*\.js/);
  for(const [method,path] of [['GET','/documents/'],['GET','/auth/me'],['GET','/unknown'],['POST','/notes']]){
   const response=await fetch(origin+path,{method});assert.equal(response.status,404);assert.deepEqual(await response.json(),{detail:'No static fixture route'});
  }
 }finally{if(child.exitCode===null&&child.signalCode===null){const exited=once(child,'exit');child.kill('SIGTERM');await exited;}}
});
