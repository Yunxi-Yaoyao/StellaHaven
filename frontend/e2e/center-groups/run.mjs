// Isolated production-built actual server views. Network is fixture-only.
import {build} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const root=process.cwd(),out=resolve(root,'.cache/center-browser-build');
const evidence=resolve(root,'../docs/Stella-界面收敛第四轮-20261020/monitors');await mkdir(evidence,{recursive:true});
const entry=`import {createApp,h} from 'vue';import {createPinia} from 'pinia';import {createRouter,createWebHistory,RouterView} from 'vue-router';import '@fontsource-variable/inter';import '/src/style.css';import Page from '/src/modules/servers/ServersPage.vue';import Home from '/src/modules/servers/ServersHome.vue';import Settings from '/src/modules/settings/SettingsPage.vue';import {auth} from '/src/modules/home/auth';auth.me={id:'fixture-owner',username:'fixture',display_name:'fixture'};auth.suspended=false;auth.sessionClosing=false;const router=createRouter({history:createWebHistory(),routes:[{path:'/status',component:Page,children:[{path:'',component:Home}]},{path:'/settings',component:Settings}]});createApp({render:()=>h(RouterView)}).use(createPinia()).use(router).mount('#app');window.fixtureRouter=router;`;
await build({root,configFile:false,envDir:false,logLevel:'error',cacheDir:resolve(root,'.cache/center-browser-vite'),plugins:[vue(),{name:'center-fixture',resolveId(id){if(id==='virtual:center-entry')return '\0center-entry';},load(id){if(id==='\0center-entry')return entry;}}],build:{outDir:out,emptyOutDir:true,cssTarget:'chrome90',rollupOptions:{input:'virtual:center-entry',output:{entryFileNames:'entry.js'}}}});
const assets=(await import('node:fs/promises')).readdir;const files=await assets(out);const css=files.filter(f=>f.endsWith('.css')).map(f=>`<link rel="stylesheet" href="/${f}">`).join('');
await writeFile(resolve(out,'index.html'),`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${css}<style>html,body,#app{margin:0;width:100%;height:100%;background:var(--bg-base);color:var(--text-hi)}#app{padding:24px;box-sizing:border-box}@media(max-width:768px){#app{padding:12px}}</style><div id="app"></div><script type="module" src="/entry.js"></script></html>`);
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,'http://localhost').pathname;const file=path.startsWith('/status')||path.startsWith('/settings')?resolve(out,'index.html'):resolve(out,'.'+path);assert(file.startsWith(out+'/'));const data=await readFile(file);res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2'})[extname(file)]??'application/octet-stream');res.end(data);}catch{res.statusCode=404;res.end();}});await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
const result={kind:'isolated production-built component/router fixture; not live App/Agent acceptance',commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),checks:[],screenshots:[],requests:[],errors:[]};
try{
 for(const width of [1920,320]){
  const context=await browser.newContext({viewport:{width,height:width===1920?1080:850},reducedMotion:'reduce'});const page=await context.newPage();page.on('pageerror',e=>result.errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')result.errors.push(m.text());});
  const monitors=[{id:10,name:'默认入口 · ICMP',node_id:7,type:'ping',target:'192.168.160.3',interval:60,timeout:1,status:'up',last_check_at:new Date().toISOString(),last_latency_ms:1.2,management:'entry_icmp'},{id:11,name:'其他入口 · ICMP',node_id:7,type:'ping',target:'192.168.160.4',interval:60,timeout:1,status:'unknown',last_check_at:null,last_latency_ms:null,management:'entry_icmp'}];
  const groups=[{id:4,name:'测试节点 A → 中心',child_ids:[10,11],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:1,automatic:true,source_node_id:7},{id:5,name:'节点B-LongUnbrokenNameWithoutSpacesForOverflowRegression → 中心',child_ids:[],failure_policy:'any',rotation_seconds:0,status:'unknown',down_count:0,unknown_count:0,automatic:true,source_node_id:8}];
  const nodes=[{id:7,name:'测试节点 A',host:'192.168.160.7',platform:'linux',status:'pending',components:null},{id:8,name:'测试节点 B',host:'192.168.160.8',platform:'linux',status:'pending',components:null}];
  let nextId=12;
  await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(url.origin!==origin){result.errors.push('external:'+url.origin);return route.abort();}const p=url.pathname,method=req.method();const respond=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:status===204?'':JSON.stringify(body)});
   if(p==='/nodes/'&&method==='GET')return respond(nodes);
   if(p==='/nodes/map-topology'&&method==='GET')return respond({generated_at:new Date().toISOString(),nodes:[],links:[],stats:{located:0,unknown:0,links:0}});
   if(p==='/monitors/'&&method==='GET')return respond(monitors);
   if(p==='/monitors/groups'&&method==='GET')return respond(groups);
   if(/^\/monitors\/\d+\/series$/.test(p)&&method==='GET')return respond([]);
   if(/^\/monitors\/\d+\/mtr$/.test(p)&&method==='GET')return respond([]);
   if(p==='/alerts/incidents'&&method==='GET')return respond([]);
   if(p==='/monitors/groups/4/children'&&method==='POST'){const data=req.postDataJSON();const child={...data,id:nextId++,status:'unknown',last_check_at:null,last_latency_ms:null,management:null};monitors.push(child);groups[0].child_ids.push(child.id);result.requests.push({width,method,p,data});return respond(child,201);}
   if(/^\/monitors\/\d+$/.test(p)&&method==='PATCH'){const id=Number(p.split('/').at(-1));const m=monitors.find(m=>m.id===id);Object.assign(m,req.postDataJSON());result.requests.push({width,method,p,data:req.postDataJSON()});return respond(m);}
   if(/^\/monitors\/\d+$/.test(p)&&method==='DELETE'){const id=Number(p.split('/').at(-1));monitors.splice(monitors.findIndex(m=>m.id===id),1);groups.forEach(g=>g.child_ids=g.child_ids.filter(mid=>mid!==id));result.requests.push({width,method,p});return respond(null,204);}
   if(p==='/monitors/groups/4'&&method==='PUT'){Object.assign(groups[0],req.postDataJSON());result.requests.push({width,method,p,data:req.postDataJSON()});return respond(groups[0]);}
   if(p.startsWith('/auth/')||p.startsWith('/config/'))return respond({});
   if(!p.includes('.')&&!p.startsWith('/status')&&!p.startsWith('/settings')){result.errors.push('unknown API:'+method+' '+p);return respond({detail:'unknown fixture endpoint'},500);}
   return route.continue();
  });
  await page.goto(origin+'/status?view=overview#service-monitors');await page.getByText('测试节点 A → 中心',{exact:true}).waitFor();await page.locator('#service-monitors').scrollIntoViewIfNeeded();await page.mouse.move(0,0);await page.screenshot({path:resolve(evidence,`overview-${width}.png`)});result.screenshots.push(`overview-${width}.png`);
  const cardBounds=await page.locator('.mon-card').evaluateAll(els=>els.map(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,scroll:el.scrollWidth,client:el.clientWidth,children:[...el.querySelectorAll('.mon-name,.mon-group-health,button,.mon-target')].map(e=>{const c=e.getBoundingClientRect();return {left:c.left,right:c.right,within:c.left>=r.left-1&&c.right<=r.right+1};})};}));assert(cardBounds.every(c=>c.left>=0&&c.right<=width&&c.scroll<=c.client+1&&c.children.every(e=>e.within)),JSON.stringify(cardBounds));
  await page.getByRole('button',{name:'管理父监控子项'}).click();await page.getByRole('button',{name:'新建子项',exact:true}).click();await page.getByLabel('子项名称',{exact:true}).fill('附加 TCP');await page.getByLabel('子项目标',{exact:true}).fill('192.168.160.3:443');await page.getByRole('button',{name:'创建并加入',exact:true}).click();await page.getByRole('button',{name:'编辑子项 附加 TCP',exact:true}).waitFor();
  await page.screenshot({path:resolve(evidence,`children-${width}.png`)});result.screenshots.push(`children-${width}.png`);
  const dialogBounds=await page.locator('.group-dialog').evaluate(el=>({scroll:el.scrollWidth,client:el.clientWidth,rect:el.getBoundingClientRect().toJSON(),fields:[...el.querySelectorAll('input,button,.dd')].map(e=>e.getBoundingClientRect().toJSON())}));assert(dialogBounds.scroll<=dialogBounds.client+1);assert(dialogBounds.rect.left>=0&&dialogBounds.rect.right<=width);assert(dialogBounds.fields.every(r=>r.left>=dialogBounds.rect.left-1&&r.right<=dialogBounds.rect.right+1));
  await page.getByRole('button',{name:'编辑子项 附加 TCP',exact:true}).click();const edit=page.locator('.edit-body');await edit.locator('input').first().fill('改名 TCP');await edit.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('button',{name:'永久删除子项 改名 TCP',exact:true}).waitFor();
  await page.getByRole('button',{name:'永久删除子项 改名 TCP',exact:true}).click();await page.getByRole('button',{name:'取消删除',exact:true}).click();assert(monitors.some(m=>m.name==='改名 TCP'));
  await page.getByRole('button',{name:'永久删除子项 改名 TCP',exact:true}).click();await page.getByRole('button',{name:'确认永久删除',exact:true}).click();await page.getByRole('button',{name:'编辑子项 改名 TCP',exact:true}).waitFor({state:'detached'});assert(!monitors.some(m=>m.name==='改名 TCP'));
  await page.getByRole('button',{name:'编辑子项 默认入口 · ICMP',exact:true}).click();await edit.getByText('Ping · 自动入口',{exact:true}).waitFor();assert(await edit.locator('input[type=number]').isDisabled());await edit.locator('input').first().fill('自动名称可编辑');await edit.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('button',{name:'编辑子项 自动名称可编辑',exact:true}).waitFor();
  const choices=page.locator('.child-choice input[type=checkbox]');await choices.nth(1).uncheck();await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.locator('.group-dialog').waitFor({state:'detached'});assert.deepEqual(groups[0].child_ids,[10]);assert(monitors.some(m=>m.id===11));
  await page.getByRole('button',{name:'管理父监控子项'}).click();await page.locator('.child-choice input[type=checkbox]').nth(1).check();await page.getByRole('button',{name:'保存组合',exact:true}).click();await page.locator('.group-dialog').waitFor({state:'detached'});assert.deepEqual(groups[0].child_ids,[10,11]);
  for(const legacy of ['/settings?section=servers','/settings?tab=servers']){await page.goto(origin+legacy);await page.waitForURL('**/status?view=overview#service-monitors');await page.locator('#service-monitors').waitFor();assert(!await page.locator('.node-monitoring').count());}
  result.checks.push({width,cardBounds,dialogBounds,crud:true,automaticReadOnly:true,legacyRedirect:true});await context.close();
 }
 assert.deepEqual(result.errors,[]);
 await writeFile(resolve(evidence,'browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({checks:result.checks.map(c=>({width:c.width,crud:c.crud,legacyRedirect:c.legacyRedirect})),screenshots:result.screenshots,errors:result.errors}));
}finally{await browser.close();await new Promise(r=>server.close(r));await writeFile(resolve(evidence,'browser-result.json'),JSON.stringify(result,null,2));}
