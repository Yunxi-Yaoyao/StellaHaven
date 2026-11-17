// Exercise the exact installed HTTP handler, not a copied preference responder.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

test('shell HTTP preference fixture rejects complete unknown query targets without exposing or mutating DTO',async()=>{
 const sourcePath=new URL('./shell-perf-browser.mjs',import.meta.url);
 const source=await fs.readFile(sourcePath,'utf8');
 const marker='async function graph(dir) {';
 assert.equal(source.split(marker).length,2,'unique original handler extraction boundary');
 let moduleSource=source.slice(0,source.indexOf(marker));
 const root=new URL('../',import.meta.url).pathname;
 moduleSource=moduleSource.replace("import { chromium } from '@playwright/test';",'')
  .replace("from 'vite';",'from '+JSON.stringify(import.meta.resolve('vite'))+';')
  .replace("const [beforeDir, afterDir, outDir] = process.argv.slice(2);",'')
  .replace("assert(beforeDir && afterDir && outDir, 'usage: node tests/shell-perf-browser.mjs before-dist after-dist report-dir');",'')
  .replace('await fs.mkdir(outDir, { recursive: true });','')
  .replace("root:new URL('../',import.meta.url).pathname",'root:'+JSON.stringify(root));
 const scratch=await fs.mkdtemp(path.join(tmpdir(),'shell-query-'));
 let service;
 try{
  const file=path.join(scratch,'original-handler.mjs');
  await fs.writeFile(file,moduleSource+'\nexport {serve};\n');
  const {serve}=await import(pathToFileURL(file).href);
  service=await serve(scratch,'shell-query-regression');
  const endpoint='/operations/backups/client-preferences';
  const request=async(target,method='GET',body)=>{
   const response=await fetch(service.origin+target,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
   return {status:response.status,dto:await response.json()};
  };
  const before=await request(endpoint);assert.equal(before.status,200);
  const {revision,...content}=before.dto;
  const put={...content,expected_revision:revision,ui:{...content.ui,listFold:!content.ui.listFold}};
  const rows=[];
  for(const query of ['?review_unknown=1','?alias=independent&review_unknown=2','?%72eview_unknown=%31','?review_unknown=1&review_unknown=2']){
   for(const method of ['GET','PUT'])rows.push({method,target:endpoint+query,response:await request(endpoint+query,method,method==='PUT'?put:undefined)});
  }
  const after=await request(endpoint);
  const evidence={sourceSHA256:createHash('sha256').update(source).digest('hex'),before,rows,after,unknown:service.unknown};
  if(process.env.SHELL_QUERY_EVIDENCE){await fs.mkdir(process.env.SHELL_QUERY_EVIDENCE,{recursive:true});await fs.writeFile(path.join(process.env.SHELL_QUERY_EVIDENCE,'requests.json'),JSON.stringify(evidence,null,2));}
  assert.deepEqual(after,before,'denials do not change saved DTO/revision');
  for(const row of rows){
   assert.equal(row.response.status,501,row.method+' '+row.target+' must be rejected');
   assert.equal(row.response.dto.revision,undefined,'unknown target cannot disclose owner DTO');
   assert(service.unknown.some(x=>x.method===row.method&&x.path===row.target),'complete query must reach original unknown gate');
  }
  assert.equal(service.unknown.length,rows.length,'no hidden unknown requests');
 }finally{
  if(service)await new Promise(resolve=>service.server.close(resolve));
  await fs.rm(scratch,{recursive:true,force:true});
 }
});
