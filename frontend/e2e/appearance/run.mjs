// Isolated browser HTTP fixture. Synthetic owner/API; never proxies live routes.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const output=process.env.STELLA_APPEARANCE_OUTPUT||await mkdtemp(path.join(tmpdir(),'stella-appearance-evidence-'));await mkdir(output,{recursive:true});
const cache=await mkdtemp(path.join(tmpdir(),'stella-appearance-vite-'));
let state=null,failWrite=false,holdRead=false,releaseRead=()=>{},calls=[];
const auth='\0appearance-auth';
// Shared st-button CSS is fixture-only until layout-lane integration, not a product fork.
const controls=`.st-button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:32px;width:auto;flex:none;padding:5px 10px;border:1px solid var(--control-border);border-radius:6px;background:var(--control-bg);color:var(--text-hi);font:inherit;font-size:13px;cursor:pointer}.st-button:hover:not(:disabled){background:var(--control-hover)}.st-button.is-primary{background:linear-gradient(170deg,var(--button-top),var(--button-bottom));border-color:var(--button-border)}.st-button.is-ghost{background:transparent}.st-button.is-danger{color:var(--danger);border-color:var(--danger)}.st-button.is-icon{width:32px;padding:0}.st-button:disabled{color:var(--text-lo);cursor:default}.fixture-navigation{padding-bottom:14px}.fixture-navigation button{background:transparent;color:var(--text-lo);border:0;padding:5px;cursor:pointer}main{max-width:1050px;margin:auto;padding:24px}.fixture-caption{color:var(--text-lo);font-size:12px;margin-bottom:16px}@media(max-width:600px){main{padding:12px}}`;
const server=await createServer({configFile:false,root:process.cwd(),cacheDir:cache,plugins:[vue(),{name:'appearance-isolation',enforce:'pre',resolveId(id){if(id.endsWith('/home/auth'))return auth;},load(id){if(id===auth)return `import {reactive,ref} from 'vue';export const auth=reactive({me:{id:'synthetic-appearance-owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});export const isAdmin=ref(false);export const refreshAccess=async()=>false;`;},configureServer(vite){vite.middlewares.use(async(req,res,next)=>{
 if(req.url==='/operations/backups/client-preferences'){
  calls.push({method:req.method});res.setHeader('Content-Type','application/json');
  if(req.method==='PUT'){let text='';for await(const chunk of req)text+=chunk;const body=JSON.parse(text);calls.at(-1).body=body;
   if(failWrite){res.statusCode=503;res.end(JSON.stringify({detail:'synthetic write unavailable'}));return;}
   if(body.expected_revision!==state.revision){res.statusCode=409;res.end(JSON.stringify({detail:'revision changed'}));return;}
   const {expected_revision,...content}=body;state={...content,revision:expected_revision+1};
  } else if(holdRead){await new Promise(resolve=>{releaseRead=resolve;});}
  res.end(JSON.stringify(state));return;
 }
 if(req.url?.startsWith('/operations/')||req.url?.startsWith('/auth/')){res.statusCode=501;res.end('Fixture forbids business API');return;}
 if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end(await vite.transformIndexHtml('/',`<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${controls}</style></head><body><main><p class="fixture-caption">隔离外观组件验收 · 合成账号与 HTTP 数据</p><div id="app"></div></main><script type="module" src="/e2e/appearance/fixture.ts"></script></body></html>`));return;}next();
 });}}],optimizeDeps:{entries:['e2e/appearance/fixture.ts'],include:['vue','vue-router']},server:{host:'127.0.0.1',port:0},appType:'custom'});
const initial=()=>({revision:7,appearance:'A',home:{theme:'daybreak',particles:'off',bgImage:'',bgCrop:{cx:.5,cy:.5,w:1,h:1},siteTitle:'StellaHaven',signature:'',meetDate:'2026-05-31',live2d:false,avatar:'/avatar.png'},ui:{backgroundQuality:'compressed1',sidebarFold:false,serversFold:false,toolsOpen:false,worldMapCollapsed:false,monitorMode:'chart',noteEditMode:'rich',listFold:false,driveBackground:'solid'}});
let browser;const receipts=[];
try{
 await server.listen();const url=`http://127.0.0.1:${server.httpServer.address().port}/`;assert.equal((await fetch(url)).status,200);
 browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 for(const width of [1280,390,320]){
  state=initial();calls=[];failWrite=false;
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],warnings=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(['error','warning'].includes(m.type()))warnings.push(m.text());});
  await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
  const selected=()=>page.evaluate(()=>document.documentElement.dataset.appearance);
  const synced=()=>page.getByRole('status').filter({hasText:'账号已同步'}).waitFor();
  const color=()=>page.getByLabel('颜色值',{exact:true});
  const part=id=>page.locator(`[data-theme-part="${id}"]`);
  try{
   await page.goto(url);await synced();assert.equal(await selected(),'A');assert.equal(calls.filter(c=>c.method==='PUT').length,0);
   const avatarBox=await page.getByLabel('示例头像',{exact:true}).boundingBox(),inputBox=await page.getByLabel('样板名称',{exact:true}).boundingBox();assert.equal(avatarBox.x,inputBox.x,'avatar and input control columns align');
   await page.screenshot({path:path.join(output,`appearance-${width}-A.png`),fullPage:true});
   const mode=page.getByRole('switch',{name:'调色模式',exact:true});assert.equal(await mode.getAttribute('aria-checked'),'true');
   await part('primary').focus();await page.keyboard.press('Enter');await color().waitFor();assert.equal(await selected(),'A');assert.equal(await color().evaluate(e=>e===document.activeElement),true);
   await color().fill('#123456');assert.equal(await selected(),'custom');assert.equal(calls.filter(c=>c.method==='PUT').length,0);
   await page.keyboard.press('Escape');assert.equal(await selected(),'A');assert.equal(await part('primary').evaluate(e=>e===document.activeElement),true);
   await part('primary').click();await color().fill('#AABBCC');await page.getByRole('button',{name:'完成调色',exact:true}).click();await synced();assert.equal(state.appearance,'custom');assert.equal(state.customAppearance.overrides['button-top'],'#AABBCC');
   assert.equal(calls.filter(c=>c.method==='PUT').length,1);
   await page.getByRole('button',{name:'A · 暮紫 × 桃粉',exact:true}).click();await synced();assert.equal(state.appearance,'A');
   await page.getByRole('button',{name:'自定义',exact:true}).click();await synced();assert.equal(state.customAppearance.overrides['button-top'],'#AABBCC');
   await page.reload();await synced();assert.equal(await selected(),'custom');
   // Real metric SVG uses resolved hex, never var().
   await part('cpu').click();const recoveryBox=await page.locator('[aria-label="配色恢复"]').boundingBox();assert(recoveryBox.y>=0&&recoveryBox.y+recoveryBox.height<=900,'recovery must remain in viewport while editing lower samples');await color().fill('#C0FFEE');await page.getByRole('button',{name:'完成调色',exact:true}).click();await synced();assert.equal(await part('cpu').locator('path').nth(1).getAttribute('stroke'),'#C0FFEE');
   // Bad contrast is visible without silently changing the chosen value.
   await part('input').click();await color().fill('#ECECF3');await page.getByText(/低于 4.5:1/).waitFor();await page.screenshot({path:path.join(output,`appearance-${width}-editor.png`),fullPage:true});
   const box=await page.locator('.color-panel').boundingBox();assert(box.x>=0&&box.x+box.width<=width&&box.y>=0&&box.y+box.height<=900);await page.getByRole('button',{name:'取消本次',exact:true}).click();
   await part('overlay').click();await color().fill('#303142');await page.getByRole('button',{name:'完成调色',exact:true}).click();await synced();
   // Trial uses actual Dropdown, HelpHint and a contained native modal.
   await mode.click();assert.equal(await mode.getAttribute('aria-checked'),'false');
   await page.getByRole('switch',{name:'样板提醒',exact:true}).click();assert.equal(await page.getByRole('switch',{name:'样板提醒',exact:true}).getAttribute('aria-checked'),'false');
   await page.getByRole('button',{name:'每日摘要',exact:true}).focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');assert.equal(await page.getByRole('button',{name:'仅重要提醒',exact:true}).count(),1);
   await page.getByRole('button',{name:'样板帮助',exact:true}).click();await page.getByRole('tooltip').filter({hasText:'这里使用'}).waitFor();assert.equal(await page.locator('.sample-portal [role=tooltip]').count(),1);assert.equal(await page.locator('.sample-portal [role=tooltip]').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(48, 49, 66)');await page.keyboard.press('Escape');
   const businessBefore=calls.filter(c=>c.method==='PUT').length;const deleteTrigger=page.getByRole('button',{name:'删除示例',exact:true});await deleteTrigger.click();await page.getByRole('dialog',{name:'删除这个示例？',exact:true}).waitFor();assert.equal(await page.locator('.sample-portal dialog').count(),1);await page.keyboard.press('Escape');assert.equal(await deleteTrigger.evaluate(e=>e===document.activeElement),true);assert.equal(calls.filter(c=>c.method==='PUT').length,businessBefore);
   await page.getByRole('button',{name:'切换页面',exact:true}).click();await page.getByRole('button',{name:'切换页面',exact:true}).click();assert.equal(await mode.getAttribute('aria-checked'),'false');
   await page.reload();await synced();assert.equal(await mode.getAttribute('aria-checked'),'false');
   // Server failure retains visible color, reload cache and retry uses read+write+read.
   await mode.click();failWrite=true;await part('cpu').click();await color().fill('#ABCDEF');await page.getByRole('button',{name:'完成调色',exact:true}).click();await page.getByRole('button',{name:'重试同步',exact:true}).waitFor();assert.equal(await part('cpu').locator('path').nth(1).getAttribute('stroke'),'#ABCDEF');
   failWrite=false;await page.getByRole('button',{name:'重试同步',exact:true}).click();await synced();assert.equal(state.customAppearance.overrides['metric-cpu'],'#ABCDEF');
   // A second offline edit survives a full reload as a conflict, not stale cloud hydration.
   failWrite=true;await part('cpu').click();await color().fill('#FEDCBA');await page.getByRole('button',{name:'完成调色',exact:true}).click();await page.getByRole('button',{name:'重试同步',exact:true}).waitFor();
   failWrite=false;await page.reload();await page.getByRole('button',{name:'保留本机',exact:true}).waitFor();assert.equal(await part('cpu').locator('path').nth(1).getAttribute('stroke'),'#FEDCBA');
   await page.getByRole('button',{name:'保留本机',exact:true}).click();await synced();assert.equal(state.customAppearance.overrides['metric-cpu'],'#FEDCBA');
   // Reset remains reachable when actual page/body colors are illegible.
   await part('page').click();await color().fill('#ECECF3');await page.getByRole('button',{name:'恢复基底',exact:true}).click();await synced();assert.equal(await selected(),'A');assert.equal(state.customAppearance.base,'A');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   if(width===1280){await page.setViewportSize({width:640,height:450});await part('primary').click();const small=await page.locator('.color-panel').boundingBox();assert(small.y>=0&&small.y+small.height<=450);await page.screenshot({path:path.join(output,'appearance-short-height-200-layout.png'),fullPage:true});await page.keyboard.press('Escape');}
   assert.deepEqual(errors,[]);assert.equal(warnings.filter(m=>!m.includes('503 (Service Unavailable)')).length,0);assert.equal(warnings.filter(m=>m.includes('503 (Service Unavailable)')).length,2);
   receipts.push({width,modeAndNavigation:true,keyboard:true,noopSelection:true,cancelAndFocus:true,firstChangeCustom:true,coalescedWrite:true,retainedPresetsAndReload:true,actualDropdownHelpDialog:true,containedPortals:true,metricHex:true,contrastWarning:true,failureRetainedAndRetryReadback:true,recovery:true,noOverflow:true,apiBoundary:'synthetic HTTP owner preferences only; no live services'});
  }finally{await context.close();}
 }
 // Native browser zoom needs a disposable persistent profile: incognito disallows chrome://settings.
 const zoomProfile=await mkdtemp(path.join(tmpdir(),'appearance-native-zoom-'));
 let zoomContext;
 try{
  zoomContext=await chromium.launchPersistentContext(zoomProfile,{headless:true,executablePath:chromium.executablePath(),viewport:{width:1280,height:900},args:['--no-sandbox']});
  const settings=await zoomContext.newPage();await settings.goto('chrome://settings/appearance');await settings.evaluate(()=>new Promise(resolve=>chrome.settingsPrivate.setDefaultZoom(2,resolve)));await settings.close();
  state=initial();calls=[];const page=await zoomContext.newPage();await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());await page.goto(url);await page.getByRole('status').filter({hasText:'账号已同步'}).waitFor();
  const geometry=await page.evaluate(()=>({dpr:devicePixelRatio,width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth}));assert.deepEqual(geometry,{dpr:2,width:640,height:450,overflow:false});
  await page.locator('[data-theme-part="primary"]').click();await page.getByLabel('颜色值',{exact:true}).fill('#AABBCC');
  const box=await page.locator('.color-panel').boundingBox();assert(box.x>=0&&box.x+box.width<=640&&box.y>=0&&box.y+box.height<=450);
  const zoomCDP=await zoomContext.newCDPSession(page);
  async function captureNative(){
   const capture=async()=>Buffer.from((await zoomCDP.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,fromSurface:true})).data,'base64');
   let image=await capture();let w=image.readUInt32BE(16),h=image.readUInt32BE(20);
   if(w!==1280||h!==900){const {windowId,bounds}=await zoomCDP.send('Browser.getWindowForTarget');await zoomCDP.send('Browser.setWindowBounds',{windowId,bounds:{width:bounds.width+1280-w,height:bounds.height+900-h}});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));image=await capture();}
   assert.equal(image.readUInt32BE(16),1280);assert.equal(image.readUInt32BE(20),900);return image;
  }
  await writeFile(path.join(output,'appearance-native-200-percent.png'),await captureNative());
  for(const name of ['单项重置','取消本次','完成调色']){await page.keyboard.press('Tab');const button=page.getByRole('button',{name,exact:true});assert.equal(await button.evaluate(e=>e===document.activeElement),true);const rect=await button.boundingBox();assert(rect.y>=0&&rect.y+rect.height<=450);}
  await writeFile(path.join(output,'appearance-native-200-percent-actions.png'),await captureNative());await page.keyboard.press('Escape');
  assert.equal(await page.locator('[data-theme-part="primary"]').evaluate(e=>e===document.activeElement),true);
  receipts.push({nativeBrowserZoom:'200%',physicalViewport:{width:1280,height:900},cssViewport:geometry,editorContained:true,escapeFocus:true,profile:'disposable persistent; removed after close'});
 }finally{await zoomContext?.close();await rm(zoomProfile,{recursive:true,force:true});}
 await writeFile(path.join(output,'browser-result.json'),JSON.stringify(receipts,null,2));console.log(JSON.stringify(receipts,null,2));
}finally{releaseRead();await browser?.close();await server.close();await rm(cache,{recursive:true,force:true});}
