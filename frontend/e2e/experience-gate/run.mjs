// The supported acceptance command deliberately takes no grep/skip/retry flags.
import {spawnSync,execFileSync} from 'node:child_process';
import {mkdirSync,rmSync} from 'node:fs';
import path from 'node:path';
if(process.argv.length!==2)throw new Error('test:experience runs the complete mandatory set; no selection flags');
const output=path.resolve(process.env.STELLA_QA_OUTPUT||'node_modules/.cache/experience');
process.env.STELLA_QA_OUTPUT=output;
mkdirSync(output,{recursive:true});for(const name of ['receipt.json','results.json'])rmSync(path.join(output,name),{force:true});
const root=path.resolve('..');const commit=execFileSync('git',['-C',process.env.STELLA_SOURCE_ROOT||root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
if(process.env.CI_COMMIT_SHA&&process.env.CI_COMMIT_SHA!==commit)throw new Error('CI checkout/source does not match CI_COMMIT_SHA');
const run=(cmd,args)=>{const p=spawnSync(cmd,args,{stdio:'inherit',env:process.env});if(p.status!==0)process.exit(p.status||1);};
run('python3',['../deploy/experience-gates/test_gate.py']);
run(process.execPath,['node_modules/@playwright/test/cli.js','test','--config','playwright.experience.config.ts']);
run('python3',['../deploy/experience-gates/check_receipt.py','--receipt',path.join(output,'receipt.json'),'--commit',commit,'--kind','synthetic-process']);
console.log('Verified full experience receipt: '+path.join(output,'receipt.json'));
