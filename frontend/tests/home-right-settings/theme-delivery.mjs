// Real App/theme/Notes rendering; offline fixtures only, no production proxy.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import ts from 'typescript';
import {chromium} from '@playwright/test';
const root=process.cwd(),out=process.env.HOME_SETTINGS_EVIDENCE;
assert(out);fs.mkdirSync(out,{recursive:true});
const port=15579,MAIN=`http://127.0.0.1:${port}`;
const fixture=path.join(root,'node_modules/.tmp/home-theme-harness.mjs');fs.mkdirSync(path.dirname(fixture),{recursive:true});
fs.writeFileSync(fixture,ts.transpileModule(fs.readFileSync('e2e/experience-independent-harness.ts','utf8').replaceAll('127.0.0.1:15487',`127.0.0.1:${port}`),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText);
const {setup}=await import(fixture);
const server=await createServer({root,configFile:false,envDir:false,plugins:[vue()],cacheDir:out+'/vite',optimizeDeps:{include:['html2canvas','jspdf','jszip']},server:{host:'127.0.0.1',port,strictPort:true,proxy:{},hmr:false}});
const files=['src/style.css','index.html','src/modules/home/HomePage.vue','src/modules/home/settings.ts','src/modules/home/BgManager.vue','src/modules/home/theme.css','src/modules/home/themes/HomeDaybreak.vue','src/modules/home/themes/HomeClassic.vue','src/shell/SettingsPanel.vue','tests/home-right-settings/theme-delivery.mjs'];
const hashes=()=>Object.fromEntries(files.map(f=>[f,fs.existsSync(f)?createHash('sha256').update(fs.readFileSync(f)).digest('hex'):null]));
const report={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),dirty:execFileSync('git',['status','--short'],{encoding:'utf8'}),before:hashes(),checks:[],failures:[],viewports:[]};
const check=(name,fn)=>{try{fn();report.checks.push(name);}catch(e){report.failures.push({name,error:e.message});}};
const rgb=s=>s.startsWith('#')?[1,3,5].map(i=>parseInt(s.slice(i,i+2),16)):s.match(/[\d.]+/g).slice(0,3).map(Number);
const lum=s=>rgb(s).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
const contrast=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
const snapshot=page=>page.evaluate(()=>{const s=getComputedStyle(document.documentElement);return Object.fromEntries(['--bg-base','--bg-panel','--bg-raised','--text-hi','--text-lo','--text-faint','--accent'].map(k=>[k,s.getPropertyValue(k).trim()]));});
let browser;
try{
 await server.listen();browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});
 for(const viewport of [{width:1440,height:1000},{width:393,height:852}]){
  const context=await browser.newContext({viewport});const page=await context.newPage();page.setDefaultTimeout(8000);
  const h=await setup(page);const receipt={viewport,unknown:h.unknown,errors:h.errors,consoleErrors:h.consoleErrors,requests:[],palettes:{},frameColors:[]};report.viewports.push(receipt);
  page.on('request',r=>receipt.requests.push({url:r.url(),method:r.method()}));
  const route=(p,fn)=>context.route(u=>u.origin===MAIN&&u.pathname===p,fn);
  const img='<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#29272c"/></svg>';
  for(const p of ['/qa-pattern.svg','/avatar.png'])await route(p,r=>r.fulfill({contentType:'image/svg+xml',body:img}));
  await context.route(MAIN+'/@fs/**',r=>r.continue());
  await context.route('https://ipinfo.io/json',r=>r.fulfill({json:{ip:'192.0.2.1',city:'演示地点',country:'CN'}}));
  await context.route('https://api.ip.sb/geoip',r=>r.fulfill({json:{ip:'192.0.2.1',city:'演示地点',country:'CN'}}));
  await route('/homebg/',r=>r.fulfill({json:[{id:'qa-bg',name:'演示背景',url:MAIN+'/qa-pattern.svg',ext:'.svg',isDefault:true,media:{url:MAIN+'/qa-pattern.svg',status:'ready',thumbnail:MAIN+'/qa-pattern.svg',variants:{original:MAIN+'/qa-pattern.svg'}}}]}));
  // Hold the entry module: verify the actual HTML paints dark before CSS/JS arrive.
  let release;const held=new Promise(resolve=>release=resolve);let saw;const started=new Promise(resolve=>saw=resolve);
  await route('/src/main.ts',async r=>{saw();await held;await r.continue();});
  await page.goto(MAIN,{waitUntil:'commit'});await started;
  const early=await page.evaluate(()=>({scheme:getComputedStyle(document.documentElement).colorScheme,bg:getComputedStyle(document.documentElement).backgroundColor}));receipt.early=early;
  check(`dark bootstrap ${viewport.width}`,()=>{assert.equal(early.scheme,'dark');assert(lum(early.bg)<.04);});release();
  const trigger=page.getByRole('button',{name:'主页设置',exact:true}),dialog=page.getByRole('dialog',{name:'主页设置',exact:true});await trigger.waitFor();
  const global=await snapshot(page);receipt.global=global;
  check(`global contrast ${viewport.width}`,()=>{for(const fg of ['--text-hi','--text-lo','--text-faint','--accent'])for(const bg of ['--bg-base','--bg-panel','--bg-raised'])assert(contrast(global[fg],global[bg])>=4.5,`${fg} on ${bg}: ${contrast(global[fg],global[bg])}`);});
  await context.addInitScript(()=>{window.__themeFrames=[];function sample(){if(document.body){const el=document.querySelector('.home-page');window.__themeFrames.push({body:getComputedStyle(document.body).backgroundColor,home:el?getComputedStyle(el).backgroundColor:null});}window.__themeRAF=requestAnimationFrame(sample);}sample();});
  try{
   for(const [key,name,color] of [['nightfall','夜泊','rgb(201, 212, 232)'],['classic','经典','rgb(195, 169, 237)']]){
    await trigger.click();await dialog.getByRole('button',{name:new RegExp('^'+name)}).click();await page.keyboard.press('Escape');
    const target=key==='nightfall'?'.daybreak.night .title':'.home-page .name';await page.locator(target).waitFor();await page.waitForTimeout(700);
    const palette=await page.locator('.home-page').evaluate(el=>({base:getComputedStyle(el).backgroundColor,accent:getComputedStyle(el).getPropertyValue('--accent').trim()}));
    palette.foreground=await page.locator(target).evaluate(el=>getComputedStyle(el).color);receipt.palettes[key]=palette;
    await page.screenshot({path:out+`/${key}-${viewport.width}.png`});
    check(`${key} visual palette ${viewport.width}`,()=>assert.equal(palette.foreground,color));
    assert.equal(await page.evaluate(()=>localStorage.getItem('stella_home_theme')),key);
    assert.deepEqual(await snapshot(page),global,'Home selection must not recolor global shell');
    assert.equal(h.user.home_bg,MAIN+'/qa-pattern.svg','User media identity is unchanged');
    await page.reload();await trigger.waitFor();await page.locator(target).waitFor();
    assert.equal(await page.evaluate(()=>localStorage.getItem('stella_home_theme')),key,'Theme persists across reload');
    await trigger.click();await dialog.waitFor();await page.screenshot({path:out+`/${key}-drawer-${viewport.width}.png`});
    const drawerColor=await dialog.locator('.theme-row.on .t-name').evaluate(el=>getComputedStyle(el.closest('aside')).getPropertyValue('--accent').trim());
    check(`${key} drawer shares home palette ${viewport.width}`,()=>assert.deepEqual(rgb(drawerColor),rgb(color)));
    if(key==='nightfall'){
     assert.match(await dialog.locator('.theme-row.on').innerText(),/月光银 · 夜色玻璃/);
     const tokens=await dialog.evaluate(el=>Object.fromEntries(['--bg-base','--bg-panel','--bg-raised','--text-hi','--text-lo','--text-faint','--accent'].map(k=>[k,getComputedStyle(el).getPropertyValue(k).trim()])));
     check(`moon drawer readable layers ${viewport.width}`,()=>{for(const fg of ['--text-hi','--text-lo','--text-faint','--accent'])for(const bg of ['--bg-base','--bg-panel','--bg-raised'])assert(contrast(tokens[fg],tokens[bg])>=4.5);});
     const glass=await page.locator('.daybreak.night').evaluate(el=>({pop:getComputedStyle(el).getPropertyValue('--t-pop-bg').trim(),date:getComputedStyle(el).getPropertyValue('--t-date').trim()}));
     assert.equal(glass.pop,'rgba(27,31,42,0.94)');assert.equal(glass.date,'#9aa3b5');
    }
    await dialog.getByRole('button',{name:'更换背景',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:out+`/${key}-background-${viewport.width}.png`});
    {
     await dialog.getByRole('button',{name:'更换背景',exact:true}).click();await page.locator('.bgm .thumb').waitFor();
     await page.waitForFunction(()=>getComputedStyle(document.querySelector('.bgm-mask')).opacity==='1');
     const galleryAccent=await page.locator('.bgm').evaluate(el=>getComputedStyle(el).getPropertyValue('--accent').trim());
     check(`${key} gallery shares palette ${viewport.width}`,()=>assert.deepEqual(rgb(galleryAccent),rgb(color)));
     await page.screenshot({path:out+`/${key}-gallery-${viewport.width}.png`});
     await page.locator('.bgm .thumb').dblclick();await page.locator('.crop-wrap').waitFor();
     await page.waitForFunction(()=>getComputedStyle(document.querySelector('.preview-mask')).opacity==='1');
     const cropPalette=await page.locator('.crop-pos').evaluate(el=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color}));
     check(`${key} crop remains dark ${viewport.width}`,()=>{assert(lum(cropPalette.bg)<.08);assert(contrast(cropPalette.bg,cropPalette.color)>=4.5);});
     await page.screenshot({path:out+`/${key}-crop-${viewport.width}.png`});
     await page.keyboard.press('Escape');await page.locator('.crop-wrap').waitFor({state:'hidden'});await page.keyboard.press('Escape');await dialog.waitFor();
    }
    await page.keyboard.press('Escape');
   }
   // Retained options: four themes; title only belongs to daybreak/nightfall.
   await trigger.click();assert.equal(await dialog.locator('.theme-row').count(),4);
   await dialog.getByRole('button',{name:/^破晓/}).click();await page.keyboard.press('Escape');await page.locator('.daybreak:not(.night)').waitFor();
   await trigger.click();await page.getByLabel('大标题',{exact:true}).fill('演示主页');await page.getByLabel('签名',{exact:true}).fill('今晚整理一点，明天轻松一点。');await page.getByLabel('相识起点',{exact:true}).fill('2026-01-01');
   await dialog.locator('.sec').filter({hasText:'氛围粒子'}).getByRole('button',{name:'关闭',exact:true}).click();await dialog.getByRole('button',{name:'星空点点',exact:true}).click();
   await page.keyboard.press('Escape');await page.locator('.home-page canvas').waitFor();assert.equal(await page.locator('.daybreak .title').textContent(),'演示主页');
   assert.equal(await page.evaluate(()=>localStorage.getItem('stella_home_particles')),'stars');
   assert.equal(await page.evaluate(()=>localStorage.getItem('stella_meet_date')),'2026-01-01');
   await trigger.click();await dialog.getByRole('button',{name:/^海岸线/}).click();await page.keyboard.press('Escape');await page.locator('.letter').waitFor();assert.equal(await page.locator('.letter .sig').textContent(),'今晚整理一点，明天轻松一点。');
   report.checks.push(`all four themes, title/signature/date/particles controls retained ${viewport.width}`);
   await trigger.click();await dialog.getByRole('button',{name:/^夜泊/}).click();await page.keyboard.press('Escape');await page.locator('.daybreak.night').waitFor();
   // Real NotesPage + DocEditor fixture, not a hand-painted table/code mock.
   const doc={id:'guide-demo',title:'深色阅读示例',workspace_id:'qa-home-ws',parent_id:null,content:'# 深色阅读示例\n\n正文、表格与代码使用同一套全站深色层次。\n\n| 配置 | 范围 |\n| --- | --- |\n| 主页主题 | 当前浏览器 |\n| 账号背景 | 当前账号 |\n\n```sh\nprintf "Stella\\n"\n```\n\n> 示例内容，不含用户资料。',file_path:'/demo.md',updated_at:'2026-01-01T00:00:00Z',created_at:'2026-01-01T00:00:00Z',has_draft:false,status:'published',is_folder:false,is_favorite:false,is_pinned:false};
   for(const [endpoint,data]of Object.entries({'/workspaces/':[{id:'qa-home-ws',name:'演示笔记',user_id:h.user.id}],'/documents/':[doc],'/documents/guide-demo':doc,'/documents/recent':[],'/documents/favorites':[],'/tags/':[],'/doc-tags/':[],'/documents/guide-demo/draft':null,'/documents/guide-demo/versions':[],'/documents/guide-demo/links':[],'/documents/guide-demo/backlinks':[],'/attachments/guide-demo':[]}))await route(endpoint,r=>r.request().method()==='GET'?r.fulfill({json:data}):r.abort());
   await context.routeWebSocket(MAIN.replace('http:','ws:')+'/ws/list/qa-home-ws',ws=>ws.onMessage(()=>{}));
   await context.routeWebSocket(MAIN.replace('http:','ws:')+'/ws/guide-demo?*',ws=>ws.onMessage(()=>{}));
   await route('/attachments/',r=>r.request().method()==='GET'?r.fulfill({json:[]}):r.abort());
   await page.evaluate(async()=>{const {default:router}=await import('/src/router/index.ts');await router.push('/notes?doc=guide-demo');});
   await page.locator('.markdown-body pre code').waitFor();await page.locator('.markdown-body table').waitFor();
   const samples=await page.locator('.markdown-body p,.markdown-body th,.markdown-body td,.markdown-body pre code').evaluateAll(els=>els.map(el=>{const rgba=s=>s.match(/[\d.]+/g).map(Number);let bg=[0,0,0];const chain=[];for(let n=el;n;n=n.parentElement)chain.unshift(n);for(const n of chain){const c=rgba(getComputedStyle(n).backgroundColor),a=c[3]??1;bg=bg.map((v,i)=>c[i]*a+v*(1-a));}return {text:el.textContent,color:getComputedStyle(el).color,bg:`rgb(${bg.join(',')})`};}));receipt.reading=samples;
   check(`real notes table/code contrast ${viewport.width}`,()=>{for(const row of samples){assert(lum(row.bg)<.08);assert(contrast(row.color,row.bg)>=4.5,JSON.stringify(row));}});
   await page.screenshot({path:out+`/notes-reading-${viewport.width}.png`});
   assert.deepEqual(await snapshot(page),global);
   await page.evaluate(async()=>{const {default:router}=await import('/src/router/index.ts');await router.push('/settings');});await page.getByRole('heading',{name:'设置',exact:true}).waitFor();await page.screenshot({path:out+`/system-settings-${viewport.width}.png`});
   assert.deepEqual(await snapshot(page),global);report.checks.push(`global scope independent on notes/settings ${viewport.width}`);
  }catch(e){report.failures.push({viewport,error:e.stack});await page.screenshot({path:out+`/failed-${viewport.width}.png`});}
  receipt.frameColors=await page.evaluate(()=>{cancelAnimationFrame(window.__themeRAF);return window.__themeFrames||[];});
  check(`no white shell frames ${viewport.width}`,()=>{assert(receipt.frameColors.length);for(const f of receipt.frameColors)assert(lum(f.body)<.04);});
  check(`network/runtime diagnostics ${viewport.width}`,()=>{assert.deepEqual(h.unknown,[]);assert.deepEqual(h.errors,[]);assert.deepEqual(h.consoleErrors,[]);assert(!receipt.requests.some(r=>r.method==='PATCH'),'No account settings write during visual preferences');});
  await context.close();
 }
}finally{await browser?.close();await server.close();report.after=hashes();assert.deepEqual(report.before,report.after);fs.writeFileSync(out+'/report.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify({checks:report.checks,failures:report.failures},null,2));if(report.failures.length)process.exitCode=1;
