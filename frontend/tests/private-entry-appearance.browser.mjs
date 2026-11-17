// Real candidate Vue + actual exported bridge; synthetic directory, never production.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
const output=process.env.STELLA_QA_OUTPUT;assert(output);mkdirSync(output,{recursive:true});
const cache=mkdtempSync(path.join(process.env.TMPDIR,'entry-vite-'));
const parents=['https://main.example','https://main.p.example'];
// Reuse the CI's fenced actual-source AST export: no full-app/config/database imports.
const exported=JSON.parse(execFileSync(process.env.STELLA_TEST_PYTHON||'python3',['../tools/experience-fixture/export_template.py',...parents],{encoding:'utf8'}));
const snapshot=exported.code;
const start=snapshot.js.indexOf('/* stella:background-ready:v1 */'),bridge=snapshot.js.slice(start,snapshot.js.indexOf('\n})();',start)+6);
const detail={id:'fixture',name:'网盘',icon:'drive',enabled:true,mode:'iframe',browser_url:'https://drive.example/',origin:'https://drive.example',background:'home',injection:{active:{enabled:true,js:snapshot.js}}};
const html=`<!doctype html><html style="color-scheme:dark"><head><meta charset="utf-8"><meta name="color-scheme" content="dark"><style>html,body,#app{margin:0;width:100%;height:100%;background:#17191f;color:white;font-family:system-ui}#app{--bg-panel:#25272e;--text-hi:white;--text-lo:#ccc}</style></head><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue';import Page from '/src/shell/ExternalModulePage.vue';import {auth} from '/src/modules/home/auth.ts';import {navigation} from '/src/stores/navigation.ts';
Object.assign(auth,{me:{id:'fixture-owner',home_bg:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="8" height="8"%3E%3Cpath fill="%23246e59" d="M0 0h8v8H0z"/%3E%3C/svg%3E'},sessionGeneration:1,sessionClosing:false});
navigation.loaded=true;navigation.modules=[${JSON.stringify(process.env.STELLA_BASELINE==='1'?detail:{...detail,injection:undefined})}];window.acks=[];window.addEventListener('message',e=>{if(e.data?.type==='stella-bg-ready')window.acks.push({origin:e.origin,data:e.data});});const app=createApp({render:()=>h(Page,{id:'fixture'})});app.component('RouterLink',{render(){return null}});app.mount('#app');</script></body></html>`;
const baseline=process.env.STELLA_BASELINE==='1';
const server=await createServer({configFile:false,root:process.cwd(),cacheDir:cache,appType:'custom',plugins:[{name:'baseline-source',enforce:'pre',load(id){if(baseline&&id===path.resolve('src/shell/ExternalModulePage.vue'))return execFileSync('git',['show','7af68e82c02acbb34e48da9b99b1b3696a472ba8:frontend/src/shell/ExternalModulePage.vue'],{encoding:'utf8'});}},vue(),{name:'fixture',configureServer(s){s.middlewares.use(async(req,res,next)=>{if(req.url!=='/')return next();res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await s.transformIndexHtml('/',html));});}}],optimizeDeps:{entries:[],include:['vue']},server:{host:'127.0.0.1',port:0},logLevel:'error'});
let browser;const receipts=[];
try{
 await server.listen();const local=server.resolvedUrls.local[0].replace(/\/$/,'');browser=await chromium.launch({executablePath:process.env.CHROME_BIN||process.env.STELLA_CHROMIUM||chromium.executablePath(),args:['--no-sandbox']});
 for(const parent of parents)for(const width of [1280,390])for(const scenario of ['no-ack','bridge']){
  const target=parent===parents[0]?'https://drive.example':'https://drive.p.example';
  const context=await browser.newContext({viewport:{width,height:800},reducedMotion:'reduce'});const page=await context.newPage(),unknown=[],errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.route('**/*',async route=>{const u=new URL(route.request().url());requests.push(u.pathname);
   if(u.origin===parent){
    if(u.pathname==='/@vite/client')return route.fulfill({contentType:'application/javascript',body:'export const createHotContext=()=>({accept(){},prune(){},dispose(){},on(){}});export const updateStyle=(id,content)=>{let el=document.querySelector(`style[data-id="${id}"]`);if(!el){el=document.createElement("style");el.dataset.id=id;document.head.append(el);}el.textContent=content;};export const removeStyle=()=>{};export const injectQuery=x=>x;'});
    if(u.pathname==='/external-modules/fixture')return route.fulfill({json:detail});
    if(u.pathname==='/external-modules/fixture/launch')return route.fulfill({json:{mode:'iframe',method:'GET',url:target+'/',source_origin:parent,target_origin:target}});
    // Baseline still probes; return immediately so the visibility oracle isolates the reported defect.
    if(u.pathname==='/website-settings/check')return route.fulfill({json:{embedding:{status:'allowed'}}});
    if(u.pathname==='/'||u.pathname.startsWith('/src/')||u.pathname.startsWith('/node_modules/')||u.pathname.startsWith('/@'))return route.fulfill({response:await route.fetch({url:local+u.pathname+u.search})});
   }
   if(u.origin===target)return route.fulfill({contentType:'text/html; charset=utf-8',body:`<!doctype html><html><head><meta name="color-scheme" content="light dark"><style>html,body,#root{margin:0;height:100%;background:#fff}h1{margin:0;padding:24px;color:#fff;background:#345}</style></head><body><div id="root"><h1>目录 fixture</h1><button id="folder">打开目录</button><p id="listing">3 items</p></div><script>document.querySelector('#folder').onclick=()=>document.querySelector('#listing').textContent='nested directory';</script>${scenario==='bridge'?`<script>${bridge}</script>`:''}</body></html>`});
   unknown.push(u.href);return route.abort();
  });
  await page.goto(parent);await page.waitForSelector('iframe',{state:'attached'});const frame=await page.waitForEvent('framenavigated',{predicate:f=>f.url()===target+'/',timeout:1000}).catch(()=>page.frames().find(f=>f.url()===target+'/'));assert(frame);
  await frame.locator('#listing').waitFor();const visibility=await page.locator('iframe').evaluate(el=>getComputedStyle(el).visibility);
  assert.equal(visibility,'visible','loaded directory must not wait for a style ACK');
  await frame.locator('#folder').click();assert.equal(await frame.locator('#listing').textContent(),'nested directory');
  await page.waitForSelector('.external-loading',{state:'detached'});
  if(scenario==='bridge'){await page.waitForFunction(()=>window.acks.length>0);assert.equal(await frame.locator('html').evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');assert.equal(await frame.locator('meta[name=color-scheme]').getAttribute('content'),'dark');}
  const filename=`${parent===parents[0]?'public':'private'}-${width}-${scenario}.png`;await page.screenshot({path:path.join(output,filename)});
  assert.deepEqual(unknown,[]);assert.deepEqual(errors,[]);if(!baseline)assert(!requests.includes('/website-settings/check'));
  receipts.push({parent,target,width,scenario,visibility,content:'nested directory',acks:await page.evaluate(()=>window.acks),requests,unknown,errors,screenshot:filename});await context.close();
 }
 const sha=p=>createHash('sha256').update(readFileSync(p)).digest('hex');
 writeFileSync(path.join(output,'receipt.json'),JSON.stringify({baseline,commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),sources:{component:sha('src/shell/ExternalModulePage.vue'),bridge:createHash('sha256').update(bridge).digest('hex')},receipts},null,2));console.log(JSON.stringify({cases:receipts.length,baseline,errors:receipts.flatMap(r=>r.errors)}));
}finally{await browser?.close();await server.close();rmSync(cache,{recursive:true,force:true});}
