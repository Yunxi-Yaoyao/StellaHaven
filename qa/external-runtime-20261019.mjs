import {captureOwnSession,logoutOwnSession} from './own-session.mjs';
let ownSID;
import {chromium} from '/opt/hermes-workstation/stella-preview-20261018/frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
const base='https://stella-dev.p.xiya.live'
const out='/opt/hermes-workstation/docs/Stella-反馈梳理-20261018/external-runtime'
const priv='/var/lib/stella-external-runtime-20261019/private'
const cred=JSON.parse(fs.readFileSync('/var/lib/stella-preview-20261018/private/owner.json','utf8'))
const fixture=JSON.parse(fs.readFileSync('/var/lib/stella-preview-20261018/private/fixture.json','utf8'))
const token=JSON.parse(fs.readFileSync(priv+'/token.json','utf8')).token
const report={origin:base,steps:[],normal_ui_login:false,pageErrors:[],blockedExternal:[]}
let objects=fs.existsSync(out+'/OBJECTS.json')?JSON.parse(fs.readFileSync(out+'/OBJECTS.json','utf8')):{}
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome-stable',headless:true,args:['--no-sandbox','--no-proxy-server']})
const ctx=await browser.newContext({viewport:{width:1440,height:960},ignoreHTTPSErrors:false})
await ctx.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin===base||(/^https:\/\/(app-dev-|pages-dev\.)/.test(u.origin)&&u.hostname.endsWith('.p.xiya.live'))||['blob:','data:'].includes(u.protocol))return route.continue();report.blockedExternal.push(u.hostname+u.pathname);return route.abort()})
const page=await ctx.newPage();page.on('pageerror',e=>report.pageErrors.push(e.message))
const save=()=>{fs.writeFileSync(out+'/PROVISION.json',JSON.stringify(report,null,2));fs.writeFileSync(out+'/OBJECTS.json',JSON.stringify(objects,null,2))}
async function api(method,path,data,expected=200){const r=await ctx.request.fetch(base+path,{method,data,headers:{Origin:base}});report.steps.push({method,path,status:r.status()});if(r.status()!==expected){report.last_failure={method,path,status:r.status(),body:await r.text()};throw Error(method+' '+path+' '+r.status())}return r.status()===204?null:r.json()}
try{
 await page.goto(base+'/notes',{waitUntil:'domcontentloaded'});
 await page.getByRole('dialog',{name:'Stella 登录'}).waitFor();
 await page.locator('input[autocomplete=username]').fill(cred.username);
 await page.locator('input[autocomplete=current-password]').fill(cred.password);
 const login=page.waitForResponse(r=>new URL(r.url()).pathname==='/auth/login'&&r.request().method()==='POST');
 await page.getByRole('button',{name:'回港',exact:true}).click();assert.equal((await login).status(),200);
 await page.getByRole('dialog',{name:'Stella 登录'}).waitFor({state:'hidden'});report.normal_ui_login=true;ownSID=await captureOwnSession(ctx,base);
 assert.equal((await api('GET','/auth/me')).id,fixture.owner_id);
 await api('POST','/auth/admin/unlock',{password:cred.management_password});
 const templates=await api('GET','/website-templates');
 const list=Array.isArray(templates)?templates:[...(templates.builtin||templates.presets||[]),...(templates.user||[])];
 const preset=list.find(x=>x.id==='openlist');assert(preset,'No OpenList preset');
 if(!objects.module_id){
  const incoming={...preset.draft,address:'http://127.0.0.1:25444/isolated-test',name:'TEST · 独立 OpenList · 20261019',background:'home',idempotency_key:'external-runtime-openlist-20261019',connection:{...preset.draft.connection,transport:'proxy',auth_mode:'header',token,injection_delivery:'proxy'}};
  const res=await api('POST','/website-settings',incoming,201);const mod=res.module||res.website||res;objects.module_id=mod.id;objects.target_id=mod.target_id;objects.module_origin=mod.origin;save();
 }
 if(process.env.STELLA_EXTERNAL_APPLY==='1'&&objects.module_id){
  const incoming={...preset.draft,address:'http://127.0.0.1:25444/isolated-test',name:'TEST · 独立 OpenList · 20261019',background:'home',connection:{...preset.draft.connection,transport:'proxy',auth_mode:'header',token,injection_delivery:'proxy'}};
  await api('PATCH','/website-settings/'+objects.module_id,incoming);report.owned_snapshot_reapplied=true;
 }
 const mod=await api('GET','/external-modules/'+objects.module_id);assert.equal(mod.name,'TEST · 独立 OpenList · 20261019');objects.module_origin=mod.origin;objects.target_id=mod.target_id;report.registered_module_readback=true;report.snapshot_exact_parent_origins=['https://stella-dev.p.xiya.live','https://stella-alt-dev.p.xiya.live'].map(origin=>({origin,present:mod.injection.active.js.includes(origin)}));save();
 if(!objects.workspace_id){const ws=await api('POST','/workspaces/',{user_id:fixture.owner_id,name:'TEST · 外站真实运行验收 · 20261019'},201);objects.workspace_id=ws.id;save()}
 if(!objects.project_id){
  const r=await ctx.request.post(base+'/web-projects/import',{headers:{Origin:base},multipart:{workspace_id:objects.workspace_id,import_id:'1229fd93-cdfb-4907-9e8a-59925ed52240',entry:'index.html',file:{name:'external-state.zip',mimeType:'application/zip',buffer:fs.readFileSync('/var/lib/stella-external-runtime-20261019/external-state.zip')}}});
  report.steps.push({method:'POST',path:'/web-projects/import',status:r.status()});if(!r.ok()){report.last_failure={path:'/web-projects/import',status:r.status(),body:await r.text()};throw Error('import failed')};const p=await r.json();objects.project_id=p.id;save();
 }
 await api('GET','/web-projects/'+objects.project_id);report.real_import_readback=true;
 const launch=await api('POST','/web-projects/'+objects.project_id+'/launch',{});assert.equal(launch.target_origin,'https://pages-dev.p.xiya.live');report.pages_launch_passed=true;
 // Capabilities stay process/private, never in reports.
 fs.writeFileSync(priv+'/launch.json',JSON.stringify(launch),{mode:0o600});
 report.module_launch=await api('POST','/external-modules/'+objects.module_id+'/launch',{});delete report.module_launch.fields;
 report.complete=true;
}catch(e){report.error=e.message;process.exitCode=1}finally{try{report.logout=await logoutOwnSession(ctx,base,ownSID)}catch(e){report.logout_error=e.message;process.exitCode=1}finally{save();await browser.close();console.log(JSON.stringify(report,null,2));}}
