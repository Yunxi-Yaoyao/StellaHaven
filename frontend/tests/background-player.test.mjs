import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';

test('background player uses one real video, poster, quality swap and visibility pause', async t => {
  const server = await createServer({ configFile:false, appType:"custom", plugins:[vue()], server:{host:'127.0.0.1',port:0},logLevel:'error' });
  server.middlewares.use('/__bg_test',async(req,res,next)=>{
    try {const html=await server.transformIndexHtml('/__bg_test',`<div id="app" style="position:relative;width:600px;height:400px"></div><script type="module">
      import {createApp,h,ref} from 'vue'; import BgLayer from '/src/modules/home/BgLayer.vue';
      import {backgroundMedia} from '/src/modules/home/backgroundMedia.ts';
      backgroundMedia['/assets/homebg/test.mp4']={url:'/assets/homebg/test.mp4',status:'ready',poster:'/assets/poster.webp',thumbnail:'/assets/thumb.webp',variants:{original:'/assets/homebg/test.mp4',compressed1:'/assets/homebg/test-q1.mp4',compressed2:'/assets/homebg/test-q2.mp4'}};
      const url=ref('/assets/homebg/test.mp4'); window.setBackground=v=>url.value=v;
      window.createdVideos=0; const create=document.createElement.bind(document);document.createElement=(tag,...args)=>{if(tag==='video')window.createdVideos++;return create(tag,...args)};
      createApp({render:()=>h(BgLayer,{url:url.value,crop:{cx:.5,cy:.5,w:1,h:1}})}).mount('#app');
      </script>`);res.setHeader('Content-Type','text/html');res.end(html);}catch(e){next(e)}
  });await server.listen();t.after(()=>server.close());
  const browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox'],headless:true});t.after(()=>browser.close());
  const page=await browser.newPage();
  await page.route('**/homebg/media**',route=>route.fulfill({json:{url:'/assets/homebg/test.mp4',status:'ready',poster:'/assets/poster.webp',thumbnail:'/assets/thumb.webp',variants:{original:'/assets/homebg/test.mp4',compressed1:'/assets/homebg/test-q1.mp4',compressed2:'/assets/homebg/test-q2.mp4'}}}));
  await page.route('**/homebg/',route=>route.fulfill({json:[]}));
  await page.route('**/assets/**',route=> { if (!route.request().url().endsWith('.mp4')) return route.fulfill({status:200,body:''}); });
  page.on('pageerror',e=>console.log('PAGE ERROR',e.message));
  page.setDefaultTimeout(6000);
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/__bg_test`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('video'));
  assert.equal(await page.evaluate(()=>window.createdVideos),1,'must not create hidden metadata video');
  await page.waitForFunction(()=>document.querySelector('video')?.getAttribute('src')?.includes('q1'),null,{timeout:5000});
  assert.equal(await page.evaluate(()=>window.createdVideos),1,'must not create hidden metadata video');
  assert.equal(await page.locator('video').getAttribute('poster'),'/assets/poster.webp');
  await page.locator('video').evaluate(el=>{Object.defineProperty(el,'videoWidth',{value:2560,configurable:true});Object.defineProperty(el,'videoHeight',{value:1440,configurable:true});el.dispatchEvent(new Event('loadedmetadata'));el.dispatchEvent(new Event('loadeddata'));window.firstVideo=el;});
  await page.evaluate(async()=>{const path='/src/modules/home/backgroundMedia.ts';const m=await import(path);m.quality.value='compressed2';});
  await page.waitForFunction(()=>document.querySelector('video[src*="q2"]'));
  assert.equal(await page.evaluate(()=>window.firstVideo.isConnected),true,'previous video remains until replacement ready');
  await page.locator('video[src*="q2"]').evaluate(el=>{Object.defineProperty(el,'videoWidth',{value:1920,configurable:true});Object.defineProperty(el,'videoHeight',{value:1080,configurable:true});el.dispatchEvent(new Event('loadedmetadata'));el.dispatchEvent(new Event('loadeddata'));});
  await page.waitForFunction(()=>document.querySelectorAll('video').length===1);
  assert.equal(await page.evaluate(()=>window.firstVideo.isConnected),false);
  await page.locator('video').evaluate(el=>{el.pause=()=>{window.paused=true;};Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new Event('visibilitychange'));});
  assert.equal(await page.evaluate(()=>window.paused),true);
});
