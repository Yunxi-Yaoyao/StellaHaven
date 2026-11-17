import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp, mkdir, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import test from 'node:test';

const runner=await readFile(new URL('../e2e/documentation/run.mjs',import.meta.url),'utf8');
const url='http://127.0.0.1:15591/help';
async function fixture(mode){
 const root=await mkdtemp(path.join(tmpdir(),'documentation-startup-'));
 await mkdir(path.join(root,'node_modules/vite/bin'),{recursive:true});
 await mkdir(path.join(root,'e2e/documentation'),{recursive:true});
 await writeFile(path.join(root,'e2e/documentation/run.mjs'),runner);
 await writeFile(path.join(root,'e2e/documentation/acceptance.mjs'),`console.log('BROWSER_ACCEPTANCE_REACHED');`);
 await writeFile(path.join(root,'node_modules/vite/bin/vite.js'),`
 const http=require('node:http');
 const fs=require('node:fs');
 fs.writeFileSync('server.pid',String(process.pid));
 const mode=${JSON.stringify(mode)};
 const server=http.createServer((req,res)=>{
  if(mode==='hang')return;
  if(mode==='exit-inflight')process.exit(23);
  if(mode==='503')res.statusCode=503;
  res.end('owned built fixture');
 });
 if(mode==='exit'){console.error('owned fixture startup failure');process.exit(23);}
 server.listen(15591,'127.0.0.1',()=>{
  if(mode==='no-url'){process.stdout.write('fixture is running without a Vite URL\\n');return;}
  if(mode==='plain'){process.stdout.write('http://127.0.0.1:15591/\\n');return;}
  const text='  Local: \\x1b[36mhttp://127.0.0.1:\\x1b[1m15591\\x1b[22m/\\x1b[39m\\n';
  if(mode==='split'){
   const chunks=[text.slice(0,7),text.slice(7,30),text.slice(30,33),text.slice(33)];
   chunks.forEach((chunk,i)=>setTimeout(()=>process.stdout.write(chunk),i*40));
  }else process.stdout.write(text);
 });
 `);
 const env={...process.env,STELLA_DOC_SKIP_BUILD:'1',STELLA_DOC_OUTPUT:path.join(root,'output')};
 delete env.NODE_OPTIONS;delete env.NODE_ENV;
 const started=performance.now();
 const child=spawn(process.execPath,['e2e/documentation/run.mjs'],{cwd:root,env,stdio:['ignore','pipe','pipe']});
 let output='';child.stdout.on('data',chunk=>output+=chunk);child.stderr.on('data',chunk=>output+=chunk);
 const timer=setTimeout(()=>child.kill('SIGKILL'),13000);
 try{
  const [code,signal]=await once(child,'exit');
  // The runner owns and must reap its server before returning.
  await assert.rejects(fetch(url,{signal:AbortSignal.timeout(500)}));
  const pid=Number(await readFile(path.join(root,'server.pid'),'utf8'));
  assert.throws(()=>process.kill(pid,0),{code:'ESRCH'},'fixture server must be reaped');
  return {code,signal,output,elapsed:performance.now()-started};
 }finally{
  clearTimeout(timer);
  try{process.kill(Number(await readFile(path.join(root,'server.pid'),'utf8')),'SIGKILL');}catch{}
  await rm(root,{recursive:true,force:true});
 }
}
test('ANSI inside the URL must not hide a ready HTTP fixture',async()=>{
 const result=await fixture('ansi');
 assert.equal(result.code,0,result.output);
 assert.match(result.output,/BROWSER_ACCEPTANCE_REACHED/);
 assert.ok(result.elapsed<3000,`readiness should not consume its 10s deadline: ${result.elapsed}`);
});
test('negative control: a listening server that never answers HTTP fails within the original 10s budget',async()=>{
 const result=await fixture('hang');
 assert.equal(result.code,1,result.output);
 assert.match(result.output,/Documentation fixture did not become ready/);
 assert.doesNotMatch(result.output,/BROWSER_ACCEPTANCE_REACHED/);
 assert.ok(result.elapsed>=9900&&result.elapsed<11500,`deadline elapsed: ${result.elapsed}`);
});
for(const mode of ['plain','split'])test(`${mode} stdout URL also admits HTTP readiness`,async()=>{
 const result=await fixture(mode);
 assert.equal(result.code,0,result.output);
 assert.match(result.output,/BROWSER_ACCEPTANCE_REACHED/);
 assert.ok(result.elapsed<3000);
});
for(const mode of ['exit','exit-inflight'])test(`negative control: ${mode} fails early with its exit status and reaps the child`,async()=>{
 const result=await fixture(mode);
 assert.equal(result.code,1,result.output);
 assert.match(result.output,/server exited before readiness: 23/);
 assert.doesNotMatch(result.output,/BROWSER_ACCEPTANCE_REACHED/);
 assert.ok(result.elapsed<3000);
});
for(const mode of ['503','no-url'])test(`negative control: ${mode} cannot satisfy both readiness gates`,async()=>{
 const result=await fixture(mode);
 assert.equal(result.code,1,result.output);
 assert.match(result.output,mode==='503'?/listening=true; HTTP=status 503/:/listening=false; HTTP=not attempted/);
 assert.doesNotMatch(result.output,/BROWSER_ACCEPTANCE_REACHED/);
 assert.ok(result.elapsed>=9900&&result.elapsed<11500);
});
