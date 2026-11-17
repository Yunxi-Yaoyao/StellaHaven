// Real Vue/router/Chromium WAAPI; synthetic HTTP/auth only. No DB, preview, or live session.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium,expect} from '@playwright/test';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
const root=process.cwd(), out=process.env.NOTIFICATION_EVIDENCE||resolve(root,'../notification-motion-evidence');
await mkdir(out,{recursive:true});
const work=await mkdtemp(resolve(process.env.TMPDIR||'/root/.hermes/cache/scratch','notification-motion-'));
const server=await createServer({
 root,configFile:false,envDir:false,appType:'custom',cacheDir:resolve(work,'vite'),
 // Bound this fixture's dependency graph; never scan all application HTML or share optimizer state.
 optimizeDeps:{entries:[],include:['vue','vue-router']},
 plugins:[vue(),{
  name:'notification-motion-fixture',enforce:'pre',
  resolveId(id){if(id==='/motion-entry.js')return '\0motion-entry';if(/\/home\/auth(?:\.ts)?(?:\?.*)?$/.test(id))return '\0motion-auth';},
  load(id){
   if(id==='\0motion-auth')return `import {ref} from 'vue';export const loggedIn=ref(true);export const auth={me:{id:'fixture'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false};export const refreshAccess=async()=>false;`;
   if(id==='\0motion-entry')return `
    import {createApp,h,ref} from 'vue';import {createRouter,createWebHistory} from 'vue-router';
    import '@fontsource-variable/inter';import '/src/style.css';
    import Bell from '/src/shell/NotificationBell.vue';import Detail from '/src/shell/NotificationDetail.vue';import Dialog from '/src/shell/DetailDialog.vue';
    const router=createRouter({history:createWebHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});
    const direct=ref(0),plain=ref(false);window.switchNotification=id=>direct.value=id;
    createApp({render:()=>[h('div',{class:'fixture-bar'},[h(Bell)]),h('button',{id:'plain',onClick:()=>plain.value=true},'普通详情'),
     plain.value?h(Dialog,{title:'告警详情',onClose:()=>plain.value=false},()=>h('p','既有告警内容')):null,
     direct.value?h(Detail,{id:direct.value,onClose:()=>direct.value=0}):null]}).use(router).mount('#app');`;
  },
  configureServer(s){s.middlewares.use((req,res,next)=>{
   if(!req.url?.startsWith('/fixture'))return next();
   res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>通知详情</title><style>body{margin:0;min-height:100vh;background:#191b20}.fixture-bar{padding:18px 22px}button{font-family:inherit}</style><div id="app"></div><script type="module" src="/motion-entry.js"></script></html>');
  });},
 }],server:{host:'127.0.0.1',port:0,strictPort:true},
});
await server.listen();const origin=`http://127.0.0.1:${server.httpServer.address().port}`;
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const checks=[],errors=[],screens=[];let step='startup';
const item=id=>({id,title:id===9?'HK 节点 · 网络延迟持续升高':'备份任务已完成',body:id===9?'节点延迟连续超过阈值。请检查上游链路与节点负载；通知仅保留发送时的状态。':'备份文件已保存，可在备份中心查看完整结果。',ts:'2026-10-19T01:20:00Z',kind:id===9?'alert':'backup_result',severity:id===9?'warning':'info',read:false,entities:[{type:'node',id:12,label:'香港 HK · 主节点',available:true},{type:'node',id:13,label:'已移除节点',available:false}],context:id===9?{incident_id:7}:null});
const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,opacity:getComputedStyle(el).opacity};};
function closeEnough(a,b){for(const k of ['x','y','width','height'])expect(Math.abs(a[k]-b[k]),k).toBeLessThan(2);}
async function sample(page,progress){return page.evaluate(progress=>{
 const d=document.querySelector('.detail-dialog'),a=document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().endTime));
 for(const animation of a){animation.pause();animation.currentTime=Number(animation.effect.getTiming().duration)*progress;}
 const r=d.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,opacity:getComputedStyle(d).opacity,content:getComputedStyle(d.firstElementChild).opacity,backdrop:getComputedStyle(document.querySelector('.detail-mask')).backgroundColor,panel:getComputedStyle(document.querySelector('[data-notification-panel]')).opacity,animations:a.length};
},progress);}
const finish=page=>page.evaluate(()=>document.getAnimations().filter(a=>Number.isFinite(a.effect.getComputedTiming().endTime)).forEach(a=>a.finish()));
async function screenshot(page,name){
 // Playwright's default CSS clip crops native-zoom screenshots on viewport:null.
 // Capture the actual full compositor viewport, without a synthetic clip.
 const session=await page.context().newCDPSession(page);
 try{const shot=await session.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(resolve(out,name),Buffer.from(shot.data,'base64'));screens.push(name);}
 finally{await session.detach();}
}
try{
 for(const [label,width,height,reduced] of [['desktop',1440,900,false],['mobile390',390,844,false],['mobile320',320,740,false],['zoom200',720,450,false],['reduced',390,844,true]]){
  step=`${label}: navigate`;
  const zoom=label==='zoom200';
  const context=zoom
   ? await chromium.launchPersistentContext(resolve(work,'zoom-profile'),{channel:'chromium',headless:true,viewport:null,args:['--no-sandbox','--window-size=1440,987'],locale:'zh-CN',timezoneId:'Asia/Shanghai'})
   : await browser.newContext({viewport:{width,height},reducedMotion:reduced?'reduce':'no-preference',locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  const page=zoom?context.pages()[0]:await context.newPage(),requests=[],releases=new Map();page.on('pageerror',e=>errors.push(e.message));
  let pendingId,fail=false,readFail=false,zoomInfo=null;
  try{
   if(zoom){
    // Actual Chromium page zoom, not CSS zoom or deviceScaleFactor emulation.
    await page.goto('chrome://settings/appearance');
    await page.evaluate(()=>new Promise(resolve=>chrome.settingsPrivate.setDefaultZoom(2,resolve)));
    expect(await page.evaluate(()=>new Promise(resolve=>chrome.settingsPrivate.getDefaultZoom(resolve)))).toBe(2);
   }
   await page.route('**/*',async route=>{
    const u=new URL(route.request().url());if(u.origin!==origin)return route.abort();
    if(u.pathname==='/alerts/incidents/7')return route.fulfill({json:{id:7,label:'HK 网络延迟',message:'持续异常',status:'unresolved',started_at:'2026-10-19T01:00:00Z',duration_seconds:1200,severity:'warning',timeline:[],notifications:[]}});
    if(!u.pathname.startsWith('/notifications'))return route.continue();
    requests.push({path:u.pathname,method:route.request().method()});
    if(u.pathname==='/notifications/'||u.pathname==='/notifications')return route.fulfill({json:[item(9),item(10)]});
    if(u.pathname.endsWith('/read'))return route.fulfill({status:readFail?500:200,json:{ok:!readFail}});
    const id=Number(u.pathname.split('/').at(-1));if(id===pendingId)await new Promise(r=>releases.set(id,r));
    return route.fulfill({status:fail?500:200,json:fail?{detail:'fixture read failure'}:item(id)});
   });
   await page.goto(origin+'/fixture');const bell=page.getByRole('button',{name:'通知',exact:true});await expect(bell).toBeVisible();
   if(zoom){zoomInfo=await page.evaluate(()=>({width:innerWidth,height:innerHeight,outerWidth,devicePixelRatio,cssZoom:getComputedStyle(document.documentElement).zoom}));expect(zoomInfo.width).toBe(width);expect(zoomInfo.devicePixelRatio).toBe(2);expect(zoomInfo.cssZoom).toBe('1');}
   await bell.click();const row=page.locator('[data-notification-panel] .item').first();await expect(row).toBeVisible();
   await page.evaluate(()=>Promise.all(document.getAnimations().map(a=>a.finished)));const source=await row.evaluate(rect),d=page.locator('.detail-dialog');
   // Natural (unpaused) browser clock plus a real loading→content reflow.
   let liveFrames;
   if(label==='desktop'){
    step=`${label}: natural rAF reflow`;pendingId=9;
    await page.evaluate(()=>{window.motionFrames=[];window.motionDone=new Promise(resolve=>{
     let start;function frame(t){start??=t;setTimeout(()=>{const el=document.querySelector('.detail-dialog');if(el){const r=el.getBoundingClientRect();window.motionFrames.push({t:t-start,x:r.x,y:r.y,width:r.width,height:r.height,content:getComputedStyle(el.firstElementChild).opacity});}if(t-start<450)requestAnimationFrame(frame);else resolve();},0);}requestAnimationFrame(frame);
    });});
    await row.click();await expect(page.getByRole('status')).toContainText('正在读取');
    await expect.poll(()=>page.evaluate(()=>window.motionFrames.length)).toBeGreaterThan(2);
    pendingId=undefined;releases.get(9)();releases.delete(9);await expect(page.locator('[data-notification-detail]')).toContainText(item(9).body);
    liveFrames=await page.evaluate(async()=>{await window.motionDone;return window.motionFrames;});
    expect(liveFrames.length).toBeGreaterThan(5);expect(liveFrames.some(f=>f.height>source.height+2&&f.height<liveFrames.at(-1).height-2)).toBe(true);
    await page.keyboard.press('Escape');await expect(d).toHaveCount(0);await expect(row).toBeFocused();requests.length=0;
   }
   // Paused WAAPI still uses the real browser renderer, not fabricated rectangles.
   await page.evaluate(()=>{const original=Element.prototype.animate;Element.prototype.animate=function(...args){const a=original.apply(this,args);a.pause();a.currentTime=0;return a;};});
   step=`${label}: source/middle/end`;
   await row.focus();await page.keyboard.press('Enter');await expect(page.locator('[data-notification-detail]')).toContainText('发送时间');
   // Flush layout/ResizeObserver before deliberately seeking the paused timeline.
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const start=await sample(page,0),middle=await sample(page,.5),end=await sample(page,1);
   await writeFile(resolve(out,`${label}-samples.json`),JSON.stringify({source,start,middle,end,liveFrames},null,2));
   if(!reduced){
    expect(start.animations).toBeGreaterThanOrEqual(3);closeEnough(start,source);expect(Math.abs(middle.y-start.y)).toBeGreaterThan(1);
    expect(middle.height).toBeGreaterThan(start.height);expect(middle.height).toBeLessThan(end.height);
    expect(Number(middle.panel)).toBeGreaterThan(0);expect(Number(middle.panel)).toBeLessThan(1);
    expect(Number(middle.content)).toBeGreaterThan(Number(start.content));expect(Number(middle.content)).toBeLessThan(1);
   }else closeEnough(start,end);
   await sample(page,0);await screenshot(page,`${label}-start.png`);await sample(page,.5);await screenshot(page,`${label}-mid.png`);
   await finish(page);await screenshot(page,`${label}-detail.png`);
   expect(await page.locator('[data-notification-panel]').getAttribute('aria-hidden')).toBe('true');expect(await page.locator('[data-notification-panel]').evaluate(e=>e.inert)).toBe(true);
   expect(await d.evaluate(e=>e.contains(document.activeElement))).toBe(true);
   const geometry=await d.evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth,right:e.getBoundingClientRect().right,viewport:innerWidth}));expect(geometry.scroll).toBeLessThanOrEqual(geometry.width+1);expect(geometry.right).toBeLessThanOrEqual(width+1);
   expect(await page.locator('[data-notification-detail] a.entity').getAttribute('href')).toBe('/status/12');expect(await page.locator('[data-notification-detail] .missing').count()).toBe(1);
   expect(requests.filter(r=>r.path==='/notifications/9'&&r.method==='GET')).toHaveLength(1);expect(requests.filter(r=>r.path==='/notifications/9/read')).toHaveLength(1);await expect(row).not.toHaveClass(/unread/);
   step=`${label}: nested alert and keyboard`;
   const alertButton=page.getByRole('button',{name:'查看对应告警详情',exact:true});
   await page.keyboard.press('Tab');await expect(page.getByRole('button',{name:'关闭详情',exact:true})).toBeFocused();
   await page.keyboard.press('Shift+Tab');await expect(alertButton).toBeFocused();await page.keyboard.press('Tab');await expect(page.getByRole('button',{name:'关闭详情',exact:true})).toBeFocused();
   await alertButton.click();const incident=page.getByRole('dialog',{name:'告警详情',exact:true});await expect(incident).toContainText('HK 网络延迟');
   await page.keyboard.press('Escape');await expect(incident).toHaveCount(0);await expect(alertButton).toBeFocused();
   await page.keyboard.press('Escape');await finish(page);await expect(d).toHaveCount(0);await expect(row).toBeFocused();
   step=`${label}: interrupted close`;
   await page.keyboard.press('Space');await expect(d).toHaveCount(1);await expect(page.locator('[data-notification-detail]')).toContainText('发送时间');
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const interruptedFrom=await sample(page,.3);await page.keyboard.press('Escape');const interrupted=await sample(page,0);closeEnough(interrupted,interruptedFrom);
   expect(Math.abs(Number(interrupted.content)-Number(interruptedFrom.content))).toBeLessThan(.01);
   await page.keyboard.press('Escape'); // A repeated close cannot emit twice or lose the focus owner.
   await finish(page);await expect(d).toHaveCount(0);await expect(row).toBeFocused();
   step=`${label}: resize`;
   await row.click();await expect(d).toHaveCount(1);await page.setViewportSize({width:width+12,height});
   // setViewportSize resolves before resize dispatch: wait on the result, not an arbitrary sleep.
   await expect.poll(()=>d.evaluate(e=>getComputedStyle(e).transform)).toBe('none');await page.keyboard.press('Escape');await finish(page);await expect(d).toHaveCount(0);
   step=`${label}: load/read failures`;
   pendingId=9;await row.click();await expect(page.getByRole('status')).toContainText('正在读取');await finish(page);
   fail=true;pendingId=undefined;releases.get(9)();releases.delete(9);await expect(page.getByRole('alert')).toContainText('加载失败');fail=false;readFail=true;
   await page.getByRole('button',{name:'重试',exact:true}).click();await expect(page.locator('[data-notification-detail]')).toContainText(item(9).body);
   await expect(page.getByRole('alert')).toContainText('标记已读失败');readFail=false;await page.getByRole('button',{name:'重试标记',exact:true}).click();await expect(page.getByRole('alert')).toHaveCount(0);
   await page.locator('[data-notification-detail] a.entity').click();await expect(page).toHaveURL(/\/status\/12$/);await expect(d).toHaveCount(0);await expect(page.locator('[data-notification-panel]')).toHaveCount(0);
   step=`${label}: shared default`;
   await page.locator('#plain').click();await expect(page.getByRole('heading',{name:'告警详情',exact:true})).toBeVisible();expect(await d.evaluate(e=>getComputedStyle(e).transform)).toBe('none');
   await page.keyboard.press('Escape');await expect(d).toHaveCount(0);await expect(page.locator('#plain')).toBeFocused();
   step=`${label}: switch pending owner`;
   pendingId=9;await page.evaluate(()=>window.switchNotification(9));await expect(page.getByRole('status')).toBeVisible();await expect.poll(()=>releases.has(9)).toBe(true);
   await page.evaluate(()=>window.switchNotification(10));await expect(page.locator('[data-notification-detail]')).toContainText(item(10).title);
   pendingId=undefined;releases.get(9)();releases.delete(9);await expect(page.locator('[data-notification-detail]')).not.toContainText(item(9).body);
   await page.keyboard.press('Escape');await expect(d).toHaveCount(0);
   checks.push({label,width,height:zoomInfo?.height??height,reduced,zoom:zoom?'Chromium native default zoom 2':null,zoomInfo,source,start,middle,end,geometry,liveFrames,interruptedFrom,interrupted,requests});
  }finally{
   // Fixture auth has no actual login to revoke. Release held HTTP and destroy this isolated context.
   for(const release of releases.values())release();await context.close();
  }
 }
 expect(errors).toEqual([]);await writeFile(resolve(out,'browser-result.json'),JSON.stringify({passed:true,boundary:'Real components/router/Chromium WAAPI; synthetic HTTP/auth, no DB or live session',checks,screens,errors},null,2));
 console.log(JSON.stringify({passed:true,checks:checks.map(c=>c.label),screens,errors}));
}catch(e){await writeFile(resolve(out,'browser-failure.json'),JSON.stringify({step,error:String(e),checks,errors},null,2));throw e;}
finally{await browser.close();await server.close();await rm(work,{recursive:true,force:true});}
