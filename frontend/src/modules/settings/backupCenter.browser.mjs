// Isolated browser/HTTP fixture, NOT production/backend restore acceptance.
// Run from frontend with pinned Node 23, NODE_ENV unset. No installs or production proxy.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium,expect} from '@playwright/test';
import JSZip from 'jszip';
import {createHash} from 'node:crypto';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {execFileSync} from 'node:child_process';
const root=resolve(import.meta.dirname,'../../..');
const output=process.env.BACKUP_EVIDENCE_DIR || join(process.env.TMPDIR,'stella-backup-center-frontend-20261017');
await mkdir(output,{recursive:true});
const json=(res,body,status=200)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(status===204?'':JSON.stringify(body));};
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const archives={};
for(const scope of ['settings','all']){const zip=new JSZip();zip.file('fixture-manifest.json',JSON.stringify({fixture:true,scope}));archives[scope]=await zip.generateAsync({type:'nodebuffer'});}
const record=(scope,id,filename)=>({id,filename,scope,created_at:'2026-10-17T12:00:00Z',bytes:archives[scope].length,sha256:digest(archives[scope]),verified:true});
let config,records,job,tick,sequence=0,denyPatch=false,denyPreferences=false,preferences;
function reset(){config={revision:1,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0};records=[record('settings','seed-settings','stella-settings-20261017-200000.zip'),record('all','seed-all','stella-all-20261017-190000.zip')];job=null;tick=0;denyPatch=false;denyPreferences=false;preferences={revision:0,appearance:'A',home:{theme:'daybreak',particles:'stars',bgImage:'',bgCrop:{cx:.5,cy:.5,w:1,h:1},siteTitle:'StellaHaven',signature:'',meetDate:'2026-05-31',live2d:true,avatar:'/avatar.png'},ui:{backgroundQuality:'compressed1',sidebarFold:false,serversFold:false,toolsOpen:false,worldMapCollapsed:false,monitorMode:'chart',noteEditMode:'rich',listFold:false,driveBackground:'solid'}};}
reset();
const requests=[],unknown=[],screenshots=[],errors=[];
const entry=`import {createApp,h} from 'vue';
import {createRouter,createWebHistory,RouterView} from 'vue-router';
import {createPinia} from 'pinia';
import '@fontsource-variable/inter';import '/src/style.css';import '/src/stores/appearance.ts';
import SettingsPage from '/src/modules/settings/SettingsPage.vue';
import AdminElevationModal from '/src/shell/AdminElevationModal.vue';
import {auth,security,securityChecked} from '/src/modules/home/auth.ts';
import {homeSettings} from '/src/modules/home/settings.ts';
import {startClientPreferenceSync,clientPreferenceSync} from '/src/modules/settings/clientPreferenceSync.ts';
Object.assign(auth,{me:{id:'fixture-owner',username:'fixture',display_name:'云曦',is_admin:true,avatar_url:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/%3E'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1});
Object.assign(security,{enabled:true,configured:true,elevated:true,expires_at:null,setup_required:false});securityChecked.value=true;
startClientPreferenceSync();window.__preferenceFixture={homeSettings,clientPreferenceSync};
const router=createRouter({history:createWebHistory(),routes:[{path:'/settings',component:SettingsPage}]});
await router.isReady().catch(()=>{});
const app=createApp({render:()=>h('main',{style:'padding:28px 24px;max-width:100%;min-width:0'},[h(RouterView),h(AdminElevationModal)])});app.use(createPinia());app.use(router);app.mount('#app');`;
// router.isReady must run after installing the router, not before app.use.
const fixtureEntry=entry.replace("await router.isReady().catch(()=>{});",'');
const server=await createServer({root,configFile:false,cacheDir:join(output,'vite-cache'),plugins:[vue(),{name:'backup-center-only-fixture',resolveId(id){if(id==='/backup-fixture-entry.js')return id;},load(id){if(id==='/backup-fixture-entry.js')return fixtureEntry;},configureServer(server){server.middlewares.use(async(req,res,next)=>{
  const url=new URL(req.url,'http://fixture.invalid');
  if(url.pathname==='/settings'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end('<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stella 设置</title></head><body><div id="app"></div><script type="module" src="/backup-fixture-entry.js"></script></body></html>');return;}
  if(!/^\/(operations|auth|config|navigation|notes-preferences|homebg)\b/.test(url.pathname))return next();
  const method=req.method,bodyText=await (async()=>{let body='';for await(const chunk of req){body+=chunk;if(body.length>16384)throw Error('fixture body limit');}return body;})();const body=bodyText?JSON.parse(bodyText):null;requests.push({path:url.pathname,method,body});
  if(url.pathname==='/auth/sessions'||url.pathname==='/auth/avatars'){json(res,[]);return;}
  if(url.pathname==='/config/public-host'){json(res,{value:''});return;}
  if(url.pathname==='/auth/security'){json(res,{enabled:true,configured:true,elevated:true,expires_at:null,single_user:true,setup_required:false});return;}
  if(url.pathname==='/operations/backups/client-preferences'){
    if(method==='PUT'){
      if(denyPreferences){json(res,{detail:'fixture preferences unavailable'},503);return;}
      if(body.expected_revision!==preferences.revision){json(res,{detail:{code:'revision_conflict'}},409);return;}
      const {expected_revision,...content}=body;preferences={...content,revision:expected_revision+1};
    }
    json(res,preferences);return;
  }
  if(url.pathname==='/operations/backups'&&method==='GET'){
    if(job&&['queued','running'].includes(job.state)){tick++;job.state=tick>1?'succeeded':'running';if(job.state==='succeeded'&&job.kind==='backup'){const id=`created-${++sequence}`;records.unshift(record(job.scope,id,`stella-${job.scope}-20261017-${sequence}.zip`));records=records.slice(0,2);job.record_id=id;}}
    json(res,{config,records,job,storage:{node:'stella-fixture-node',available:true,free_bytes:25769803776,error:null},next_run:config.enabled?'2026-10-23T14:15:00Z':null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}});return;
  }
  if(url.pathname==='/operations/backups/config'&&method==='PATCH'){
    if(denyPatch){json(res,{detail:{code:'admin_elevation_required',message:'管理权限已过期，请先解锁'}},403);return;}
    if(body.directory.startsWith('/denied')){json(res,{detail:{message:'服务器目录不可写：权限不足；输入已保留'}},422);return;}
    if(body.expected_revision!==config.revision){json(res,{detail:{message:'配置版本冲突，请先重新读取'}},409);return;}
    const {expected_revision,...fields}=body;config={...fields,revision:config.revision+1};json(res,config);return;
  }
  if(url.pathname==='/operations/backups'&&method==='POST'){job={id:`job-${++sequence}`,kind:'backup',scope:body.scope,state:'queued',stage:'queued',error:null,record_id:null};tick=0;json(res,job,202);return;}
  const match=url.pathname.match(/^\/operations\/backups\/([^/]+)(?:\/(download|verify|restore))?$/);
  if(match){const id=decodeURIComponent(match[1]),action=match[2],item=records.find(r=>r.id===id);if(!item){json(res,{detail:'记录不存在'},404);return;}
    if(action==='download'&&['GET','HEAD'].includes(method)){res.writeHead(200,{'Content-Type':'application/zip','Content-Length':String(archives[item.scope].length),'Content-Disposition':`attachment; filename="${item.filename}"`,'Cache-Control':'no-store'});res.end(method==='HEAD'?undefined:archives[item.scope]);return;}
    if((action==='restore'||method==='DELETE')&&body?.confirm!==item.filename){json(res,{detail:'确认文件名不匹配'},422);return;}
    if(method==='DELETE'){records=records.filter(r=>r.id!==id);json(res,null,204);return;}
    if(action==='restore'&&item.scope==='all'){json(res,{detail:{code:'maintenance_required',message:'需离线维护；以下为隔离测试入口，非生产命令。',command:'python tools/backup_fixture.py restore --archive /isolated/fixture-all.zip --target empty-fixture'}},409);return;}
    if(method==='POST'&&['verify','restore'].includes(action)){job={id:`job-${++sequence}`,kind:action==='verify'?'verify':'restore',scope:item.scope,state:'queued',stage:'queued',error:null,record_id:item.id};tick=0;json(res,job,202);return;}
  }
  unknown.push({path:url.pathname,method});json(res,{detail:'unhandled isolated fixture request'},404);
});}}],server:{host:'127.0.0.1',port:0,proxy:{},fs:{allow:[root]}},optimizeDeps:{include:['vue','vue-router','pinia']},logLevel:'warn'});
let browser;
const ownedSources=['src/api/backups.ts','src/modules/settings/BackupCenter.vue','src/modules/settings/ClientPreferenceStatus.vue','src/modules/settings/clientPreferenceController.ts','src/modules/settings/clientPreferenceContract.ts','src/modules/settings/clientPreferenceSync.ts','src/modules/settings/SettingsPage.vue','src/modules/settings/PerformanceSettings.vue','src/modules/settings/backupClientPreferences.ts','src/style.css','src/stores/appearance.ts'];
const hashes=async()=>Object.fromEntries(await Promise.all(ownedSources.map(async p=>[p,digest(await readFile(join(root,p)))])));
const before=await hashes();
try{
 await server.listen();const port=server.httpServer.address().port,origin=`http://127.0.0.1:${port}`;
 browser=await chromium.launch({executablePath:process.env.BACKUP_CHROME || '/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome',headless:true,args:['--no-sandbox'],env:{...process.env}});
 async function context(viewport,palette='A',mobile=false){const ctx=await browser.newContext({viewport,hasTouch:mobile,isMobile:mobile,deviceScaleFactor:1,reducedMotion:'reduce'});await ctx.addInitScript(p=>localStorage.setItem('stella_appearance',p),palette);await ctx.route('**/*',route=>{const url=new URL(route.request().url());return url.origin===origin?route.continue():route.abort();});const page=await ctx.newPage();page.on('pageerror',error=>errors.push(error.stack||error.message));page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text());});return {ctx,page};}
 async function shot(page,name,fullPage=true){const path=join(output,name+'.png');await page.screenshot({path,fullPage});screenshots.push(path);return path;}
 async function noOverflow(page){const result=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('.backup-center input,.backup-center select,.backup-center button,.scope-card,.panel,.backup-dialog')].filter(el=>{const r=el.getBoundingClientRect();return r.width && (r.left< -1||r.right>innerWidth+1);}).map(el=>el.outerHTML.slice(0,200))}));expect(result.document).toBeLessThanOrEqual(result.viewport);expect(result.overflow).toEqual([]);return result;}
 const {ctx,page}=await context({width:1440,height:1000});
 await page.goto(origin+'/settings?section=backups');await expect(page.getByLabel('备份目录')).toBeVisible();await expect(page.getByLabel('启用自动备份')).not.toBeChecked();expect(requests.filter(r=>r.path!=='/operations/backups/client-preferences'&&['PATCH','POST','DELETE'].includes(r.method))).toEqual([]);await expect(page.locator('[data-client-preferences]')).toContainText('服务器确认');await noOverflow(page);await shot(page,'desktop-A-default-off');
 denyPreferences=true;await page.evaluate(()=>window.__preferenceFixture.homeSettings.signature='同步失败后保留的输入');await expect(page.locator('[data-client-preferences][role="alert"]')).toContainText('本机输入已保留');await noOverflow(page);await shot(page,'desktop-A-preferences-error');denyPreferences=false;await page.getByRole('button',{name:'重试偏好同步',exact:true}).click();await expect(page.locator('[data-client-preferences]')).toContainText('服务器确认');expect(preferences.home.signature).toBe('同步失败后保留的输入');
 preferences={...preferences,revision:preferences.revision+1,home:{...preferences.home,siteTitle:'另一设备的主页'}};await page.evaluate(()=>window.__preferenceFixture.homeSettings.siteTitle='本机仍保留的输入');await expect(page.getByRole('button',{name:'保留本机偏好',exact:true})).toBeVisible();expect(await page.evaluate(()=>window.__preferenceFixture.homeSettings.siteTitle)).toBe('本机仍保留的输入');await noOverflow(page);await shot(page,'desktop-A-preferences-conflict');await page.getByRole('button',{name:'使用服务器偏好',exact:true}).click();await expect(page.locator('[data-client-preferences]')).toContainText('服务器确认');expect(await page.evaluate(()=>window.__preferenceFixture.homeSettings.siteTitle)).toBe('另一设备的主页');
 const settingsRow=page.locator('[data-backup-id="seed-settings"]');const restore=settingsRow.getByRole('button',{name:'恢复设置'});await restore.click();let dialog=page.getByRole('dialog');await expect(dialog.getByLabel('确认 ZIP 文件名')).toBeFocused();await page.keyboard.press('Shift+Tab');await expect(dialog.getByRole('button',{name:'取消',exact:true})).toBeFocused();await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(restore).toBeFocused();
 await restore.click();dialog=page.getByRole('dialog');await dialog.getByLabel('确认 ZIP 文件名').fill(records.find(r=>r.id==='seed-settings').filename);await shot(page,'desktop-A-settings-restore-modal',false);await dialog.getByRole('button',{name:'确认恢复设置',exact:true}).click();await expect(page.getByText('设置恢复已完成',{exact:true})).toBeVisible();
 await settingsRow.getByRole('button',{name:'校验 ZIP',exact:true}).click();await expect(page.getByText('ZIP 校验已完成',{exact:true})).toBeVisible();
 const dlEvent=page.waitForEvent('download');await settingsRow.getByRole('button',{name:'下载 ZIP',exact:true}).click();const download=await dlEvent;const dlPath=join(output,'fixture-download.zip');await download.saveAs(dlPath);expect(digest(await readFile(dlPath))).toBe(records.find(r=>r.id==='seed-settings').sha256);expect(JSON.parse(await (await JSZip.loadAsync(await readFile(dlPath))).file('fixture-manifest.json').async('string')).fixture).toBe(true);
 await settingsRow.getByRole('button',{name:'删除 ZIP',exact:true}).click();dialog=page.getByRole('dialog');await dialog.getByLabel('确认 ZIP 文件名').fill(records.find(r=>r.id==='seed-settings').filename);await dialog.getByRole('button',{name:'确认删除',exact:true}).click();await expect(settingsRow).toHaveCount(0);
 await page.locator('[data-backup-id="seed-all"]').getByRole('button',{name:'离线恢复',exact:true}).click();dialog=page.getByRole('dialog');await dialog.getByLabel('确认 ZIP 文件名').fill(records.find(r=>r.id==='seed-all').filename);await dialog.getByRole('button',{name:'读取离线恢复指引'}).click();await expect(dialog.getByText('python tools/backup_fixture.py restore',{exact:false})).toBeVisible();await shot(page,'desktop-A-maintenance-cli',false);await dialog.getByRole('button',{name:'关闭指引'}).click();
 for(const label of ['备份所有设置','备份全部数据']){await page.getByRole('button',{name:label,exact:true}).click();await expect(page.getByText('备份已完成',{exact:true})).toBeVisible();}expect(records).toHaveLength(2);await expect(page.getByLabel('启用自动备份')).not.toBeChecked();
 const postsBefore=requests.filter(r=>r.method==='POST').length;await page.getByLabel('备份目录').fill('/mnt/stella backups');await page.getByLabel('执行频率').selectOption('weekly');await page.getByLabel('执行星期').selectOption('4');await page.getByLabel('执行时间').fill('22:15');await page.getByLabel('时区',{exact:true}).fill('Asia/Shanghai');await page.getByLabel('启用自动备份').check();await page.getByRole('button',{name:'应用目录与计划'}).click();await expect(page.getByText('目录与计划已确认',{exact:true})).toBeVisible();expect(requests.filter(r=>r.method==='POST')).toHaveLength(postsBefore);expect(config).toMatchObject({enabled:true,directory:'/mnt/stella backups',frequency:'weekly',weekday:4,time:'22:15'});await noOverflow(page);await shot(page,'desktop-A-weekly-plan');
 await page.getByLabel('备份目录').fill('/denied/keep-this-input');await page.getByRole('button',{name:'应用目录与计划'}).click();await expect(page.getByRole('alert')).toContainText('目录不可写');await expect(page.getByLabel('备份目录')).toHaveValue('/denied/keep-this-input');await shot(page,'desktop-A-directory-error');
 denyPatch=true;await page.getByLabel('备份目录').fill('/keep-after-403');await page.getByRole('button',{name:'应用目录与计划'}).click();await expect(page.getByRole('button',{name:'解锁管理权限',exact:true})).toBeEnabled();await page.getByRole('button',{name:'解锁管理权限',exact:true}).click();await expect(page.getByRole('dialog').getByRole('heading',{name:'解锁管理权限'})).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByLabel('备份目录')).toHaveValue('/keep-after-403');await shot(page,'desktop-A-management-required');await ctx.close();
 reset();const mobile=await context({width:393,height:852},'A',true);await mobile.page.goto(origin+'/settings?section=backups');await expect(mobile.page.getByLabel('备份目录')).toBeVisible();await noOverflow(mobile.page);await shot(mobile.page,'mobile-393-A-default-off');await shot(mobile.page,'mobile-393-A-viewport',false);
 await mobile.page.getByLabel('执行频率').selectOption('weekly');await noOverflow(mobile.page);await mobile.page.locator('[data-backup-id="seed-settings"]').getByRole('button',{name:'恢复设置'}).tap();dialog=mobile.page.getByRole('dialog');await dialog.getByLabel('确认 ZIP 文件名').fill(records.find(r=>r.id==='seed-settings').filename);await noOverflow(mobile.page);await shot(mobile.page,'mobile-393-A-restore-modal',false);await mobile.page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
 await mobile.page.getByRole('button',{name:'我的资料',exact:true}).tap();await mobile.page.getByRole('button',{name:'备份与恢复',exact:true}).tap();await expect(mobile.page.getByLabel('执行频率')).toHaveValue('weekly');await mobile.ctx.close();
 reset();const blue=await context({width:1440,height:1000},'B');await blue.page.goto(origin+'/settings?section=backups');await expect(blue.page.getByLabel('备份目录')).toBeVisible();await expect(blue.page.locator('html')).toHaveAttribute('data-appearance','B');await shot(blue.page,'desktop-B-default-off');await blue.page.evaluate(()=>document.body.style.zoom='2');await noOverflow(blue.page);await shot(blue.page,'desktop-B-200percent');await blue.ctx.close();
 const expectedHttpErrors=errors.filter(message=>/^Failed to load resource: the server responded with a status of (403|409|422|503) \(/.test(message));
 const runtimeErrors=errors.filter(message=>!expectedHttpErrors.includes(message));
 expect(expectedHttpErrors).toHaveLength(5);expect(unknown).toEqual([]);expect(runtimeErrors).toEqual([]);expect(await hashes()).toEqual(before);
 const report={kind:'isolated real-browser + same-origin HTTP fixture; not production/backend acceptance',commit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--porcelain'],{cwd:root,encoding:'utf8'}).trim(),sources:before,browser:await browser.version(),screenshots,requests,unknown,errors,expectedHttpErrors,runtimeErrors,download:{path:dlPath,sha256:digest(await readFile(dlPath)),fixture:true},verified:['default GET only/off','settings/all manual exact body','plan PATCH/readback, no backup POST','ZIP authenticated HEAD + native download/hash','verify job readback','settings restore modal/job readback','DELETE confirmation/list readback','full restore maintenance_required409 instructions','directory422 retained input','403 unlock modal usable/no write replay','native tabs retain input','393px/reflow/200%/A+B']};await writeFile(join(output,'browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({success:true,report:join(output,'browser-report.json'),screenshots,requests:requests.length,errors},null,2));
}finally{await browser?.close();await server.close();}
