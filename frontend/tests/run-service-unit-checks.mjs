// Run all distinct unit configs and every Node leaf-test file, in a clean environment.
import {readdirSync,readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const out=resolve(process.env.STELLA_SERVICE_ARTIFACTS||'test-results/service-unit');mkdirSync(out,{recursive:true});
const env={HOME:process.env.HOME,PATH:process.env.PATH,TMPDIR:out,NODE_ENV:'development'};
const commands=[];
function run(name,args){
 const command=[process.execPath,...args];const result=spawnSync(command[0],command.slice(1),{cwd:process.cwd(),env,encoding:'utf8',timeout:240000,maxBuffer:24*1024*1024});
 writeFileSync(out+'/'+name+'.log',result.stdout+'\n'+result.stderr);commands.push({name,command,exitCode:result.status,error:result.error?.message});writeFileSync(out+'/commands.json',JSON.stringify(commands,null,2));
 console.log(name+': exit '+result.status+(result.error?' '+result.error.message:''));return result;
}
for(const config of readdirSync('.').filter(p=>/^vitest.*\.config\.(ts|mjs)$/.test(p)).sort())run(config,['node_modules/vitest/vitest.mjs','run','--config',config,'--reporter=json','--outputFile='+out+'/'+config+'.json']);
const files=[];
function walk(dir){for(const entry of readdirSync(dir,{withFileTypes:true})){const path=dir+'/'+entry.name;if(entry.isDirectory())walk(path);else if(/\.test\.(mjs|ts)$/.test(path)&&readFileSync(path,'utf8').includes('node:test'))files.push(path);}}
walk('tests');walk('src');files.sort();
writeFileSync(out+'/node-files.json',JSON.stringify(files,null,2));
run('node',['--experimental-strip-types','--test','--test-concurrency=1','--test-reporter=tap',...files]);
run('build',['node_modules/vue-tsc/bin/vue-tsc.js','-b']);
run('bundle',['node_modules/vite/bin/vite.js','build']);
process.exitCode=commands.some(x=>x.exitCode!==0)?1:0;
