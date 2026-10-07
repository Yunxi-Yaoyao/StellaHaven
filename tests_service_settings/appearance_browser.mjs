import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.STELLA_TEST_PLAYWRIGHT||'/opt/Yunxi-workstation/Stella/frontend/node_modules/@playwright/test');
const browser=await chromium.launch({headless:true,executablePath:process.env.STELLA_TEST_CHROMIUM,args:['--no-sandbox','--no-proxy-server']});
const context=await browser.newContext();
const page=await context.newPage();
const origin=process.env.APPEARANCE_ORIGIN, mode=process.env.APPEARANCE_MODE;
const errors=[];page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
function assert(value,message){if(!value)throw Error(message);}
try {
  await page.goto(origin+'/');
  let evidence;
  if(mode.startsWith('drive')) {
    await page.waitForTimeout(150);
    assert(await page.locator('#file').textContent()==='OpenList backups.tar','filename changed');
    assert(await page.locator('#file-link').count()===1 && await page.locator('#other-link').count()===1 && await page.locator('#header-other').count()===1,'user GitHub link removed');
    if(mode==='drive-simple') {
      await page.waitForFunction(()=>document.querySelector('nav')?.contains(document.querySelector('[aria-label="switch layout"]')));
      assert(await page.locator('#project').count()===0,'brand project not removed');
    } else {
      assert(await page.locator('#brand').textContent()==='OpenList','simplified=false still removed brand');
      assert(await page.locator('header [aria-label="switch layout"]').count()===1,'layout changed when disabled');
    }
    await page.evaluate(()=>fetch('/api/fs/move',{method:'POST',body:JSON.stringify({src_dir:'/src',dst_dir:'/dst'})}));
    await page.waitForFunction(()=>cache.size===0);
    await page.evaluate(()=>fetch('/api/fs/remove',{method:'POST',body:new FormData()}));
    await page.waitForSelector('[data-stella-admin-required]');
    await page.evaluate(()=>new Promise(resolve=>{const x=new XMLHttpRequest();x.open('POST','/api/fs/remove');x.onload=resolve;x.send('synthetic');}));
    const color=await page.evaluate(()=>getComputedStyle(document.body).backgroundColor);
    await page.evaluate(()=>window.postMessage({type:'stella-bg-mode',mode:'image'},location.origin));
    await page.waitForFunction(()=>document.documentElement.dataset.bgMode==='image');
    assert(await page.evaluate(()=>localStorage.getItem('stella_drive_bg_mode')==='image'&&localStorage.getItem('__stella_drive_bg_mode__')==='image'),'background keys not synchronized');
    await page.evaluate(()=>window.postMessage({type:'stella-bg-mode',mode:'solid'},location.origin));
    await page.waitForFunction(()=>!document.documentElement.hasAttribute('data-bg-mode'));
    assert(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor)===color,'solid did not restore upstream background');
    await page.evaluate(()=>{history.replaceState({},'', '/?bgmode=image');window.dispatchEvent(new PopStateEvent('popstate'));});
    assert(await page.evaluate(()=>!document.documentElement.hasAttribute('data-bg-mode')),'stale URL overrode saved device choice');
    evidence={mode,color,filename:await page.locator('#file').textContent(),errors};
  } else {
    const response=await page.request.get(origin+'/code.js');
    const code=await response.text(), version=response.headers()['x-stella-injection-version'];
    // Simulate earlier authority and nginx v1 CSS on the same already-open DOM.
    await page.evaluate(()=>{window.__stellaBuiltin_gallery='prior-version';const s=document.createElement('style');s.dataset.stellaBuiltin='gallery';s.textContent='img[alt="Immich logo"]{content:url("old-logo.png")}';document.head.append(s);});
    await page.addScriptTag({content:code});
    await page.waitForTimeout(50);
    const logo=await page.locator('img').evaluate(e=>getComputedStyle(e).content);
    assert(await page.locator('[data-stella-gallery-base]').count()===0,'legacy fixed logo CSS retained');
    assert(await page.locator('style[data-stella-builtin="gallery"]').count()===1,'duplicate styles');
    if(mode==='gallery-original')assert(!logo.includes('avatar.png')&&!logo.includes('old-logo'),'disabled logo still forced');
    else assert(logo.includes('avatar.png'),'stella logo not applied');
    assert(await page.evaluate(()=>window.ownerOnlySecret??null)===null,'anonymous received custom code');
    await page.addScriptTag({content:code});
    assert(await page.locator('style[data-stella-builtin="gallery"]').count()===1,'dedupe failed');
    evidence={mode,logo,version,code,errors};
  }
  await page.screenshot({path:process.env.APPEARANCE_SCREENSHOT});
  console.log(JSON.stringify(evidence));
} finally {await browser.close();}
