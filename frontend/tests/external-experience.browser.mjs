// Owned Vue + exported child snapshot; all non-loopback traffic intercepted.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
const output=process.env.STELLA_QA_OUTPUT||path.resolve('node_modules/.cache/external-456');mkdirSync(output,{recursive:true});
const cache=mkdtempSync(path.join(process.env.TMPDIR||tmpdir(),'external-vite-'));
const parents=['https://main.example','https://main.p.example'];
const child='https://drive.example';
const env={PATH:process.env.PATH,PYTHONPATH:path.resolve('..'),STELLA_SECRET_KEY:'synthetic-key-only-45620',POSTGRES_HOST:'127.0.0.1',POSTGRES_PORT:'1',STELLA_ENTRY_REGISTRY:JSON.stringify([{service_id:'stella',public:parents[0],private:parents[1]}])};
const snapshot=JSON.parse(execFileSync(process.env.STELLA_TEST_PYTHON||'/opt/hermes-workstation/stella-preview-20261018/.venv/bin/python',['-c',`import json;from app.services.website_templates import export_code;print(json.dumps(export_code('drive',main_origin='https://main.example')))`],{env,encoding:'utf8'}));
// Pure background fragment still comes from the actual exported editable snapshot.
const start=snapshot.js.indexOf('/* stella:background-ready:v1 */');const bridge=snapshot.js.slice(start,snapshot.js.indexOf('\n})();',start)+6);
const html=`<!doctype html><html style="color-scheme:dark"><head><meta name="color-scheme" content="dark"><style>html,body,#app{margin:0;width:100%;height:100%;background:#17191f;color:#e8e8ed;font-family:system-ui}#app{--bg-base:#17191f;--bg-panel:#25272e;--text-hi:#e8e8ed;--text-lo:#b6b6c1}</style></head><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue';
import Page from '/src/shell/ExternalModulePage.vue';import {auth} from '/src/modules/home/auth.ts';import {navigation} from '/src/stores/navigation.ts';
Object.assign(auth,{me:{id:'fixture-owner',home_bg:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="8" height="8"%3E%3Cpath fill="%23246e59" d="M0 0h8v8H0z"/%3E%3C/svg%3E'},sessionGeneration:1,sessionClosing:false});
navigation.loaded=true;navigation.modules=[{id:'fixture',name:'网盘',icon:'drive',enabled:true,mode:'iframe',browser_url:'${child}/',origin:'${child}',background:'home',injection:{active:{enabled:true,js:'/* stella:background-ready:v1 */'}}}];
window.fixture=createApp({render:()=>h(Page,{id:'fixture'})});window.fixture.component('RouterLink',{render(){return null}});window.fixture.mount('#app');
</script></body></html>`;
const server=await createServer({configFile:false,plugins:[vue(),{name:'owned-fixture',configureServer(s){s.middlewares.use(async(req,res,next)=>{if(req.url!=='/')return next();res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml('/',html));});}}],root:process.cwd(),cacheDir:cache,appType:'custom',optimizeDeps:{entries:[],include:['vue']},server:{host:'127.0.0.1',port:0},logLevel:'error'});
let browser;const receipts=[];
try{
 await server.listen();const local=server.resolvedUrls.local[0].replace(/\/$/,'');browser=await chromium.launch({executablePath:process.env.CHROME_BIN,args:['--no-sandbox']});
 for(const parent of parents)for(const viewport of [{width:1280,height:800},{width:390,height:844}]){
  const target=parent===parents[0]?child:'https://drive.p.example';
  const context=await browser.newContext({viewport,reducedMotion:'reduce'});const page=await context.newPage();const unknown=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
  let release;const gate=new Promise(done=>release=done);
  await page.route('**/*',async route=>{const u=new URL(route.request().url());
   if(u.origin===parent){
    if(u.pathname==='/website-settings/check')return route.fulfill({json:{embedding:{status:'allowed'}}});
    if(u.pathname==='/external-modules/fixture/launch'){await gate;return route.fulfill({json:{mode:'iframe',method:'GET',url:target+'/',target_origin:target}});}
    if(u.pathname==='/'||u.pathname.startsWith('/src/')||u.pathname.startsWith('/node_modules/')||u.pathname.startsWith('/@'))return route.fulfill({response:await route.fetch({url:local+u.pathname+u.search})});
   }
   if(u.origin===target)return route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta name="color-scheme" content="light dark"></head><body style="background:#fff"><div id="root"><h1 style="color:#fff;padding:24px">目录 fixture</h1></div><script>${bridge}</script></body></html>`});
   unknown.push(u.href);return route.abort();
  });
  await page.goto(parent);await page.waitForSelector('.external-loading--center');
  const centre=await page.locator('.external-loading--center').boundingBox();assert(centre);assert.equal(centre.width,viewport.width);assert.equal(centre.height,viewport.height);
  const activity=await page.locator('.activity').evaluate(el=>getComputedStyle(el).animationName);assert.equal(activity,'none');
  await page.screenshot({path:path.join(output,`${parent===parents[0]?'public':'private'}-${viewport.width}-loading.png`)});
  release();await page.waitForSelector('iframe');await page.waitForFunction(()=>getComputedStyle(document.querySelector('iframe')).visibility==='visible');await page.waitForSelector('.external-loading',{state:'detached'});
  const frame=page.frames().find(f=>f.url().startsWith(target));assert(frame);assert.equal(await frame.locator('meta[name=color-scheme]').getAttribute('content'),'dark');
  assert.equal(await frame.locator('html').evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
  await page.screenshot({path:path.join(output,`${parent===parents[0]?'public':'private'}-${viewport.width}-ready.png`)});
  assert.deepEqual(unknown,[]);assert.deepEqual(errors,[]);receipts.push({parent,target,viewport,activity,canvasScheme:'dark',frameVisible:true,unknown,errors});await context.close();
 }
 writeFileSync(path.join(output,'browser-receipt.json'),JSON.stringify(receipts,null,2));console.log(JSON.stringify(receipts,null,2));
}finally{await browser?.close();await server.close();rmSync(cache,{recursive:true,force:true});}
