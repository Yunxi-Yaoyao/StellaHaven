// Bounded screenshot audit: real App/components, declared synthetic data only.
// No production proxy/config/env; unknown requests fail closed, including WS.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import {chromium,expect} from '@playwright/test';
const root=process.cwd(),out=process.env.LAYOUT_EVIDENCE;
assert(out);fs.mkdirSync(out,{recursive:true});
const port=15581,origin=`http://127.0.0.1:${port}`;
const fixture=path.join(root,'node_modules/.tmp/layout-harness.mjs');fs.mkdirSync(path.dirname(fixture),{recursive:true});
fs.writeFileSync(fixture,ts.transpileModule(fs.readFileSync('e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(fixture);
const server=await createServer({root,configFile:false,envDir:false,plugins:[vue()],cacheDir:out+'/vite',optimizeDeps:{include:['html2canvas','jspdf','jszip']},server:{host:'127.0.0.1',port,strictPort:true,fs:{allow:[root,path.dirname(fs.realpathSync('node_modules/vite'))]},proxy:{},hmr:false}});
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),fixture:'Real App. Synthetic accounts/nodes/metrics/documents; solid placeholder wallpaper. Not production data, backend acceptance or physical-phone review.',runs:[]};
let browser;
try{
 await server.listen();browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
 for(const width of [1440,393]){
  const context=await browser.newContext({viewport:{width,height:width===1440?1000:852},serviceWorkers:'block',isMobile:width<500,hasTouch:width<500});
  const page=await context.newPage();page.setDefaultTimeout(10000);
  const h=await setup(page,{storage:{stella_home_theme:'nightfall',stella_server_world_map_collapsed:'1'}});h.user.is_admin=true;
  const run={width,shots:[],checks:[],failures:[],unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors,requests:[]};report.runs.push(run);
  const stamp=new Date().toISOString();let failNotes=false,failSMTP=false,failNodes=false;
  const security={enabled:true,configured:true,elevated:true,single_user:true,setup_required:false};
  const nodes=[{id:1,name:'演示边缘节点',host:'192.0.2.10',platform:'linux',status:'online',last_seen:stamp,agent_version:'fixture'},{id:2,name:'演示归档节点',host:'192.0.2.11',platform:'linux',status:'offline',last_seen:'2026-01-01T00:00:00Z'}];
  const detail={...nodes[0],interfaces:{eth0:{up:true,is_physical:true,is_default:true,ip:'192.0.2.10',ipv4:['192.0.2.10/24'],speed:1000,mac:'00:00:5e:00:53:01'}},monitored_ifaces:{eth0:{}},latest_metrics:[{iface:'eth0',ts:stamp,rx_delta:62500,tx_delta:12000}],latest_sys_metric:{ts:stamp,cpu_pct:12,mem_pct:35},sys_info:{hostname:'example-edge',os:'Linux (synthetic)',kernel:'fixture',cpu_model:'Synthetic CPU',cpu_count:4,mem_total:8589934592,uptime:86400,load1:0.2,load5:0.3,load15:0.2,disks:[],hardware:{sampled_at:stamp,availability:{cpu_temperature:'available',gpu:'no_gpu'},cpu:{sampled_at:stamp,model:'Synthetic CPU',physical_cores:2,logical_cores:4,frequency_mhz:2400,temperature_c:42},memory:{total_bytes:8589934592,used_bytes:3006477107,available_bytes:5583457485,scope:'os_visible',state:'available',sampled_at:stamp},gpus:[],sensors:[],machine:{kind:'virtual',vendor:null,model:'Synthetic guest',virtualization:'KVM',evidence:['synthetic fixture'],detected_at:stamp}}}};
  const doc={id:'layout-doc',title:'布局审查合成笔记',workspace_id:'layout-ws',parent_id:null,content:'# 阅读与编辑\n\n这是一份明确的合成场景，不是用户笔记。检查正文行宽、侧栏比例与编辑入口。\n\n## 布局原则\n\n合理留白用于阅读和构图，不用额外卡片填满。\n\n| 项目 | 目标 |\n|---|---|\n| 输入栏 | 依据内容分配宽度 |\n| 编辑器 | 阅读区保持清晰 |\n\n```sh\nprintf "example\\n"\n```\n\n## 后续\n\n有限修复清单交由主任务决定。',file_path:'/synthetic.md',created_at:stamp,updated_at:stamp,updated_at_display:stamp,has_draft:false,status:'published',is_folder:false,is_favorite:false,is_pinned:false};
  const provider={issuer:'https://example.invalid',discovery_url:'https://example.invalid/.well-known/openid-configuration',authorization_endpoint:'https://example.invalid/oidc/authorize',token_endpoint:'https://example.invalid/oidc/token',userinfo_endpoint:'https://example.invalid/oidc/userinfo',jwks_uri:'https://example.invalid/oidc/jwks',clients:[{client_id:'synthetic-reader',name:'演示阅读应用',redirect_uris:['https://reader.example.invalid/callback'],scopes:['openid','profile'],enabled:true,has_secret:true}],capabilities:{}};
  const modules=[{id:'example-site',name:'演示网站',icon:'globe',browser_url:'https://example.invalid/',mode:'iframe',adapter:'generic',enabled:true,keep_alive:false,injection:{active:null,draft:null,previous:null}}];
  const prefs={revision:1,delete_action:'trash',ask_before_delete:true};
  const rules=[{id:7,revision:2,node_id:1,label:'演示月度出口流量',condition:{metric:'network.volume',direction:'out',interface:'eth0',threshold:'9007199254740993',window:{kind:'fixed',start:'2026-10-01T00:00:00Z',end:'2026-10-31T00:00:00Z',timezone:'Asia/Shanghai'}},severity:'warning',debounce:2,repeat_minutes:0,email:false,enabled:true,state:'ok',preview:{value:'12000000000',lower:'12000000000',upper:'12000000000',quality:'valid',reason:'',watermark:stamp,unit:'byte',bad:false},evaluated_at:stamp}];
  const data={
   '/auth/security':security,'/auth/provider/config':provider,'/external-modules':modules,
   '/navigation':{entries:[{id:'home',title:'主页',visible:true},{id:'notes',title:'笔记',visible:true},{id:'status',title:'服务器',visible:true},{id:'example-site',title:'演示网站',visible:true},{id:'settings',title:'设置',visible:true}],legacy_routes:{}},
   '/auth/sessions':[{id:'synthetic-current',device:'Chrome / Linux',current:true,ip:'192.0.2.1',ip_location:'合成地点',created_at:stamp,last_seen:stamp}],
   '/auth/sessions/history':{items:[],total:0,page:1,page_size:20},
   '/admin/email/config':{host:'mail.example.invalid',port:465,user:'sender@example.invalid',password:'',sender:'sender@example.invalid',sender_name:'演示通知',enabled:false,use_ssl:true},
   '/notes-preferences':prefs,'/nodes/':nodes,'/nodes/host':{hostname:'synthetic-host',platform:'linux',installed:true,node_id:1},'/nodes/1':detail,
   '/nodes/map-topology':{generated_at:stamp,nodes:[],links:[],stats:{located:0,unknown:0,links:0}},
   '/monitors/':[],'/component-installs':[],'/nodes/1/net-tasks/latest':{id:1,status:'done',created_at:stamp,result_json:{ufw:{installed:true,status:'inactive',rules:[]},iptables:{tables:{}},rules:[],tables:{},marks:[]}},'/operations/backup-health':{status:'unknown',message:'Synthetic: no backup observation',items:[]},
   '/alerts/rules':[{id:1,kind:'node_offline',target:'2',label:'演示归档节点',link:'/status/2',severity:'warning',enabled:true,email:false,state:'fired'}],'/alerts/events':[],
   '/alerts/v2/rules':rules,
   '/workspaces/':[{id:'layout-ws',name:'合成笔记',user_id:h.user.id}],'/documents/':[doc],'/documents/layout-doc':doc,'/documents/recent':[],'/documents/favorites':[],'/tags/':[],'/doc-tags/':[],
   '/documents/layout-doc/draft':null,'/documents/layout-doc/versions':[],'/documents/layout-doc/links':[],'/documents/layout-doc/backlinks':[],'/attachments/layout-doc':[],'/attachments/':[]
  };
  await context.routeWebSocket(origin.replace('http:','ws:')+'/ws/list/layout-ws',ws=>ws.onMessage(()=>{}));
  await context.routeWebSocket(origin.replace('http:','ws:')+'/ws/layout-doc?*',ws=>ws.onMessage(()=>{}));
  await context.route('**/*',async r=>{
   const q=r.request(),u=new URL(q.url()),p=u.pathname,m=q.method();
   if(['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.origin+p))return r.fulfill({json:{ip:'192.0.2.1',city:'合成地点',country:'CN'}});
   if(u.origin!==origin)return r.fallback();
   if(['/qa-pattern.svg','/avatar.png'].includes(p))return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#29272c"/></svg>'});
   if(p.startsWith('/@fs/'))return r.continue();
   if(m==='GET'&&Object.hasOwn(data,p)){
    run.requests.push({method:m,path:p});
    if((p==='/notes-preferences'&&failNotes)||(p==='/nodes/'&&failNodes))return r.fulfill({status:503,json:{detail:'Synthetic unavailable'}});
    return r.fulfill({json:data[p]});
   }
   if(m==='GET'&&['/nodes/1/metrics','/nodes/1/sys-metrics'].includes(p))return r.fulfill({json:Array.from({length:30},(_,i)=>({ts:new Date(Date.now()-(29-i)*5000).toISOString(),iface:'eth0',rx_delta:62500+(i%7)*10000,tx_delta:12000,cpu_pct:12+(i%6),mem_pct:35}))});
   if(m==='GET'&&p==='/nodes/1/traffic-stats')return r.fulfill({json:{rx_95:62500,tx_95:12000,rx_max:92500,rx_min:62500,tx_max:12000,tx_min:12000,rx_total:12000000,tx_total:3000000,sample_count:30}});
   if(m==='POST'&&['/nodes/1/firewall-scan','/nodes/1/pbr-scan'].includes(p))return r.fulfill({status:422,json:{detail:'Synthetic scan unavailable; no agent exists'}});
   if(p==='/admin/email/config'&&m==='PUT'&&failSMTP)return r.fulfill({status:422,json:{detail:'Synthetic rejected configuration'}});
   if(p==='/documents/layout-doc'&&m==='PUT')return r.fulfill({status:422,json:{detail:'合成保存失败：笔记草稿仍保留'}});
   if(p==='/alerts/v2/rules/7'&&m==='PUT')return r.fulfill({status:422,json:{detail:'合成保存失败：检查所选时间范围'}});
   if(p==='/website-settings/check'&&m==='POST')return r.fulfill({json:{normalized_url:'https://example.invalid/',name_suggestion:'',access:{status:'unknown',http_status:null},embedding:{status:'blocked',reason_code:'csp_none',reason:"合成上游 CSP 不允许嵌入"},injection:{status:'unsupported',reason:'跨域网页不能修改 DOM'},help:null,can_save:false,recommended_behavior:'external',issues:['请更改打开方式或核对上游配置']}});
   return r.fallback();
  });
  const flush=()=>fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));
  async function shot(name){
   await page.waitForTimeout(250);await page.evaluate(()=>document.fonts.ready);
   const file=`${name}-${width}.png`;await page.screenshot({path:out+'/'+file,fullPage:true});
   const geometry=await page.evaluate(()=>({url:location.pathname+location.search,viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,fields:[...document.querySelectorAll('input:not([type=password]),select,textarea')].filter(e=>e.getBoundingClientRect().width>0).map(e=>({tag:e.tagName,type:e.type,label:e.getAttribute('aria-label')||e.placeholder||e.id,rect:e.getBoundingClientRect().toJSON()})),regions:[...document.querySelectorAll('.card,.notes-settings,.inline-editor,.node-detail,.detail-grid,.overview,.tab-body,.metric-alerts,.editor,.doc-list,.dialog,.hardware-grid,.hardware-card,.hardware-panel,.memory-panel')].filter(e=>e.getBoundingClientRect().width>0).map(e=>({cls:e.className,rect:e.getBoundingClientRect().toJSON()}))}));
   run.shots.push({name,file,geometry});flush();
  }
  async function bottomShot(name,selector){await page.locator(selector).last().scrollIntoViewIfNeeded();await shot(name);}
  async function check(name,fn){try{await fn();run.checks.push(name)}catch(e){run.failures.push({name,error:e.stack});await shot('failure-'+name)}flush()}
  async function go(url){await page.evaluate(async url=>{const {default:router}=await import('/src/router/index.ts');await router.push(url)},url);await page.waitForTimeout(500)}
  await page.goto(origin);await page.getByRole('button',{name:'主页设置',exact:true}).waitFor();
  for(const [key,label]of [['nightfall','夜泊'],['daybreak','破晓']])await check('home-'+key,async()=>{await page.getByRole('button',{name:'主页设置',exact:true}).click();await page.getByRole('dialog',{name:'主页设置'}).getByRole('button',{name:new RegExp('^'+label)}).click();await page.keyboard.press('Escape');await shot('home-'+key);await page.getByRole('button',{name:'主页设置',exact:true}).click();await shot('home-'+key+'-drawer');await page.keyboard.press('Escape')});
  for(const section of ['profile','authentication','navigation','notes','services','performance'])await check('settings-'+section,async()=>{
   await go('/settings?section='+section);await page.getByRole('heading',{name:'设置',exact:true}).waitFor();await shot('settings-'+section);
   if(section==='profile'){await page.getByRole('button',{name:'绑定邮箱',exact:true}).click();await shot('settings-profile-expanded');await page.getByRole('button',{name:'发送验证码',exact:true}).click();await shot('settings-profile-error');await page.locator('.mini-mask').click({position:{x:5,y:5}});}
   if(section==='authentication'){const details=page.locator('details');if(await details.count()){await details.last().locator('summary').click();await shot('settings-auth-history');await bottomShot('settings-auth-bottom','.card details');}}
   if(section==='notes'){failNotes=true;await go('/');await go('/settings?section=notes');await shot('settings-notes-error');failNotes=false;}
   if(section==='services'){await page.getByLabel('SMTP 服务地址').waitFor();await page.getByLabel('SMTP 服务地址').fill('bad.example.invalid');failSMTP=true;await page.getByRole('button',{name:'应用 SMTP 配置',exact:true}).click();await page.getByText('未保存，请重试',{exact:true}).waitFor();await shot('settings-services-error');await bottomShot('settings-services-bottom','button:has-text("发送测试邮件")');failSMTP=false;}
   if(section==='navigation'){
    await page.getByRole('button',{name:/添加网站/}).click();await shot('website-form');await page.getByLabel('网站地址',{exact:true}).fill('https://example.invalid/');await page.getByLabel('显示名称',{exact:true}).fill('演示网站草稿');
    await page.locator('details.custom > summary').click();await shot('website-form-expanded');await bottomShot('website-code-bottom','textarea');await page.getByRole('button',{name:'检测',exact:true}).click();await page.getByLabel('检测结果').waitFor();await shot('website-form-error');await page.locator('.inline-editor').getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'放弃修改',exact:true}).click();
   }
  });
  await check('servers-list',async()=>{await go('/status');await page.locator('.nodes-view .card').first().waitFor();await shot('servers-list');await page.getByRole('button',{name:'添加节点',exact:true}).click();await shot('servers-add');});
  await check('servers-error',async()=>{failNodes=true;await go('/');await go('/status');await page.getByText('服务器加载失败',{exact:false}).first().waitFor();await shot('servers-list-error');failNodes=false;});
  await check('server-detail',async()=>{failNodes=false;await go('/status/1');await page.locator('.d-tabs').waitFor();await shot('server-detail');await bottomShot('server-detail-bottom','.tab-body:visible .chart');await page.getByRole('button',{name:'网络',exact:true}).click();await shot('server-detail-network');});
  await check('alerts',async()=>{await go('/status?view=alerts');await page.getByRole('button',{name:'编辑',exact:true}).last().waitFor();await shot('alerts');await page.getByRole('button',{name:'编辑',exact:true}).last().click();await shot('alerts-expanded');await page.getByRole('button',{name:'保存规则',exact:true}).click();await page.locator('form [role=alert]').waitFor();await shot('alerts-error');await page.keyboard.press('Escape')});
  await check('notes',async()=>{await go('/notes?doc=layout-doc');await page.locator('.markdown-body table').waitFor();await shot('notes-reading');await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'Markdown',exact:true}).click();await page.locator('.cm-content').waitFor();await shot('notes-editing');await page.getByRole('button',{name:'阅览',exact:true}).click();await page.getByRole('button',{name:'更多',exact:true}).click();await page.locator('#note-more-menu').getByRole('button',{name:'文档信息与标签',exact:true}).click();await shot('notes-info-expanded');await page.keyboard.press('Escape');await page.getByRole('button',{name:'编辑',exact:true}).click();await page.locator('.cm-content').click();await page.keyboard.press('Control+End');await page.keyboard.insertText('\n合成失败草稿');const failedSave=page.waitForResponse(r=>new URL(r.url()).pathname==='/documents/layout-doc'&&r.request().method()==='PUT');await page.keyboard.press('Control+s');await failedSave;await shot('notes-save-error');});
  const unexpectedConsole=run.consoleErrors.filter(x=>!/^Failed to load resource: the server responded with a status of (422|503) /.test(x));if(unexpectedConsole.length)run.failures.push({name:'unexpected-console',error:unexpectedConsole});
  await context.close();flush();
 }
}finally{await browser?.close();await server.close();fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report.runs.map(r=>({width:r.width,shots:r.shots.length,checks:r.checks,failures:r.failures,unknown:r.unknown,errors:r.errors,consoleErrors:r.consoleErrors})),null,2));
if(report.runs.some(r=>r.failures.length||r.unknown.length||r.errors.length))process.exitCode=1;
