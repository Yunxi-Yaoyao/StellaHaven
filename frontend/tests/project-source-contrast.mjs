// Actual Vue component in isolated Vite, no API/PG or production access.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=process.cwd(),out=process.env.SOURCE_CONTRAST_EVIDENCE;
assert(out?.startsWith('/opt/hermes-workstation/docs/'));
await mkdir(out,{recursive:true});
const component=path.join(root,'src/modules/notes/ProjectSourceEditor.vue');
const hash=()=>readFile(component).then(b=>createHash('sha256').update(b).digest('hex'));
const before=await hash();
const samples={
 'app.js':'// 注释与数字\nimport { value } from "./lib.js";\nconst answer = true;\nfunction calculate(input) { return input + 42; }\nconsole.log(calculate(2));',
 'index.html':'<!doctype html>\n<!-- 注释 -->\n<html><body><h1 class="title">数学复习册</h1><input disabled value="A" /></body></html>',
 'style.css':'/* 注释 */\n.title { color: #abcdef; margin: 12px; font-family: sans-serif; }',
 'note.md':'# 标题\n正文 **强调** 和 *斜体*。\n> 引用\n[链接](https://example.test)\n`code`\n- 列表',
};
const server=await createServer({configFile:false,root,cacheDir:path.join(out,'vite-cache'),plugins:[vue(),{name:'isolated-editor',configureServer(s){s.middlewares.use((req,res,next)=>{if(req.url?.startsWith('/contrast')){res.setHeader('Content-Type','text/html');res.end('<div id="app"></div><script type="module" src="/@contrast-entry"></script>');return;}next();});},resolveId(id){if(id==='/@contrast-entry')return '\0contrast-entry';},load(id){if(id==='\0contrast-entry')return `import {createApp,h} from 'vue';import Editor from '/src/modules/notes/ProjectSourceEditor.vue';import '/src/style.css';const samples=${JSON.stringify(samples)};document.documentElement.style.setProperty('--bg-base','#111216');document.documentElement.style.setProperty('--bg-panel','#191a20');document.documentElement.style.setProperty('--text-hi','#e8e5ec');document.documentElement.style.setProperty('--text-faint','#a6a3b0');document.documentElement.style.setProperty('--font-mono','ui-monospace,monospace');document.body.style.margin='0';document.querySelector('#app').style.height='100vh';const filename=new URLSearchParams(location.search).get('file')||'app.js';createApp({render:()=>h(Editor,{modelValue:samples[filename],filename})}).mount('#app');`;}}],server:{host:'127.0.0.1',port:0,proxy:{}},logLevel:'error'});
let browser;const results=[],errors=[];
try{
 await server.listen();const port=server.httpServer.address().port;
 browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1100,height:520},deviceScaleFactor:2});
 await context.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
 const page=await context.newPage();page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 for(const file of Object.keys(samples)){
  await page.goto(`http://127.0.0.1:${port}/contrast?file=${encodeURIComponent(file)}`);
  await page.waitForFunction(()=>document.querySelectorAll('.cm-content span[class]').length>1);
  const colors=await page.evaluate(()=>({bg:getComputedStyle(document.querySelector('.cm-editor')).backgroundColor,items:[...document.querySelectorAll('.cm-content span[class]')].filter(n=>n.textContent.trim()).map(n=>({text:n.textContent,color:getComputedStyle(n).color}))}));
  function lum(rgb){const c=rgb.match(/\d+/g).slice(0,3).map(Number).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;});return c.reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);}
  const bg=lum(colors.bg);for(const item of colors.items){const l=lum(item.color);item.ratio=(Math.max(l,bg)+.05)/(Math.min(l,bg)+.05);}
  results.push({file,...colors});await page.screenshot({path:path.join(out,file+'.png')});
 }
 await writeFile(path.join(out,'results.json'),JSON.stringify({source_sha256:before,results,errors},null,2));
 assert.equal(await hash(),before,'source changed during verification');assert.deepEqual(errors,[]);
 const low=results.flatMap(r=>r.items.filter(x=>x.ratio<4.5).map(x=>({file:r.file,...x})));
 assert.deepEqual(low,[],'syntax contrast below4.5');
 console.log(JSON.stringify({files:results.length,minimum:Math.min(...results.flatMap(r=>r.items.map(x=>x.ratio))),source_sha256:before,output:out}));
}finally{await browser?.close();await server.close();}
