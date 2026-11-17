// Component-only fixture. Full App integration belongs to the Overview owner.
import {createRequire} from 'node:module';
import {writeFile,mkdir} from 'node:fs/promises';
const require=createRequire('/opt/Yunxi-workstation/Stella/frontend/package.json');
const {createServer}=await import('/opt/Yunxi-workstation/Stella/frontend/node_modules/vite/dist/node/index.js');
const {default:vue}=await import('/opt/Yunxi-workstation/Stella/frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs');
const {chromium}=require('playwright');
const root='/opt/hermes-workstation/worktrees/stella/v8-monitor-management/frontend';
const out='/opt/hermes-workstation/worktrees/stella/v8-monitor-management/docs/v8-management/screenshots-final';await mkdir(out,{recursive:true});
const server=await createServer({configFile:false,root,envDir:false,appType:'custom',cacheDir:'/root/.hermes/cache/scratch/monitor-management-v8/browser-cache',optimizeDeps:{noDiscovery:true,include:[]},server:{host:'127.0.0.1',port:0,fs:{allow:[root,'/opt/Yunxi-workstation/Stella/frontend']}},plugins:[{name:'shared-read-only',enforce:'pre',resolveId(id){if(id.startsWith('@vue/'))return '/opt/Yunxi-workstation/Stella/frontend/node_modules/'+id+'/dist/'+id.split('/')[1]+'.esm-bundler.js';if(id==='vue')return '/opt/Yunxi-workstation/Stella/frontend/node_modules/vue/dist/vue.runtime.esm-bundler.js';if(!id.startsWith('.')&&!id.startsWith('/')&&!id.startsWith('\0'))try{return require.resolve(id)}catch{}}},vue(),{name:'fixture',configureServer(s){s.middlewares.use('/__v8fixture',(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(`<html><body style="margin:0;background:#111521;color:#eee;font-family:system-ui"><div id="app"></div><script type="module">import {createApp,h} from '/@fs/opt/Yunxi-workstation/Stella/frontend/node_modules/vue/dist/vue.runtime.esm-bundler.js';import Management from '/src/modules/servers/MonitorManagement.vue';createApp({render:()=>h(Management,{open:true,nodes:[{id:1,name:'隔离探测源'}]})}).mount('#app');</script></body></html>`);});}}]});
let browser;
try{
 await server.listen();const address=server.httpServer.address();const origin=`http://127.0.0.1:${address.port}`;
 browser=await chromium.launch({headless:true});const page=await browser.newPage();
 const items=[{id:7,name:'外部网站可达性',node_id:1,type:'ping',target:'owned.example',interval:60,timeout:5,status:'down',status_reason:'failure',visible:false,enabled:true,effective_enabled:true},{id:8,name:'保留的独立监控',node_id:1,type:'tcp',target:'owned.example:443',interval:60,timeout:5,status:'down',visible:false,enabled:false,effective_enabled:false}];
 const groups=[{id:3,name:'入口监控组',child_ids:[7],eligible_child_ids:[],status:'down',down_count:0,up_count:0,unknown_count:0,failure_policy:'any',rotation_seconds:0,visible:true,enabled:true}];
 let writes=0;const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)});
 await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(url.origin!==origin)return route.abort();const path=url.pathname,method=req.method();let body;
 if(path==='/monitors/'&&method==='GET')body=items;
 else if(path==='/monitors/groups'&&method==='GET')body=groups;
 else if(path==='/monitors/7'&&method==='PATCH'){Object.assign(items[0],req.postDataJSON());groups[0].eligible_child_ids=items[0].visible?[7]:[];groups[0].down_count=items[0].visible?1:0;writes++;body=items[0];}
 else if(path==='/monitors/7/checks'&&method==='GET')body=[{id:1,monitor_id:7,ts:'2026-10-20T00:00:00Z',success:false,latency_ms:null,loss_pct:100},{id:2,monitor_id:7,ts:'2026-10-19T00:00:00Z',success:true,latency_ms:3,loss_pct:0}];
 else if(path.startsWith('/monitors'))throw new Error(`Unexpected ${method} ${path}`);
 else return route.continue();
 return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(origin+'/__v8fixture');await page.getByText('无参与项',{exact:false}).waitFor();
 await page.getByRole('button',{name:'显示',exact:true}).first().click();await page.getByRole('button',{name:'隐藏',exact:true}).waitFor();if(writes!==1)throw Error('toggle was not applied exactly once');
 await page.getByRole('button',{name:'历史',exact:true}).first().click();await page.getByLabel('历史结果筛选').selectOption('down');await page.getByText('最近 200 条原始采样',{exact:false}).waitFor();
 for(const width of [1365,390,320]){await page.setViewportSize({width,height:900});await page.screenshot({path:`${out}/${width}.png`,fullPage:true});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error(`overflow ${width}`);}
 if(errors.length)throw Error(errors.join('\n'));await writeFile(out+'/result.json',JSON.stringify({component_only:true,viewports:[1365,390,320],writes,errors},null,2));console.log(JSON.stringify({component_only:true,viewports:[1365,390,320],writes,errors}));
}finally{await browser?.close();await server.close();}
