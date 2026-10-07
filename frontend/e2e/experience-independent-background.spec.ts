import {test,expect,setup,frames,defaultModule,MAIN,CHILD,ID} from './experience-independent-harness';
import type {Page,Frame,TestInfo} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const tools=fileURLToPath(new URL('../../tools/experience-fixture/',import.meta.url));
// Re-extracted from the selected source on EVERY run; never a copied bridge.
const exported=JSON.parse(execFileSync('python3',[path.join(tools,'export_template.py'),MAIN],{encoding:'utf8'}));
const code=exported.code;
const moduleFor=(background='home',enabled=true)=>({...defaultModule(),background,injection:{active:{...code,enabled,csp_policy:'reject',version:'source-export'},draft:null,previous:null}});
function childHTML(enabled=true){return `<!doctype html><html><head><meta charset="utf-8"><meta name="color-scheme" content="dark"><style>html,body,#root{margin:0;min-height:100vh;background:#f5f5f5}#directory{padding:20px}</style>${enabled?`<style>${code.css}</style><script defer src="/template.js"></script>`:''}</head><body><div id="root"><div id="directory"><nav class="hope-breadcrumb">受控目录</nav><div class="list viselect-container"><div class="list-item">QA 文件</div></div></div></div></body></html>`;}
async function start(page:Page,evidence:any,options:any={}){
 const enabled=options.enabled!==false;
 const h=evidence.h=await setup(page,{...options,module:moduleFor(options.background||'home',enabled),childHTML:()=>childHTML(enabled),childScript:code.js,background:options.media});
 await page.goto('/apps/'+ID,{waitUntil:'domcontentloaded'});
 await expect(page.locator('.external-page iframe')).toBeAttached();
 await expect.poll(()=>page.frames().some((f:any)=>f.url().startsWith(CHILD+'/frame'))).toBe(true);
 const child=page.frames().find((f:any)=>f.url().startsWith(CHILD+'/frame'))!;
 await expect(child.locator('#root')).toBeAttached();
 return {h,child,iframe:page.locator('.external-page iframe')};
}
async function roots(child:Frame){return child.evaluate(()=>({mode:document.documentElement.dataset.bgMode||'solid',roots:[document.documentElement,document.body,document.getElementById('root')].map(el=>{const s=getComputedStyle(el!);return {background:s.backgroundColor,image:s.backgroundImage,scheme:s.colorScheme};}),layers:[...document.querySelectorAll('.hope-breadcrumb,.list,.list-item')].map(el=>getComputedStyle(el).backgroundColor),media:document.querySelectorAll('video,img').length}));}
async function pixels(page:Page,info:TestInfo,name:string){
 const box=(await page.locator('.external-page').boundingBox())!;
 const points=[[box.x+box.width*.25,box.y+box.height*.8],[box.x+box.width*.75,box.y+box.height*.8]];
 const file=info.outputPath(name+'.png');await page.screenshot({path:file});
 const result=JSON.parse(execFileSync('python3',[path.join(tools,'sample_pixels.py'),file,JSON.stringify(points)],{encoding:'utf8'}));
 await info.attach(name+'-pixels.json',{body:JSON.stringify({points,...result}),contentType:'application/json'});return result.pixels;
}
function assertTransparent(value:any){expect(value.mode).toBe('image');for(const r of value.roots){expect(r.background).toBe('rgba(0, 0, 0, 0)');expect(r.image).toBe('none');}expect(value.roots[0].scheme).toBe('normal');expect(value.layers.every((v:string)=>v==='rgba(0, 0, 0, 0)')).toBe(true);expect(value.media).toBe(0);}
test.beforeEach(async({},info)=>{await info.attach('template-provenance.json',{body:JSON.stringify(exported.provenance,null,2),contentType:'application/json'});});

test('background actual template waits hidden until transparency ACK, not load',async({page,evidence},info)=>{
 const {h,child,iframe}=await start(page,evidence,{holdChildScript:true});
 await expect.poll(()=>h.gates.script.requests).toBe(1);await frames(page,5);
 expect.soft(exported.provenance.has_ready_marker,'source export must carry the real readiness opt-in').toBe(true);
 expect.soft(await iframe.evaluate((el:any)=>getComputedStyle(el).visibility),'unready dark/white child must not be exposed').toBe('hidden');
 await page.screenshot({path:info.outputPath('01-template-held.png')});
 h.gates.script.release();
 await expect.poll(()=>child.evaluate(()=>document.documentElement.dataset.bgMode)).toBe('image');
 await expect(iframe).toBeVisible();assertTransparent(await roots(child));
 const history=await page.evaluate(()=> (window as any).__experience);
 const ack=history.messages.find((m:any)=>m.data.type==='stella-bg-ready');
 expect.soft(ack,'ACK must come from actual exported JS, not fixture code').toBeTruthy();
 if(ack){expect(ack.origin).toBe(CHILD);expect(ack.data).toMatchObject({mode:'image',module_id:ID});expect(typeof ack.data.request_id).toBe('string');const early=history.frames.filter((s:any)=>s.t<ack.t&&s.frames.some((f:any)=>f.visibility!=='hidden'&&f.display!=='none'&&Number(f.opacity)>0));expect(early,'no visible iframe snapshot before verified ACK').toEqual([]);}
 expect(await pixels(page,info,'transparent-image')).toEqual([[228,60,80],[40,184,202]]);
});

test('background real image composition stays continuous on resize',async({page,evidence},info)=>{
 const {child}=await start(page,evidence);
 await expect.poll(()=>child.evaluate(()=>document.documentElement.dataset.bgMode)).toBe('image');assertTransparent(await roots(child));
 expect(await pixels(page,info,'image-wide')).toEqual([[228,60,80],[40,184,202]]);
 await page.setViewportSize({width:1100,height:800});await frames(page,4);
 expect(await pixels(page,info,'image-resized')).toEqual([[228,60,80],[40,184,202]]);
});

for(const input of [
 {name:'old current image',storage:{stella_drive_bg_mode:'image'},background:'solid',want:'image'},
 {name:'legacy-only image',storage:{__stella_drive_bg_mode__:'image'},background:'solid',want:'image'},
 {name:'current solid beats legacy image',storage:{stella_drive_bg_mode:'solid',__stella_drive_bg_mode__:'image'},background:'home',want:'solid'},
 {name:'invalid current falls through to legacy',storage:{stella_drive_bg_mode:'invalid',__stella_drive_bg_mode__:'image'},background:'solid',want:'image'},
 {name:'new explicit choice wins',storage:{stella_drive_bg_mode:'image',['stella_website_background_explicit:qa-owner:'+ID]:'1'},background:'solid',want:'solid'},
]){
 test('background device preference '+input.name,async({page,evidence},info)=>{
  const {child}=await start(page,evidence,{storage:input.storage,background:input.background});
  await child.waitForLoadState('load');await frames(page,4);
  expect.soft(await page.locator('.external-page').evaluate((el:any)=>el.classList.contains('home-background'))).toBe(input.want==='image');
  expect.soft((await roots(child)).mode).toBe(input.want);
  if(input.want==='image')expect.soft(await pixels(page,info,'legacy-composite')).toEqual([[228,60,80],[40,184,202]]);
  expect(evidence.h!.requests.filter(r=>['PATCH','PUT','DELETE'].includes(r.method)),'legacy device choice must never silently publish server settings').toEqual([]);
 });
}

test('background injection disabled preserves native child and is not readiness-gated',async({page,evidence},info)=>{
 const {child,iframe}=await start(page,evidence,{enabled:false});await expect(iframe).toBeVisible();
 const value=await roots(child);expect(value.mode).toBe('solid');expect(value.roots.map((r:any)=>r.background)).toEqual(['rgb(245, 245, 245)','rgb(245, 245, 245)','rgb(245, 245, 245)']);
 expect(await pixels(page,info,'native-child')).toEqual([[245,245,245],[245,245,245]]);
});

test('background retained page follows real navigation readback and solid is reversible',async({page,evidence},info)=>{
 const {h,child}=await start(page,evidence,{background:'solid'});await child.waitForLoadState('load');
 expect((await roots(child)).mode).toBe('solid');
 const refresh=()=>page.evaluate(async()=>{const source='/src/stores/navigation.ts';await (await import(source)).loadNavigation();});
 // Simulate a server-side saved value. Readback goes through the REAL navigation
 // store and API; no mutation of Vue parent/child state and no settings write.
 h.modules[0].background='home';await refresh();
 await expect.poll(()=>child.evaluate(()=>document.documentElement.dataset.bgMode)).toBe('image');
 expect(await page.locator('.external-page').evaluate(el=>getComputedStyle(el).backgroundImage)).toContain('qa-pattern.svg');
 h.modules[0].background='solid';await refresh();
 await expect.poll(()=>child.evaluate(()=>document.documentElement.dataset.bgMode||'solid')).toBe('solid');
 expect((await roots(child)).roots.map((r:any)=>r.background)).toEqual(['rgb(20, 23, 31)','rgb(20, 23, 31)','rgb(20, 23, 31)']);
 expect(await page.locator('.external-page').evaluate(el=>getComputedStyle(el).backgroundImage)).toBe('none');
 expect(await pixels(page,info,'reversed-solid')).toEqual([[20,23,31],[20,23,31]]);
});

test('background rejects wrong origin, wrong source, module and stale ACK',async({page,evidence})=>{
 const {h,child,iframe}=await start(page,evidence,{holdChildScript:true});
 await expect.poll(()=>h.gates.script.requests).toBe(1);
 // A real request from the current child elicits the parent's current nonce.
 await child.evaluate(origin=>parent.postMessage({type:'stella-bg-request'},origin),MAIN);await frames(page,4);
 const mode=await child.evaluate(()=> (window as any).__experience.messages.find((m:any)=>m.data.type==='stella-bg-mode')?.data);
 expect.soft(mode,'parent responds to the actual child').toBeTruthy();
 const valid={type:'stella-bg-ready',module_id:ID,mode:'image',request_id:mode?.request_id||'unissued'};
 await page.evaluate(({childOrigin,data})=>{
  const source=document.querySelector('iframe')!.contentWindow;
  window.dispatchEvent(new MessageEvent('message',{origin:'https://wrong-origin.invalid',source,data}));
  window.dispatchEvent(new MessageEvent('message',{origin:childOrigin,source:window,data}));
 },{childOrigin:CHILD,data:valid});
 for(const payload of [{...valid,module_id:'different-module'},{...valid,request_id:'old-request'},{...valid,mode:'solid'}])await child.evaluate(({main,data})=>parent.postMessage(data,main),{main:MAIN,data:payload});
 await frames(page,4);
 expect.soft(await iframe.evaluate(el=>getComputedStyle(el).visibility),'untrusted ACKs cannot reveal the unstyled frame').toBe('hidden');
 h.gates.script.release();await expect.poll(()=>child.evaluate(()=>document.documentElement.dataset.bgMode)).toBe('image');await expect(iframe).toBeVisible();
 // Wrong parent source/origin must not reverse the child after real readiness.
 await child.evaluate(({main})=>{
  const data={type:'stella-bg-mode',mode:'solid',module_id:'qa-drive',request_id:'bad'};
  window.dispatchEvent(new MessageEvent('message',{origin:main,source:window,data}));
  window.dispatchEvent(new MessageEvent('message',{origin:'https://wrong-origin.invalid',source:parent,data}));
 },{main:MAIN});
 await frames(page);expect((await roots(child)).mode).toBe('image');
});

test('background video plays behind the genuinely transparent child',async({page,evidence},info)=>{
 const file=info.outputPath('controlled-video.webm');
 execFileSync('ffmpeg',['-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=12','-t','4','-c:v','libvpx','-an',file]);
 // Media is explicit, same-origin controlled input; every other unknown request remains denied.
 const {child}=await startVideo();
 async function startVideo(){const h=evidence.h=await setup(page,{module:moduleFor(),background:MAIN+'/qa-video.webm?fixture=1#media',childHTML:()=>childHTML(),childScript:code.js});await page.context().route(MAIN+'/qa-video.webm*',r=>r.fulfill({contentType:'video/webm',body:fs.readFileSync(file)}));await page.goto('/apps/'+ID);await expect.poll(()=>page.frames().some(f=>f.url().startsWith(CHILD+'/frame'))).toBe(true);return {h,child:page.frames().find(f=>f.url().startsWith(CHILD+'/frame'))!};}
 await expect.poll(()=>child.evaluate(()=>document.documentElement.dataset.bgMode)).toBe('image');assertTransparent(await roots(child));
 const video=page.locator('.external-page video');await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>v.readyState)).toBeGreaterThanOrEqual(2);
 expect(await video.evaluate((v:HTMLVideoElement)=>({muted:v.muted,paused:v.paused,width:v.videoWidth}))).toMatchObject({muted:true,paused:false,width:320});
 const t=await video.evaluate((v:HTMLVideoElement)=>v.currentTime),a=await pixels(page,info,'video-first');
 await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>v.currentTime)).toBeGreaterThan(t+.2);
 const b=await pixels(page,info,'video-next');expect(a,'composited pixel samples must change as outer video plays').not.toEqual(b);
});
