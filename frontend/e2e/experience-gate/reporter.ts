import type {Reporter,FullConfig,Suite,FullResult} from '@playwright/test/reporter';
import {execFileSync,spawnSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
const harness=path.resolve(import.meta.dirname,'../../..');
const source=path.resolve(process.env.STELLA_SOURCE_ROOT||harness);
const output=path.resolve(process.env.STELLA_QA_OUTPUT||'node_modules/.cache/experience');
const git=(root:string,...args:string[])=>execFileSync('git',['-C',root,...args],{encoding:'utf8'}).trim();
const harnessFiles=['frontend/e2e/experience-independent-navigation.spec.ts','frontend/e2e/experience-independent-background.spec.ts',
 'frontend/e2e/experience-independent-harness.ts','tools/experience-fixture/export_template.py','tools/experience-fixture/sample_pixels.py',
 'frontend/experience-independent.vite.config.ts','frontend/playwright.experience-independent.config.ts',
 'frontend/e2e/experience-gate/reporter.ts','frontend/e2e/experience-gate/run.mjs','frontend/playwright.experience.config.ts',
 'frontend/package.json','deploy/experience-gates/check_receipt.py','deploy/experience-gates/contract.json'];
function revision(root:string){return git(root,'rev-parse','HEAD');}
function cleanHarness(){return harnessFiles.every(file=>{try{return readFileSync(path.join(harness,file),'utf8')===execFileSync('git',['-C',harness,'show','HEAD:'+file],{encoding:'utf8',stdio:['pipe','pipe','ignore']});}catch{return false;}});}
function cleanSource(){return !git(source,'status','--porcelain','--untracked-files=all','--','app','frontend/src','frontend/index.html');}
export default class ExperienceReporter implements Reporter {
 suite!:Suite; commit=''; harnessCommit=''; dirty=true; errors:string[]=[];
 onBegin(_config:FullConfig,suite:Suite){
  this.suite=suite;this.commit=revision(source);this.harnessCommit=revision(harness);
  this.dirty=!cleanHarness()||!cleanSource();
 }
 onError(error:any){this.errors.push(error.message||String(error));}
 onEnd(result:FullResult){
  const checks=(this.suite?.allTests()||[]).map(test=>{
   const last=test.results.at(-1);const trace=last?.attachments.find(a=>a.name==='trace')?.path;
   return {id:test.title,title:test.title,expected:test.expectedStatus,
    status:test.outcome()==='expected'&&last?.status==='passed'?'passed':test.outcome(),
    attempts:test.results.length,errors:test.results.flatMap(r=>r.errors.map(e=>e.message||String(e))),
    evidence:trace||'',evidence_sha256:trace?createHash('sha256').update(readFileSync(trace)).digest('hex'):null};
  });
  const receipt={schema:'stella-experience/v1',kind:'synthetic-process',commit:this.commit,harness_commit:this.harnessCommit,
   dirty:this.dirty||!cleanHarness()||!cleanSource()||revision(source)!==this.commit||revision(harness)!==this.harnessCommit,
   status:result.status,errors:this.errors,checks,scope:'controlled API latency/failure + actual App/Sidebar/router/store and AST-exported template; NOT production performance'};
  mkdirSync(output,{recursive:true});const file=path.join(output,'receipt.json');writeFileSync(file,JSON.stringify(receipt,null,2)+'\n');
  const check=spawnSync('python3',[path.join(harness,'deploy/experience-gates/check_receipt.py'),'--receipt',file,'--commit',this.commit,'--kind','synthetic-process'],{encoding:'utf8'});
  console.log(check.stdout||check.stderr);if(check.status!==0)return {status:'failed' as const};
 }
}
