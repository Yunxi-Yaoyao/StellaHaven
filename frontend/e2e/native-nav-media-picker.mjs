import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const origin=process.env.STELLA_MAIN_ORIGIN,out=process.env.NAV_MEDIA_EVIDENCE;
assert(origin&&out);
const browser=await chromium.launch({headless:true,executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox']});
const context=await browser.newContext({ignoreHTTPSErrors:true,storageState:out+'/private-state.json',viewport:{width:1440,height:1000}});
const page=await context.newPage();
const report={journeys:[],geometry:[],requests:[],pageerrors:[],console:[],external:[],responses:[]};
let checking=false;
page.on('pageerror',e=>report.pageerrors.push(e.message));
page.on('console',m=>{if(m.type()==='error')report.console.push(m.text());});
page.on('request',r=>{const u=new URL(r.url());if(u.origin===origin)report.requests.push({method:r.method(),path:u.pathname,checking});});
page.on('response',async r=>{if(r.status()>=400)report.responses.push({status:r.status(),url:r.url(),body:await r.text().catch(()=>'<unreadable>')});});
await context.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!==origin){report.external.push(u.origin+u.pathname);return route.abort();}const r=route.request();if(checking&&r.method()!=='GET'&&r.method()!=='HEAD'&&!((r.method()==='POST'&&(u.pathname==='/homebg/upload'||/^\/homebg\/[^/]+\/optimize$/.test(u.pathname)||u.pathname==='/auth/activity'))||(r.method()==='DELETE'&&/^\/homebg\/[^/]+$/.test(u.pathname))||(r.method()==='PATCH'&&/^\/homebg\/[^/]+$/.test(u.pathname))||(r.method()==='PUT'&&u.pathname==='/nav-data')))return route.abort('blockedbyclient');return route.continue();});
const read=async path=>{const r=await context.request.get(origin+path);assert.equal(r.status(),200,path+': '+await r.text());return r.json();};
const dialog=()=>page.locator('.nav-dialog[open]');
const manager=()=>page.locator('.bgm-mask .bgm');
const cell=name=>manager().locator('.cell').filter({has:page.locator('.name',{hasText:new RegExp('^'+name+'$')})});
const shot=async name=>{await expect(page.locator('.fade-enter-active,.fade-leave-active')).toHaveCount(0);return page.screenshot({path:out+'/'+name+'.png'});};
const settings=async()=>{await page.getByRole('button',{name:'导航设置',exact:true}).click();await dialog().getByRole('button',{name:'背景',exact:true}).click();};
const open=async()=>{const loading=page.waitForResponse(r=>new URL(r.url()).pathname==='/homebg/'&&r.request().method()==='GET');await dialog().getByRole('button',{name:'管理壁纸与视频',exact:true}).click();await (await loading).finished();await expect(manager()).toBeVisible();await expect(cell('Synthetic home protected')).toBeVisible();await expect.poll(()=>manager().locator('img').evaluateAll(images=>images.every(i=>i.complete))).toBe(true);await page.waitForLoadState('networkidle');
 const retry=manager().getByRole('button',{name:'缩略图加载失败 · 重试',exact:true});
 for(let i=0;i<4&&await retry.count();i++){await retry.first().click();report.thumbnailRetries=(report.thumbnailRetries||0)+1;await expect.poll(()=>manager().locator('img').evaluateAll(images=>images.every(i=>i.complete))).toBe(true);await page.waitForLoadState('networkidle');}
 await expect(retry).toHaveCount(0);await expect.poll(()=>manager().locator('img').evaluateAll(images=>images.every(i=>i.naturalWidth>0))).toBe(true);
};
async function geometry(selector,label){const g=await page.locator(selector).evaluate(el=>{const rect=el.getBoundingClientRect();const buttons=[...el.querySelectorAll('button')].filter(b=>b.offsetWidth&&!b.disabled);return {rect:rect.toJSON(),viewport:{width:innerWidth,height:innerHeight},buttons:buttons.map(b=>{const r=b.getBoundingClientRect();return {text:b.textContent.trim(),rect:r.toJSON(),hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('button')===b};})};});assert(g.rect.left>=0&&g.rect.right<=g.viewport.width&&g.rect.top>=0&&g.rect.bottom<=g.viewport.height,JSON.stringify(g));for(const b of g.buttons)assert(b.hit,JSON.stringify(b));report.geometry.push({label,...g});}
const journey=async(name,fn)=>{await fn();report.journeys.push(name);console.log('PASS',name);};
try{
 await page.goto(origin+'/nav');await expect(page.getByRole('button',{name:'导航设置',exact:true})).toBeEnabled();await expect(page.getByText('多窗口同步已连接',{exact:true})).toBeVisible();
 // Allow the real App's first-owner preference bootstrap to settle before the
 // picker baseline. No preference write is permitted during the journeys.
 await expect.poll(async()=> (await read('/operations/backups/client-preferences')).revision).toBe(1);
 const homeBefore=await read('/auth/me'),prefsBefore=await read('/operations/backups/client-preferences'),navBefore=await read('/nav-data');
 const localBefore=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.startsWith('stella_home_'))));
 checking=true;
 await journey('upload image, choose into navigation draft, cancel leaves nav/home/account preferences unchanged',async()=>{
  await settings();await open();await expect(cell('Synthetic home protected').getByTitle('删除',{exact:true})).toBeDisabled();
  await manager().locator('input[type=file]').setInputFiles(out+'/synthetic.png');await expect(cell('synthetic')).toBeVisible();
  await geometry('.bgm-mask .bgm-foot','1440 picker footer');await shot('image-picker-1440');
  await manager().getByRole('button',{name:'选择此背景',exact:true}).click();await expect(manager()).toHaveCount(0);
  assert.deepEqual(await read('/nav-data'),navBefore);await dialog().locator('footer').getByRole('button',{name:'取消',exact:true}).click();
  assert.deepEqual(await read('/nav-data'),navBefore);assert.deepEqual(await read('/auth/me'),homeBefore);assert.deepEqual(await read('/operations/backups/client-preferences'),prefsBefore);
 });
 await journey('real MP4 upload optimizes in PG, decodes in preview, selection saves only navigation and plays',async()=>{
  await settings();await open();await manager().locator('input[type=file]').setInputFiles(out+'/synthetic.mp4');
  // Two entries share a basename: the real extension, not nth order, owns the target.
  const videoCell=cell('synthetic').filter({has:page.locator('[data-ext="mp4"]')});await expect(videoCell).toBeVisible();
  const entries=await read('/homebg/'),video=entries.find(e=>e.ext==='mp4'&&e.name==='synthetic');assert(video);assert.equal(video.media.status,'ready');assert(video.media.variants.compressed1&&video.media.variants.compressed2&&video.media.poster);
  assert.notEqual(video.media.variants.compressed1,video.url);assert.notEqual(video.media.variants.compressed2,video.url);
  const original=await context.request.get(origin+video.url),compressed=await context.request.get(origin+video.media.variants.compressed1);
  assert.equal(original.status(),200);assert.equal(compressed.status(),200);assert((await compressed.body()).length<(await original.body()).length);
  report.optimization={originalBytes:(await original.body()).length,compressed1Bytes:(await compressed.body()).length,variants:video.media.variants};
  await videoCell.dblclick();const player=page.locator('.preview-mask video');await expect(player).toBeVisible();
  await expect.poll(()=>player.evaluate(v=>({width:v.videoWidth,height:v.videoHeight,ready:v.readyState,time:v.currentTime}))).toMatchObject({width:320,height:180});
  await expect.poll(()=>player.evaluate(v=>v.currentTime)).toBeGreaterThan(0);assert.equal(await page.locator('.crop-sliders').count(),0);await geometry('.crop-actions','1440 video preview footer');await shot('video-decoded-1440');
  report.decoded=await player.evaluate(v=>({width:v.videoWidth,height:v.videoHeight,readyState:v.readyState,currentTime:v.currentTime,source:v.currentSrc}));assert.equal(report.decoded.source,origin+video.media.variants.compressed1);
  await page.locator('.crop-actions').getByRole('button',{name:'选择此背景',exact:true}).click();await dialog().locator('footer').getByRole('button',{name:'保存',exact:true}).click();await expect(dialog()).toHaveCount(0);
  const saved=await read('/nav-data');assert.equal(saved.revision,1);assert.equal(saved.data.preferences.background,'custom');assert.equal(saved.data.preferences.backgroundUrl,video.url);
  await expect.poll(()=>page.locator('.nav-wallpaper video').evaluate(v=>v.videoWidth)).toBe(320);
  assert.deepEqual(await read('/auth/me'),homeBefore);assert.deepEqual(await read('/operations/backups/client-preferences'),prefsBefore);
 });
 await journey('malformed MP4 optimization failure is real, original bytes survive retry and authoritative GET',async()=>{
  await settings();await open();await manager().locator('input[type=file]').setInputFiles(out+'/broken.mp4');const broken=cell('broken');await expect(broken.getByRole('alert')).toContainText('original retained');
  const entries=await read('/homebg/'),entry=entries.find(e=>e.name==='broken');assert.equal(entry.media.status,'error');
  await broken.getByRole('button',{name:'重试',exact:true}).click();await expect.poll(async()=>report.requests.filter(r=>r.method==='POST'&&r.path==='/homebg/'+entry.id+'/optimize').length).toBe(1);
  await expect(broken.getByRole('alert')).toContainText('original retained');const actual=await read('/homebg/media?url='+encodeURIComponent(entry.url));assert.equal(actual.status,'error');
  const bytes=await context.request.get(origin+entry.url);assert.equal(bytes.status(),200);assert.deepEqual(await bytes.body(),await fs.readFile(out+'/broken.mp4'));await shot('video-failure-retained');
  await manager().getByRole('button',{name:'取消',exact:true}).click();await dialog().locator('footer').getByRole('button',{name:'取消',exact:true}).click();
 });
 await journey('shared delete cancel/confirm targets only synthetic unused image; protected home/saved nav remain, 393px real hit tests',async()=>{
  await page.setViewportSize({width:393,height:852});await settings();await open();assert(await manager().locator('.cell').evaluateAll(cells=>cells.every(c=>c.getBoundingClientRect().width>=128)));await geometry('.bgm-mask .bgm-foot','393 picker footer');await shot('picker-393');
  await expect(cell('Synthetic home protected').getByTitle('删除',{exact:true})).toBeDisabled();await expect(cell('synthetic').filter({has:page.locator('[data-ext="mp4"]')}).getByTitle('删除',{exact:true})).toBeDisabled();
  const image=cell('synthetic').filter({has:page.locator('[data-ext="png"]')});await image.hover();await image.getByTitle('删除',{exact:true}).click();const confirm=page.getByRole('dialog',{name:'删除背景',exact:true});await expect(confirm).toContainText('共享图库删除');await geometry('.bgm-delete','393 delete confirmation');await shot('delete-confirm-393');
  const before=await read('/homebg/');await confirm.getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await read('/homebg/'),before);
  await image.hover();await image.getByTitle('删除',{exact:true}).click();await confirm.getByRole('button',{name:'确认删除',exact:true}).click();await expect(confirm).toHaveCount(0);await expect(image).toHaveCount(0);
  const entry=before.find(e=>e.name==='synthetic'&&e.ext==='png');assert(!(await read('/homebg/')).some(e=>e.id===entry.id));assert.equal((await context.request.get(origin+entry.url)).status(),404);
  await manager().getByRole('button',{name:'取消',exact:true}).click();await dialog().locator('footer').getByRole('button',{name:'取消',exact:true}).click();assert.deepEqual(await read('/auth/me'),homeBefore);assert.deepEqual(await read('/operations/backups/client-preferences'),prefsBefore);
 });
 assert.deepEqual(await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage).filter(([k])=>k.startsWith('stella_home_')))),localBefore);
 assert.deepEqual(report.pageerrors,[]);assert.deepEqual(report.external,[]);
 // Existing two-slot media admission also covers simultaneous thumbnails.
 // Preserve every observed rejection: functional journeys do NOT certify a
 // zero-error gallery load. Only that exact existing 503 is classified here.
 report.mediaAdmissionFailures=report.responses.filter(r=>r.status===503&&new URL(r.url).pathname.startsWith('/assets/homebg/')&&r.body.includes('Media concurrency limit reached'));
 assert.deepEqual(report.responses.filter(r=>!report.mediaAdmissionFailures.includes(r)),[]);
 assert.equal(report.console.length,report.mediaAdmissionFailures.length);
 for(const error of report.console)assert(error.includes('503 (Service Unavailable)'));
 report.zeroMediaAdmissionFailures=report.mediaAdmissionFailures.length===0;
 assert(!report.requests.some(r=>r.checking&&['PATCH','PUT','POST','DELETE'].includes(r.method)&&['/auth/me','/operations/backups/client-preferences'].includes(r.path)));
}finally{report.players=await page.locator('video').evaluateAll(videos=>videos.map(v=>({src:v.src,currentSrc:v.currentSrc,readyState:v.readyState,networkState:v.networkState,error:v.error?.message,canPlay:v.canPlayType('video/mp4; codecs="avc1.42E01E"')})));await shot('final-state');await fs.writeFile(out+'/results.json',JSON.stringify(report,null,2));await context.close();await browser.close();}
