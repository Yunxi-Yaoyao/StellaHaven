// Supported isolated owning acceptance. Never proxies to a backend.
import {spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {stripVTControlCharacters} from 'node:util';
const env={...process.env};delete env.NODE_ENV;
env.STELLA_DOC_OUTPUT=path.resolve(env.STELLA_DOC_OUTPUT||mkdtempSync(path.join(tmpdir(),'stella-doc-center-')));mkdirSync(env.STELLA_DOC_OUTPUT,{recursive:true});
const run=(args)=>new Promise((resolve,reject)=>{const child=spawn(process.execPath,args,{env,stdio:'inherit'});child.once('error',reject);child.once('exit',(code,signal)=>code===0?resolve():reject(Error(`Command failed (${code??signal}): ${args.join(' ')}`)));});
if(env.STELLA_DOC_SKIP_BUILD!=='1')await run(['node_modules/vue-tsc/bin/vue-tsc.js','-b']).then(()=>run(['node_modules/vite/bin/vite.js','build']));
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--config','vite.documentation.config.ts'],{env,stdio:['ignore','pipe','pipe']});
// Vite styles the port even on CI pipes; a stream chunk need not contain a whole URL.
let listening=false,stdout='',stderr='';server.stdout.on('data',chunk=>{process.stdout.write(chunk);stdout=(stdout+String(chunk)).slice(-8192);if(stripVTControlCharacters(stdout).includes('http://127.0.0.1:15591/'))listening=true;});server.stderr.on('data',chunk=>{process.stderr.write(chunk);stderr=(stderr+String(chunk)).slice(-4096);});
let exited=false,exitDetail='';
const startup=new AbortController(),deadline=performance.now()+10000;
const timer=setTimeout(()=>startup.abort(Error('startup deadline reached')),10000);
server.once('error',error=>{exitDetail=error.message;startup.abort(error);});
server.once('exit',(code,signal)=>{exited=true;exitDetail=String(code??signal);startup.abort(Error('server exited: '+exitDetail));});
try{
 let ready=false,lastHTTP='not attempted',lastStatus;
 for(let i=0;i<100&&performance.now()<deadline;i++){
  if(exited||exitDetail)throw Error('Documentation fixture server exited before readiness: '+exitDetail);
  if(listening){
   try{
    const response=await fetch('http://127.0.0.1:15591/help',{signal:startup.signal,redirect:'error'});
    lastStatus=response.status;lastHTTP='status '+lastStatus;
    await response.body?.cancel();
    if(response.ok&&!exited&&!startup.signal.aborted&&performance.now()<deadline){ready=true;break;}
   }catch(error){lastHTTP=(lastStatus?'status '+lastStatus+'; ':'')+error.message;}
  }
  const remaining=deadline-performance.now();
  if(remaining>0)await new Promise(resolve=>setTimeout(resolve,Math.min(100,remaining)));
 }
 if(!ready)throw Error(`Documentation fixture did not become ready within 10000ms (listening=${listening}; HTTP=${lastHTTP}; exit=${exitDetail||'none'})\n${stripVTControlCharacters(stdout+stderr)}`);
 clearTimeout(timer);
 await run(['e2e/documentation/acceptance.mjs']);
 console.log('Documentation evidence: '+env.STELLA_DOC_OUTPUT);
}finally{
 clearTimeout(timer);
 if(!exited){const done=new Promise(resolve=>server.once('exit',resolve));server.kill('SIGTERM');await done;}
}
