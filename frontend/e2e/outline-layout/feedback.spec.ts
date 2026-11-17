// Actual built App, isolated HTTP/WS responses; never connects to the backend.
import {test,expect,chromium,type Page} from '@playwright/test';
import {createClientPreferencesFixture} from '../../tests/fixtures/clientPreferences';
import {createRound2WebsiteFixture} from '../../tests/fixtures/round2Website';
import {layoutNodes} from '../../tests/fixtures/layoutNodes';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const base='http://127.0.0.1:15327';
const workspace='11111111-1111-4111-8111-111111111111',docId='22222222-2222-4222-8222-222222222222';
const note={id:docId,title:'场景与正文阅读',workspace_id:workspace,parent_id:null,content:'# 场景与正文阅读\n\n这是一篇用于布局验收的非空笔记。长文应该在右侧阅读区域内居中，而不是随着二级目录一起靠左。\n\n## 小节\n\n保留正文、目录与设置抽屉各自的滚动边界。',updated_at:'2026-10-20T00:00:00Z',created_at:'2026-10-20T00:00:00Z',has_draft:false,is_favorite:false,status:'published',file_path:'/fixture.md',content_hash:'fixture',is_folder:false,is_pinned:false,draft_updated_at:null,draft_device:null};
const projectId='33333333-3333-4333-8333-333333333333',folderId='66666666-6666-4666-8666-666666666666',entryId='55555555-5555-4555-8555-555555555555';
const project={id:projectId,workspace_id:workspace,title:'交互练习册',entry:'assets/index.html',entry_file_id:entryId,directories:[{id:folderId,path:'assets',kind:'directory'}],files:[{id:entryId,path:'assets/index.html',kind:'text',mime:'text/html',size:48,updated_at:'2026-10-20T00:00:00Z'}]};
const projectDocs=[{...note,id:projectId,title:project.title,content:'',is_folder:true},{...note,id:folderId,title:'assets',parent_id:projectId,is_folder:true,content:''},{...note,id:entryId,title:'index.html',parent_id:folderId,content:'<!doctype html><h1>交互练习册</h1>'}];
const backupSnapshot={config:{revision:1,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0},records:[{id:'record-id',filename:'stella-settings-20261020.zip',scope:'settings',created_at:'2026-10-20T00:00:00Z',bytes:4096,sha256:'a'.repeat(64),verified:true}],job:{id:'completed-synthetic-backup',kind:'backup',scope:'settings',state:'succeeded',stage:'completed',error:null,record_id:'record-id'},storage:{node:'fixture-node',available:true,free_bytes:10737418240,error:null},next_run:null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}};

const output=process.env.STELLA_LAYOUT_OUTPUT||path.join(tmpdir(),'stella-feedback-layout-evidence');
async function setup(page:Page,folded=false,nonemptyNodes=false,withProject=false,options:{integrated?:boolean;locked?:boolean;smtp?:boolean}={}){
 await mkdir(output,{recursive:true});
 const preferences=createClientPreferencesFixture({storage:{stella_live2d:'off',stella_servers_fold:folded?'1':'0',stella_list_fold:'0',stella_note_edit_mode:'markdown'},allowWrite:true});
 const unknown:string[]=[],errors:string[]=[],writes:string[]=[],preferenceWrites:any[]=[];
 const calls:{method:string,path:string,body?:any}[]=[];
 const website=createRound2WebsiteFixture();let elevated=!options.locked;
 let failPreferences=false,holdProfile=false,releaseProfile=()=>{};
 const profile={id:'fixture-owner',username:'yunxi',display_name:'云曦',is_admin:true,email:'long-address-for-layout-check@example.test',email_verified:false,avatar_url:'/avatar.png'};
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&!m.text().startsWith('Failed to load resource:'))errors.push(m.text());});
 await page.routeWebSocket('**/*',ws=>{const u=new URL(ws.url());if(u.origin!=='ws://127.0.0.1:15327'||!['/ws/notifications','/ws/list/'+workspace,'/ws/'+docId].includes(u.pathname)||(!['','?device=Chrome'].includes(u.search))){unknown.push(ws.url());ws.close({code:1008,reason:'Unknown isolated WebSocket'});}});
 await page.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url()),p=u.pathname,m=request.method();
  if(!p.startsWith('/static/'))calls.push({method:m,path:p+u.search,...(['POST','PATCH','PUT'].includes(m)?{body:request.postData()?request.postDataJSON():null}:{})});
  if(m==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.href))return route.fulfill({json:{ip:'192.0.2.1',region:'Fixture',country:'ZZ'}});
  if(u.origin!==base){unknown.push(m+' '+u.href);return route.abort();}
  if(m==='GET'&&(['/','/settings','/status','/notes','/help','/avatar.png','/favicon.svg','/maps/world.geo.json',...(options.integrated?['/status/1','/apps/owned','/integrated-not-found']:[])].includes(p)||p.startsWith('/static/')))return route.continue();
  const ok=(json:any)=>route.fulfill({json});

  if(m==='POST'&&p==='/auth/admin/unlock'&&!u.search&&options.integrated){elevated=true;return ok({ok:true});}
  if(options.integrated){
   if(['/admin/email/config','/auth/provider/config','/config/access-entries'].includes(p)&&!elevated)return route.fulfill({status:403,json:{detail:{code:'admin_elevation_required'}}});
   const response=website.respond(m,p+u.search,['POST','PUT','PATCH'].includes(m)?request.postDataJSON():undefined);if(response)return route.fulfill(response);
  }
  if(options.integrated&&m==='GET'&&p==='/nodes/1'&&!u.search)return ok({...layoutNodes[0],interfaces:{eth0:{is_default:true,up:true}},monitored_ifaces:{eth0:true},latest_metrics:[],latest_sys_metric:{ts:new Date().toISOString(),cpu_pct:12,mem_pct:35,disk_pct:22}});
  if(options.integrated&&m==='GET'&&p==='/nodes/1/net-tasks/latest'&&['?kind=firewall_scan','?kind=pbr_scan'].includes(u.search))return ok({id:'synthetic-cache',node_id:1,status:'done',created_at:new Date().toISOString(),result_json:u.search.includes('firewall')?{ufw:{installed:true,active:false,rules:[]},iptables:{tables:{}}}:{rules:[],tables:{},marks:[]}});
  if(options.integrated&&m==='GET'&&['/nodes/1/metrics','/nodes/1/sys-metrics','/nodes/1/traffic-stats'].includes(p)){
   const q=u.searchParams,valid=[...q.keys()].every(k=>['iface','start','end','limit','step'].includes(k))&&['start','end'].every(k=>!!q.get(k)&&Number.isFinite(Date.parse(q.get(k)!)))&&[...q.entries()].every(([k,v])=>['limit','step'].includes(k)?/^\d+(\.\d+)?$/.test(v):k==='iface'?v==='eth0':true);
   if(!valid){unknown.push(m+' '+p+u.search);return route.fulfill({status:500,json:{detail:'Unknown chart query'}});}
   if(p.endsWith('traffic-stats'))return ok({rx_95:1000,tx_95:500,rx_max:1200,rx_min:800,tx_max:600,tx_min:400,rx_total:100000,tx_total:50000,sample_count:10});
   const start=Date.parse(q.get('start')!),end=Date.parse(q.get('end')!);return ok(Array.from({length:10},(_,i)=>({ts:new Date(start+(end-start)*i/9).toISOString(),...(p.endsWith('sys-metrics')?{cpu_pct:10+i,mem_pct:30+i,disk_pct:20+i}:{iface:'eth0',rx_delta:1000+i*10,tx_delta:500+i*10})})));
  }
  if(options.integrated&&m==='POST'&&p==='/external-modules/owned/launch'&&!u.search)return route.fulfill({status:503,json:{detail:'隔离外站入口暂不可用'}});
  if(options.integrated&&m==='GET'&&p==='/assets/homebg/default-bg-kimono-1920.webp'&&!u.search)return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#191a20"/></svg>'});
  const exact:Record<string,any>={
   ['/homebg/media?url=%2Fassets%2Fhomebg%2Fdefault-bg-kimono-1920.webp']:{url:'/assets/homebg/default-bg-kimono-1920.webp',status:'ready',variants:{original:'/assets/homebg/default-bg-kimono-1920.webp'},width:1920,height:1080},
   ['/attachments/?workspace_id='+workspace]:[],
   ['/workspaces/?user_id=fixture-owner&limit=100']:[{id:workspace,name:'布局验收笔记本',user_id:'fixture-owner'}],
   ['/workspaces/?limit=100']:[{id:workspace,name:'布局验收笔记本',user_id:'fixture-owner'}],
   ['/workspaces/'+workspace]:{id:workspace,name:'布局验收笔记本',user_id:'fixture-owner'},
   ['/documents/?workspace_id='+workspace+'&skip=0&limit=500']:[note],
   ['/documents/'+docId]:note,
   ['/documents/'+docId+'/draft']:{doc_id:docId,content:null,device:null,updated_at:null},
   ['/documents/'+docId+'/backlinks']:[],
   ['/notes-tools/documents/'+docId+'/node']:{node_id:null},
   ['/document-links/?workspace_id='+workspace]:[],
   ['/doc-tags/?doc_id='+docId]:[],
   ['/doc-tags/']:[],['/tags/?limit=200']:[],
   ['/documents/recent?workspace_id='+workspace]:[note],
   ['/documents/trash?workspace_id='+workspace]:[],
   ['/notes-preferences']:{revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[]},
   ['/web-projects/workspace/'+workspace]:[],
   ['/web-projects/workspace/'+workspace+'/identities']:[],
   ['/detached-sources?workspace_id='+workspace]:[],
   ['/notes-tools/templates/'+workspace]:{root_id:'44444444-4444-4444-8444-444444444444',items:[],recent_ids:[]},
   ['/config/access-entries']:{settings:{revision:4,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://stella.private.test'},issuer:'https://identity.example.test',deployed:{public:'https://stella.example.test',private:'https://stella.private.test'},websites:[]},
   ['/operations/backups']:backupSnapshot,
   ['/nodes/monitoring-policy']:{revision:1,enabled:true,source_node_id:layoutNodes[0].id,host_node_id:null,interval:60,source_ready:true,source_scope:null,source_test_targets:[],managed:[],pending:[]},
   ['/monitors/']:[],['/monitors/groups']:[],
   ['/nodes/map-topology']:{nodes:[],links:[],updated_at:'2026-10-20T00:00:00Z'},
   ['/alerts/rules']:[],['/alerts/v2/rules']:[],
   ['/alerts/incidents?limit=5&offset=0&status=unresolved']:{items:[],total:0,limit:5,offset:0,untracked:[]},
   ['/alerts/incidents?limit=5&offset=0']:{items:[],total:0,limit:5,offset:0},
   ['/alerts/incidents?limit=30&offset=0']:{items:[],total:0,limit:30,offset:0},
   ['/alerts/incidents?limit=30&offset=0&status=unresolved']:{items:[],total:0,limit:30,offset:0,untracked:[]},
   ['/alerts/incidents?limit=30&offset=0&status=all']:{items:[],total:0,limit:30,offset:0,untracked:[]},
  };
  if(withProject){
   if(m==='GET'&&p==='/documents/'&&u.search==='?workspace_id='+workspace+'&skip=0&limit=500')return ok([note,...projectDocs]);
   if(m==='GET'&&p==='/web-projects/workspace/'+workspace+'/identities'&&!u.search)return ok([{id:projectId,workspace_id:workspace,members:[projectId,folderId,entryId]}]);
   if(m==='GET'&&p==='/web-projects/workspace/'+workspace&&!u.search)return ok([project]);
   if(m==='GET'&&p==='/web-projects/'+projectId&&!u.search)return ok(project);
   if(m==='GET'&&projectDocs.some(d=>p==='/documents/'+d.id)&&!u.search)return ok(projectDocs.find(d=>p==='/documents/'+d.id));
   if(m==='POST'&&p==='/web-projects/'+projectId+'/launch'&&!u.search)return route.fulfill({status:503,json:{detail:'隔离运行入口暂不可用，请重试'}});
  }
  if(m==='GET'&&Object.hasOwn(exact,p+u.search))return ok(exact[p+u.search]);
  if(m==='POST'&&p==='/notes-tools/templates/'+workspace+'/initialize'&&!u.search)return ok({root_id:'44444444-4444-4444-8444-444444444444',items:[],recent_ids:[]});
  const allowedQueries:Record<string,string[]>={'/auth/sessions':['?page=1&page_size=20&exclude_current=true','?current_only=true'],'/auth/sessions/history':['?page=1&page_size=20'],'/mtr-tasks':['?trigger=manual']};
  if(u.search && !(allowedQueries[p]||[]).includes(u.search)){unknown.push(m+' '+p+u.search);return route.fulfill({status:500,json:{detail:'Unknown query'}});}
  if(m==='PUT'&&p==='/operations/backups/client-preferences'){preferenceWrites.push(request.postDataJSON());if(failPreferences)return route.fulfill({status:503,json:{detail:'隔离同步失败，输入保留'}});}
  const preference=preferences.respond(m,p+u.search,m==='PUT'?request.postDataJSON():undefined);if(preference)return route.fulfill(preference);
  if(m==='POST'&&p==='/auth/activity')return ok({ok:true});
  if(m==='PATCH'&&p==='/auth/me'){writes.push(p);if(Object.hasOwn(request.postDataJSON(),'email')){Object.assign(profile,{email:request.postDataJSON().email,email_verified:false});return ok(profile);}if(holdProfile)await new Promise<void>(resolve=>{releaseProfile=resolve;});return route.fulfill({status:400,json:{detail:'保存失败，网络连接未确认。当前输入保留，请稍后重试；这段错误用于验证多行布局，不会改动账号。'}});}
  if(m!=='GET'&&!(p==='/auth/refresh'&&m==='POST')){unknown.push(m+' '+p);return route.abort();}
  if(p==='/auth/status')return ok({initialized:true});
  if(p==='/auth/me'||p==='/auth/refresh')return ok(profile);
  if(p==='/auth/security')return ok({enabled:true,configured:true,elevated,single_user:true});
  if(p==='/navigation')return ok({entries:[],legacy_routes:{}});
  if(p==='/notifications/unread-count')return ok({count:0});
  if(p==='/auth/sessions/history')return ok({items:[],total:0,page:1,page_size:20});
  if(p==='/nodes/')return ok(nonemptyNodes?layoutNodes:[]);
  if(['/auth/sessions','/auth/avatars','/external-modules','/notifications','/homebg/','/component-installs','/iperf-tasks','/commands','/mtr-tasks'].includes(p))return ok([]);
  if(p==='/nodes/host')return ok({local_install_supported:false,os:'fixture',installed:false,node_id:null,node_status:null});
  if(p==='/auth/provider/config')return ok({issuer:'https://stella.example.test',discovery_url:'https://stella.example.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.example.test/oauth/authorize',token_endpoint:'https://stella.example.test/oauth/token',userinfo_endpoint:'https://stella.example.test/oauth/userinfo',jwks_uri:'https://stella.example.test/oauth/jwks',capabilities:{},clients:[{client_id:'fixture-client',name:'样板应用',enabled:true,has_secret:true,scopes:['openid','profile'],redirect_uris:['https://app.example.test/auth/login']}]});
  if(p==='/auth/email-service')return ok({ready:options.smtp===true});
  if(['/config/public-host','/config/site-background'].includes(p))return ok({value:''});
  if(p==='/homebg/media')return ok({source:'',poster:''});
  if(p==='/admin/email/config')return ok({host:'smtp.example.test',port:465,username:'fixture@example.test',has_password:true,enabled:false,from_name:'Stella'});
  unknown.push(m+' '+p);return route.fulfill({status:500,json:{detail:'Unknown isolated fixture request'}});
 });
 await page.addInitScript(folded=>{localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'fixture-owner',workspaceId:'11111111-1111-4111-8111-111111111111'}));localStorage.setItem('stella_list_fold','0');localStorage.setItem('stella_note_edit_mode','markdown');if(localStorage.getItem('stella_servers_fold')===null)localStorage.setItem('stella_servers_fold',folded?'1':'0');},folded);
 return {website,calls,unknown,errors,writes,preferenceWrites,failPreferences:(value:boolean)=>{failPreferences=value;},holdProfile:()=>{holdProfile=true;},releaseProfile:()=>{holdProfile=false;releaseProfile();}};
}
for(const width of [1920,1365,390,320])test(`feedback server view matrix ${width}`,async({page})=>{
 const f=await setup(page,false,true);await page.setViewportSize({width,height:900});const matrix=[];
 for(const query of ['view=overview','view=nodes','view=docker','view=alerts','view=tools&tool=iperf','view=tools&tool=mtr','view=tools&tool=command','view=tools&tool=records']){
  await page.goto('/status?'+query);await expect(page.locator('.servers-page > .view-body')).toBeVisible();await page.waitForLoadState('networkidle');await settleLayout(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:path.join(output,`feedback-server-${query.replaceAll('&','-').replaceAll('=','-')}-${width}.png`)});
  if(width>768){const pane=(await page.locator('main.content').boundingBox())!,nav=(await page.locator('.servers-bar').boundingBox())!;expect(nav.y).toBe(pane.y);expect(nav.height).toBe(pane.height);}
  if(query.includes('view=tools')&&!query.endsWith('records')&&width===1920){const form=(await page.locator('.tools .p-body').boundingBox())!,pane=(await page.locator('.view-body').boundingBox())!;expect(form.width).toBeLessThanOrEqual(1040);expect(Math.abs(form.x+form.width/2-pane.x-pane.width/2)).toBeLessThan(2);}
  matrix.push({query,viewport:width,initial:true});
 }
 await writeFile(path.join(output,`server-matrix-${width}.json`),JSON.stringify({matrix,unknown:f.unknown,errors:f.errors},null,2));expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.writes).toEqual([]);
});
for(const width of [1920,390])test(`feedback notes and documentation divider ${width}`,async({page})=>{
 const f=await setup(page);await page.setViewportSize({width,height:900});await page.goto('/notes');await expect(page.locator('.doc-list')).toBeAttached();await expect(page.locator('.title-readonly')).toContainText(note.title);await settleLayout(page);if(width>768){const prose=(await page.locator('.panes .preview').boundingBox())!,pane=(await page.locator('.panes').boundingBox())!;expect(prose.width).toBe(800);expect(Math.abs(prose.x+prose.width/2-pane.x-pane.width/2)).toBeLessThan(2);}
 if(width>768){const pane=(await page.locator('.notes-page').boundingBox())!,nav=(await page.locator('.doc-list').boundingBox())!;expect(nav.y).toBe(pane.y);expect(nav.y+nav.height).toBe(pane.y+pane.height);expect((await page.locator('.search-box').boundingBox())!.y).toBeGreaterThanOrEqual(28);}
 await page.screenshot({path:path.join(output,`feedback-notes-${width}.png`)});
 await page.goto('/notes?settings=open');await expect(page.locator('.notes-settings')).toBeVisible();await expect(page.locator('.notes-settings')).not.toContainText('附件引用与草稿保护');await expect(page.locator('.notes-settings')).toContainText('删除后不可恢复');await page.getByRole('button',{name:'笔记数据保护说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toContainText('附件引用与草稿保护');await page.screenshot({path:path.join(output,`feedback-notes-settings-help-${width}.png`)});await page.keyboard.press('Escape');
 await page.goto('/help');await expect(page.locator('.doc-reading article')).toBeVisible();await settleLayout(page);
 if(width>768){const pane=(await page.locator('main.content').boundingBox())!,nav=(await page.locator('.doc-directory').boundingBox())!;expect(nav.y).toBe(pane.y);expect(nav.y+nav.height).toBe(pane.y+pane.height);}
 await page.screenshot({path:path.join(output,`feedback-help-${width}.png`)});expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const width of [1920,1365,390,320])test(`feedback settings route matrix ${width}`,async({page})=>{
 const f=await setup(page,false,true);await page.setViewportSize({width,height:900});const matrix=[];
 for(const [section,selector] of [['profile','.profile-settings'],['appearance','.appearance-settings'],['navigation','.nav-settings'],['servers','.node-policy'],['services','.mail-service'],['authentication','.security-card'],['backups','.backup-center'],['performance','.performance-card']]){
  await page.goto('/settings?section='+section);await expect(page.locator(selector)).toBeVisible();await settleLayout(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(width>768){const scene=(await page.locator('.settings-scene').boundingBox())!,nav=(await page.locator('.settings-side').boundingBox())!,pane=(await page.locator('main.content').boundingBox())!;const gap=parseFloat(await page.locator('.settings-layout').evaluate(el=>getComputedStyle(el).columnGap));expect(scene.width).toBeLessThanOrEqual(920);expect(Math.abs(scene.x+scene.width/2-(nav.x+nav.width+gap+pane.x+pane.width-32)/2)).toBeLessThan(2);expect(nav.y+nav.height).toBeGreaterThanOrEqual(pane.y+pane.height);}
  await page.screenshot({path:path.join(output,`feedback-section-${section}-${width}.png`)});
  if(section==='authentication'){await page.getByRole('button',{name:'修改管理密码',exact:true}).click();await expect(page.locator('.security-card input')).toHaveCount(3);await page.getByText('已连接应用（1）',{exact:true}).click();await page.locator('[data-client-details]>summary').click();if(width===1920){await page.locator('main.content').evaluate(el=>el.scrollTop=el.scrollHeight);await expect(page.getByRole('link',{name:'我的资料',exact:true})).toBeInViewport();await page.locator('main.content').evaluate(el=>el.scrollTop=0);}await page.screenshot({path:path.join(output,`feedback-section-authentication-expanded-${width}.png`)});}
  if(section==='backups'){await expect(page.locator('.backup-center .job')).toContainText('completed-synthetic-backup');if(width>768)expect((await page.getByRole('button',{name:'备份所有设置',exact:true}).boundingBox())!.width).toBeLessThan(180);await page.locator('.record summary').click();await expect(page.locator('.record')).not.toContainText('校验不等于恢复验证');await page.getByRole('button',{name:'ZIP 校验说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toContainText('仅核对 ZIP 完整性与清单');await page.screenshot({path:path.join(output,`feedback-section-backups-help-${width}.png`)});await page.keyboard.press('Escape');}
  matrix.push({section,viewport:width,initial:true,expanded:['authentication','backups'].includes(section)});
 }
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);expect(f.writes).toEqual([]);await writeFile(path.join(output,`settings-matrix-${width}.json`),JSON.stringify(matrix,null,2));
});
for(const width of [1920,390])test(`feedback project contextual help ${width}`,async({page})=>{
 const f=await setup(page,false,false,true);await page.setViewportSize({width,height:900});await page.goto('/notes?doc='+folderId);await expect(page.locator('.project-files')).toBeVisible();if(width>768){const notes=(await page.locator('.notes-page').boundingBox())!,files=(await page.locator('.project-files').boundingBox())!;expect(files.x+files.width).toBe(notes.x+notes.width);}await expect(page.locator('.project-files')).not.toContainText('项目内移动或重命名');await page.getByRole('button',{name:'项目相对引用说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toContainText('不会自动修复动态路径');await page.screenshot({path:path.join(output,`feedback-project-files-help-${width}.png`)});await page.keyboard.press('Escape');
 await page.goto('/notes?doc='+projectId);await expect(page.locator('.web-project-pane')).toBeVisible();await expect(page.locator('.web-project-pane')).toContainText('API 503');await expect(page.locator('.web-project-pane')).not.toContainText('网页与主站隔离');await page.getByRole('button',{name:'网页运行进度说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toContainText('浏览器数据库');await page.screenshot({path:path.join(output,`feedback-project-runtime-help-${width}.png`)});expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const [width,height] of [[1365,420],[682,350],[320,400]])test(`feedback short viewport ${width}x${height}`,async({page})=>{
 const f=await setup(page);await page.setViewportSize({width,height});await page.goto('/settings');await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await expect(page.locator('#profile-email-draft')).toBeVisible();await page.getByRole('button',{name:'暂不验证保存说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toBeVisible();const help=(await page.getByRole('tooltip').boundingBox())!;expect(help.y).toBeGreaterThanOrEqual(0);expect(help.y+help.height).toBeLessThanOrEqual(height);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:path.join(output,`feedback-short-${width}-${height}.png`)});expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
test('feedback fixture rejects unknown HTTP queries, methods and WebSockets',async({page})=>{
 const f=await setup(page);await page.goto('/settings');await expect(page.locator('#profile-name')).toBeVisible();const result=await page.evaluate(async()=>{const send=async(url:string,method='GET')=>{try{return (await fetch(url,{method})).status;}catch{return 'blocked';}};const values=await Promise.all([send('/auth/me?unknown=1'),send('/unknown-fixture-route'),send('/auth/email/send-code','POST')]);await new Promise<void>(resolve=>{const ws=new WebSocket(location.origin.replace('http','ws')+'/ws/unlisted');ws.onclose=()=>resolve();ws.onerror=()=>resolve();});await new Promise<void>(resolve=>{const ws=new WebSocket('wss://blocked.invalid/ws/notifications');ws.onclose=()=>resolve();ws.onerror=()=>resolve();});return values;});expect(result).toEqual([500,500,'blocked']);expect(f.unknown).toEqual(['GET /auth/me?unknown=1','GET /unknown-fixture-route','POST /auth/email/send-code','ws://127.0.0.1:15327/ws/unlisted','wss://blocked.invalid/ws/notifications']);expect(f.errors).toEqual([]);
});
async function settleLayout(page:Page){await page.mouse.move(0,0);await page.evaluate(async()=>{await Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});}
for(const width of [1920,1365,390,320])test(`feedback scene boundary and centered prose ${width}`,async({page})=>{
 const f=await setup(page,false,true);await page.setViewportSize({width,height:900});await page.goto('/settings');await expect(page.locator('#profile-name')).toBeVisible();
 if(width>768){
  const pane=(await page.locator('main.content').boundingBox())!,nav=(await page.locator('.settings-side').boundingBox())!,scene=(await page.locator('.settings-scene').boundingBox())!,heading=(await page.locator('.st-secondary-heading').boundingBox())!;
  expect(nav.y).toBe(pane.y);expect(nav.y+nav.height).toBe(pane.y+pane.height);
  expect(heading.y).toBeGreaterThanOrEqual(36);
  const rightStart=nav.x+nav.width+parseFloat(await page.locator('.settings-layout').evaluate(el=>getComputedStyle(el).columnGap));
  const rightEnd=pane.x+pane.width-32;expect(Math.abs((scene.x+scene.width/2)-(rightStart+rightEnd)/2)).toBeLessThan(2);
 }
 const emailRow=page.locator('.profile-email-current');
 if(width===1920){const email=(await page.locator('.profile-email-address').boundingBox())!,edit=(await page.getByRole('button',{name:'修改邮箱',exact:true}).boundingBox())!;expect(Math.abs(email.y+email.height/2-edit.y-edit.height/2)).toBeLessThan(2);}
 await page.screenshot({path:path.join(output,`feedback-profile-${width}.png`),fullPage:true});
 await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await expect(page.locator('#profile-email-draft')).toBeVisible();await expect(page.locator('.profile-email-address')).toHaveCount(0);await expect(page.locator('#profile-email-error')).toHaveCount(0);await page.screenshot({path:path.join(output,`feedback-email-edit-${width}.png`),fullPage:true});await page.locator('#profile-email-draft').fill('saved-without-smtp@example.test');await page.getByRole('button',{name:'暂不验证并保存',exact:true}).click();await expect(page.locator('#profile-email-draft')).toHaveCount(0);await expect(page.locator('.profile-email-address')).toHaveText('saved-without-smtp@example.test');await expect(page.getByRole('button',{name:'邮箱未验证',exact:true})).toBeVisible();await expect(page.locator('#profile-email-error')).toHaveCount(0);await page.screenshot({path:path.join(output,`feedback-email-saved-no-smtp-${width}.png`)});
 await page.goto('/status');await expect(page.locator('.nodes-view .grid > .card')).toHaveCount(2);await settleLayout(page);
 if(width>768){const pane=(await page.locator('main.content').boundingBox())!,nav=(await page.locator('.servers-bar').boundingBox())!;expect(nav.y).toBe(pane.y);expect(nav.y+nav.height).toBe(pane.y+pane.height);}
 await page.screenshot({path:path.join(output,`feedback-servers-${width}.png`),fullPage:true});expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});

async function inPane(page:Page,selector:string){
 const pane=(await page.locator('.settings-scene').boundingBox())!;
 for(const rect of await page.locator(selector).evaluateAll(els=>els.filter(e=>e.getClientRects().length).map(e=>e.getBoundingClientRect().toJSON()))){expect(rect.x).toBeGreaterThanOrEqual(pane.x-1);expect(rect.right).toBeLessThanOrEqual(pane.x+pane.width+1);}
}
for(const width of [1920,1365,390,320])test(`integrated actual App website code and metadata roundtrip ${width}`,async({page})=>{
 const f=await setup(page,false,false,false,{integrated:true});await page.setViewportSize({width,height:width>600?960:640});
 await page.goto('/settings?section=navigation&module=owned');const editor=page.locator('form.inline-editor');await expect(editor).toBeVisible();await editor.locator('.custom>summary').click();await editor.locator('.auth-options>summary').click();await expect(editor.locator('textarea')).toHaveCount(2);
 await expect(editor).not.toContainText(/仅由 Stella 后端发送|这里是当前应用的代码|另有旧版未应用内容|查看当前生效代码|清除已保存凭据|回退上一版本/);
 await inPane(page,'.inline-editor textarea,.inline-editor input,.inline-editor button');
 await page.getByRole('button',{name:'已保留旧草稿说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toContainText('另有旧版未应用内容保留在服务器');const hint=(await page.getByRole('tooltip').boundingBox())!;expect(hint.x).toBeGreaterThanOrEqual(0);expect(hint.x+hint.width).toBeLessThanOrEqual(width);await page.screenshot({path:path.join(output,`integrated-website-help-${width}.png`)});await page.keyboard.press('Escape');
 await page.getByLabel('自定义 CSS',{exact:true}).fill('/* combined saved */body{color:purple}');await editor.getByRole('button',{name:'保存',exact:true}).click();await expect(editor).toHaveCount(0);
 const payload=f.calls.filter(c=>c.path==='/website-settings/owned'&&c.method==='PATCH');expect(payload).toHaveLength(1);expect(payload[0]!.body.preserve_saved_draft).toBe(true);expect(payload[0]!.body.connection).toMatchObject({token:null,clear_token:false});expect(f.website.snapshot().item.injection.active.css).toBe('/* combined saved */body{color:purple}');expect(f.website.snapshot().item.injection.draft.css).toBe('/* 服务器旧独立草稿 */');
 await page.getByRole('button',{name:'编辑 合并验收网站',exact:true}).click();await editor.locator('.custom>summary').click();await expect(page.getByLabel('自定义 CSS',{exact:true})).toHaveValue('/* combined saved */body{color:purple}');await page.screenshot({path:path.join(output,`integrated-website-code-${width}.png`)});
 await page.getByLabel('显示名称',{exact:true}).fill('只改合并名称');await editor.getByRole('button',{name:'保存',exact:true}).click();await expect(editor).toHaveCount(0);const patches=f.calls.filter(c=>c.path==='/website-settings/owned'&&c.method==='PATCH');expect(patches).toHaveLength(2);expect(patches[1]!.body).not.toHaveProperty('custom');expect(f.calls.some(c=>/injection\/(apply|rollback|validate)/.test(c.path))).toBe(false);
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);await writeFile(path.join(output,`integrated-website-${width}.json`),JSON.stringify({calls:f.calls,state:f.website.snapshot()},null,2));
});
for(const width of [1920,1365,390,320])test(`integrated actual App services independent saves and one leave guard ${width}`,async({page})=>{
 const f=await setup(page,false,false,false,{integrated:true});await page.setViewportSize({width,height:width>600?960:640});await page.goto('/settings?section=access');await expect(page).toHaveURL(/section=services/);
 await expect(page.getByLabel('公网主站地址',{exact:true})).toHaveValue('https://stella.example.test');await expect(page.getByLabel('服务器公网地址',{exact:true})).toHaveValue('agent.example.test');await expect(page.locator('.mail-service input').first()).toBeVisible();await expect(page.locator('.mail-service')).not.toContainText('站内通知通过侧栏铃铛查看');await page.getByRole('button',{name:'邮箱服务与通知说明',exact:true}).click();await expect(page.getByRole('button',{name:'邮箱服务与通知说明',exact:true})).toBeInViewport();await expect(page.getByRole('tooltip')).toContainText('网站外发邮件');const smtpHint=(await page.getByRole('tooltip').boundingBox())!;expect(smtpHint.x).toBeGreaterThanOrEqual(0);expect(smtpHint.x+smtpHint.width).toBeLessThanOrEqual(width);await page.screenshot({path:path.join(output,`integrated-smtp-help-${width}.png`)});await page.keyboard.press('Escape');
 await expect(page.getByRole('button',{name:'应用节点地址',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'应用设置',exact:true})).toHaveCount(0);await inPane(page,'.access-settings input,.public-host-row input,.mail-service input,.mail-service button');
 if(width>600){const rects=await page.locator('[aria-label="公网主站地址"],[aria-label="内网主站地址"],[aria-label="服务器公网地址"]').evaluateAll(els=>els.map(e=>e.getBoundingClientRect().toJSON()));expect(rects).toHaveLength(3);for(const r of rects){expect(r.x).toBe(rects[0]!.x);expect(r.width).toBeLessThanOrEqual(380);}}
 await page.screenshot({path:path.join(output,`integrated-services-${width}.png`),fullPage:true});await page.getByLabel('服务器公网地址',{exact:true}).fill('changed-agent.example.test');await page.getByLabel('内网主站地址',{exact:true}).fill('https://changed-private.test');
 if(width>768)await page.getByRole('link',{name:'网站与访问',exact:true}).click();else{await page.locator('.settings-mobile-nav .dd-btn').click();await page.getByRole('option',{name:/^网站与访问/}).click();}await expect(page.getByRole('dialog')).toHaveCount(1);await page.getByRole('button',{name:'继续编辑',exact:true}).click();await expect(page.getByLabel('内网主站地址',{exact:true})).toHaveValue('https://changed-private.test');
 await page.getByRole('button',{name:'应用节点地址',exact:true}).click();await expect(page.getByRole('button',{name:'应用节点地址',exact:true})).toHaveCount(0);await page.getByRole('button',{name:'检查设置',exact:true}).click();await page.getByRole('button',{name:'应用设置',exact:true}).click();await expect(page.getByRole('button',{name:'检查设置',exact:true})).toHaveCount(0);
 expect(f.website.snapshot().agentHost).toBe('changed-agent.example.test');expect(f.website.snapshot().access).toEqual({revision:5,enabled:true,public_origin:'https://stella.example.test',private_origin:'https://changed-private.test'});expect(f.calls.filter(c=>c.method==='PUT').map(c=>c.path)).toEqual(['/config/public-host','/config/access-entries']);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);await writeFile(path.join(output,`integrated-services-${width}.json`),JSON.stringify({calls:f.calls,state:f.website.snapshot()},null,2));
});
for(const width of [1920,320])test(`integrated management unlock and original OIDC callback cancel/leave ${width}`,async({page})=>{
 const f=await setup(page,false,false,false,{integrated:true,locked:true});await page.setViewportSize({width,height:width>600?960:640});await page.goto('/settings?section=authentication');await expect(page.locator('.provider-card')).toContainText('解锁管理权限后');await expect(page.locator('[data-connected-apps]')).toHaveCount(0);await page.getByRole('button',{name:'解锁管理权限',exact:true}).click();await page.locator('.security-card input[type=password]').fill('synthetic-fixture-only');await page.getByRole('button',{name:'确认安全变更',exact:true}).click();await expect(page.locator('.security-card')).toContainText('管理权限已解锁');await page.locator('[data-connected-apps]>summary').click();await page.locator('[data-client-details]>summary').click();await page.getByRole('button',{name:'编辑',exact:true}).click();
 await expect(page.locator('.callback-editor')).not.toContainText('分别填写此应用');await page.getByRole('button',{name:'应用地址与回调说明',exact:true}).focus();await expect(page.getByRole('tooltip')).toContainText('不会自动补齐其他地址的路径');await page.keyboard.press('Escape');await expect(page.getByLabel('应用地址 1',{exact:true})).toHaveValue('https://app.example.test');await expect(page.getByLabel('回调用途路径 1',{exact:true})).toHaveValue('/auth/login');await page.getByLabel('回调用途路径 1',{exact:true}).fill('/auth/login\n/new-exact-callback');await page.screenshot({path:path.join(output,`integrated-oidc-${width}.png`),fullPage:true});await inPane(page,'.callback-editor input,.callback-editor textarea,.provider-card form button');
 if(width>768)await page.getByRole('link',{name:'服务与通知',exact:true}).click();else{await page.locator('.settings-mobile-nav .dd-btn').click();await page.getByRole('option',{name:/^服务与通知/}).click();}await expect(page.getByRole('alertdialog')).toHaveCount(1);await page.getByRole('button',{name:'继续编辑',exact:true}).click();await expect(page.getByLabel('回调用途路径 1',{exact:true})).toHaveValue('/auth/login\n/new-exact-callback');await page.locator('.provider-card form').getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('.callback-editor')).toHaveCount(0);
 expect(f.calls.filter(c=>c.method!=='GET'&&!['/auth/activity','/auth/admin/unlock'].includes(c.path))).toEqual([]);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);await writeFile(path.join(output,`integrated-oidc-${width}.json`),JSON.stringify({calls:f.calls.map(c=>c.path==='/auth/admin/unlock'?{...c,body:'synthetic-redacted'}:c)},null,2));
});
test('integrated native Chromium 200 percent zoom: profile, appearance and website actions',async()=>{
 const profile=await mkdtemp(path.join(tmpdir(),'z2-'));await mkdir(path.join(profile,'Default'));
 // Native settings API, not CSS zoom or viewport emulation.
 const context=await chromium.launchPersistentContext(profile,{executablePath:'/usr/sbin/google-chrome-stable',viewport:null,args:['--no-sandbox','--window-size=1365,900'],reducedMotion:'reduce'});
 try{const page=context.pages()[0]!;await page.goto('chrome://settings/appearance');await page.evaluate(()=>new Promise<void>(resolve=>(window as any).chrome.settingsPrivate.setDefaultZoom(2,resolve)));const f=await setup(page,false,false,false,{integrated:true});await page.goto(base+'/settings?section=profile');await expect(page.locator('#profile-name')).toBeVisible();const cdp=await context.newCDPSession(page);const window=await cdp.send('Browser.getWindowForTarget');const physicalHeight=await page.evaluate(()=>innerHeight*devicePixelRatio);if(physicalHeight!==900)await cdp.send('Browser.setWindowBounds',{windowId:window.windowId,bounds:{height:window.bounds.height!+900-physicalHeight}});const zoom=await page.evaluate(()=>({inner:innerWidth,outer:outerWidth,dpr:devicePixelRatio,height:innerHeight}));expect(zoom.dpr).toBe(2);expect(Math.abs(zoom.inner*2-zoom.outer)).toBeLessThanOrEqual(2);
 await page.getByRole('button',{name:'修改邮箱',exact:true}).click();await expect(page.getByRole('button',{name:'发送验证码',exact:true})).toHaveCount(0);await page.getByRole('button',{name:'暂不验证保存说明',exact:true}).focus();const help=(await page.getByRole('tooltip').boundingBox())!;expect(help.y+help.height).toBeLessThanOrEqual(zoom.height);await writeFile(path.join(output,'integrated-native200-profile.png'),Buffer.from((await (await context.newCDPSession(page)).send('Page.captureScreenshot',{captureBeyondViewport:false,fromSurface:true})).data,'base64'));await page.keyboard.press('Escape');
 await page.goto(base+'/settings?section=appearance');await page.getByRole('button',{name:'调色：主按钮',exact:true}).click();await page.getByLabel('颜色值',{exact:true}).fill('#A7CDF5');await expect(page.locator('.appearance-sync')).toContainText('账号已同步');await page.getByRole('button',{name:'重置此颜色',exact:true}).focus();const panel=(await page.locator('.color-panel').boundingBox())!,reset=(await page.getByRole('button',{name:'重置此颜色',exact:true}).boundingBox())!;expect(panel.y).toBeGreaterThanOrEqual(0);expect(panel.y+panel.height).toBeLessThanOrEqual(zoom.height);expect(reset.y+reset.height).toBeLessThanOrEqual(zoom.height);await writeFile(path.join(output,'integrated-native200-picker.png'),Buffer.from((await (await context.newCDPSession(page)).send('Page.captureScreenshot',{captureBeyondViewport:false,fromSurface:true})).data,'base64'));await page.keyboard.press('Escape');
 await page.goto(base+'/settings?section=navigation&module=owned');await page.locator('.custom>summary').click();await inPane(page,'.inline-editor textarea,.inline-editor button');await page.getByRole('button',{name:'保存',exact:true}).scrollIntoViewIfNeeded();await expect(page.getByRole('button',{name:'保存',exact:true})).toBeInViewport();await writeFile(path.join(output,'integrated-native200-website.png'),Buffer.from((await (await context.newCDPSession(page)).send('Page.captureScreenshot',{captureBeyondViewport:false,fromSurface:true})).data,'base64'));expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);await writeFile(path.join(output,'integrated-native200.json'),JSON.stringify({zoom,calls:f.calls},null,2));
 }finally{await context.close();await rm(profile,{recursive:true,force:true});}
});

for(const width of [1920,1365])test(`integrated populated node detail tabs and full-width pane ${width}`,async({page})=>{
 const f=await setup(page,false,true,false,{integrated:true});await page.setViewportSize({width,height:960});const matrix=[];
 for(const tab of ['overview','network','services']){await page.goto('/status/1?tab='+tab);await expect(page.locator('.detail-body')).toBeVisible();await page.waitForLoadState('networkidle');await settleLayout(page);const rect=await page.locator('.servers-page>.view-body').boundingBox();expect(rect!.width).toBeGreaterThan(width===1920?1300:750);await page.screenshot({path:path.join(output,`integrated-node-${tab}-${width}.png`)});matrix.push({url:new URL(page.url()).pathname+new URL(page.url()).search,rect});}
 expect(f.calls.filter(c=>c.method==='POST'&&c.path.includes('scan'))).toEqual([]);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);await writeFile(path.join(output,`integrated-node-${width}.json`),JSON.stringify({matrix,calls:f.calls},null,2));
});
test('integrated full-page route intentions: home, all guides, API, builtin editors and external shell',async({page})=>{
 const f=await setup(page,false,false,true,{integrated:true});await page.setViewportSize({width:1365,height:960});const matrix=[];
 const routes=['/','/help','/help?section=api',...['start','notes','import','web-projects','settings','preferences','backup','websites','services','servers'].map(id=>'/help?section=guide&page='+id),...['home','notes','servers','settings','status'].map(id=>'/settings?section=navigation&module='+id),'/apps/owned','/integrated-not-found'];
 for(const url of routes){await page.goto(url);await page.waitForLoadState('networkidle');await settleLayout(page);await expect(page.locator('main.content')).toBeVisible();expect(await page.locator('main.content').innerText()).not.toBe('');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:path.join(output,`integrated-route-${matrix.length}.png`)});matrix.push({requested:url,actual:new URL(page.url()).pathname+new URL(page.url()).search});}
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);await writeFile(path.join(output,'integrated-routes.json'),JSON.stringify({matrix,calls:f.calls},null,2));
});
