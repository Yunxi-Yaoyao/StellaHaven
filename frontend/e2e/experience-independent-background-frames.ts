import {expect,type Page,type TestInfo} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const tools=fileURLToPath(new URL('../../tools/experience-fixture/',import.meta.url));
/** Observe from document creation, not just the eventual settled screenshot. */
export async function observePresentation(page:Page){
 await page.addInitScript(()=>{
  const w=window as any;w.__backgroundFrames=[];
  const sample=()=>{
   const el=document.querySelector('.external-page'),f=el?.querySelector('iframe'),overlay=el?.querySelector('.external-loading');
   if(el&&f){
    const ancestors=[];for(let e:Element|null=el;e;e=e.parentElement){const s=getComputedStyle(e);ancestors.push({tag:e.tagName,opacity:s.opacity,visibility:s.visibility,transform:s.transform});}
    const s=getComputedStyle(f),o=overlay&&getComputedStyle(overlay);
    w.__backgroundFrames.push({t:performance.now(),visibility:s.visibility,opacity:s.opacity,background:getComputedStyle(el).backgroundImage,homeBackground:el.classList.contains('home-background'),overlay:o?{opacity:Number(o.opacity),background:o.backgroundColor,classes:overlay!.className}:null,ancestors,
     animations:el.getAnimations({subtree:true}).map(a=>({state:a.playState,time:a.currentTime,timing:a.effect?.getComputedTiming(),property:(a as CSSTransition).transitionProperty}))});
   }
   requestAnimationFrame(sample);
  };requestAnimationFrame(sample);
 });
}
/** Scope starts at the actual DOM configuration change, NOT the async request
 * start or the eventual ACK. Keep every subsequent sample, including regressions. */
export function assertContinuousExposure(samples:any[],startAtHome=false){
 const start=startAtHome?samples.findIndex(s=>s.homeBackground===true):0;
 expect(start,'target presentation configuration must have been sampled').toBeGreaterThanOrEqual(0);
 const scoped=samples.slice(start);
 const presented=(s:any)=>s.visibility==='visible'&&s.opacity==='1'&&s.ancestors.every((a:any)=>a.opacity==='1'&&a.visibility==='visible');
 const first=scoped.findIndex(presented);
 expect(first,'a fully presented iframe and ancestor frame must exist').toBeGreaterThanOrEqual(0);
 expect(scoped.slice(first).every(s=>presented(s)&&(!startAtHome||s.homeBackground===true)),'iframe and ancestors stay continuously exposed after their first presented frame').toBe(true);
}
/** Only finite scene/ancestor transitions; never fast-forward or disable motion. */
export async function settlePresentation(page:Page,info:TestInfo,name:string,startAtHome=false){
 const before=await page.evaluate(async()=>{
  const el=document.querySelector('.external-page')!;
  const collect=()=>{
   const animations=new Set(el.getAnimations({subtree:true}));
   for(let p=el.parentElement;p;p=p.parentElement)for(const a of p.getAnimations())animations.add(a);
   return [...animations].filter(a=>Number.isFinite(a.effect?.getComputedTiming().endTime)&&a.playState!=='finished');
  };
  const observed:any[]=[];
  for(let finite=collect();finite.length;finite=collect()){
   const wave=finite.map(a=>({property:(a as CSSTransition).transitionProperty,state:a.playState,time:a.currentTime,timing:a.effect?.getComputedTiming(),target:(a.effect as KeyframeEffect).target instanceof Element?((a.effect as KeyframeEffect).target as Element).className:null,keyframes:(a.effect as KeyframeEffect).getKeyframes()}));
   observed.push(...wave);
   const results=await Promise.allSettled(finite.map(a=>a.finished));
   for(const [i,result]of results.entries())if(result.status==='rejected'){
    // Vue can interrupt a loading-node enter with its legitimate ACK leave,
    // or remove the node on transitionend. Follow the replacement promise;
    // never ignore cancellation of a connected, nontransitioning node.
    const target=(finite[i].effect as KeyframeEffect).target;
    if(!(target instanceof Element)||!target.matches('.external-loading'))throw result.reason;
    const replacement=target.getAnimations().some(a=>a!==finite[i]&&Number.isFinite(a.effect?.getComputedTiming().endTime)&&a.playState==='running');
    if(target.isConnected&&!replacement)throw result.reason;
    Object.assign(wave[i],{removedOnLeave:!target.isConnected,replacedByLeave:target.isConnected});
   }
  }
  // Vue removes the leaving element on finished; the following two presentation
  // opportunities prove both removal and a committed compositor frame.
  await new Promise<void>(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r())));
  return observed;
 });
 const samples=await page.evaluate(()=>(window as any).__backgroundFrames);
 await info.attach(name+'-presentation.json',{body:JSON.stringify({awaited:before,samples},null,2),contentType:'application/json'});
 await expect(page.locator('.external-page .external-loading'),'the legitimate leave transition must actually finish').toHaveCount(0);
 // A wait must not turn disappearance/reappearance into a pass.
 assertContinuousExposure(samples,startAtHome);
 return {awaited:before,samples};
}
/** Real compositor filmstrip, including the FIRST frame and every delivered intermediate frame. */
export async function filmstrip(page:Page,info:TestInfo,name:string){
 const box=(await page.locator('.external-page').boundingBox())!;
 const points=[[box.x+box.width*.25,box.y+box.height*.8],[box.x+box.width*.75,box.y+box.height*.8]];
 const overlay=await page.locator('.external-loading').evaluate(el=>getComputedStyle(el).backgroundColor.match(/\d+/g)!.map(Number));
 const cdp=await page.context().newCDPSession(page),shots:{file:string;timestamp?:number}[]=[];
 let first!:()=>void;const firstFrame=new Promise<void>(resolve=>{first=resolve;});
 cdp.on('Page.screencastFrame',event=>{
  const file=info.outputPath(`${name}-frame-${String(shots.length).padStart(3,'0')}.png`);
  fs.writeFileSync(file,Buffer.from(event.data,'base64'));shots.push({file,timestamp:event.metadata.timestamp});
  void cdp.send('Page.screencastFrameAck',{sessionId:event.sessionId});
  first();
 });
 await cdp.send('Page.startScreencast',{format:'png',everyNthFrame:1});
 await firstFrame; // The first, still-hidden loading frame is part of the oracle.
 return async()=>{
  await cdp.send('Page.stopScreencast');await cdp.detach();
  const results=shots.map(shot=>({...shot,pixels:JSON.parse(execFileSync('python3',[path.join(tools,'sample_pixels.py'),shot.file,JSON.stringify(points)],{encoding:'utf8'})).pixels}));
  await info.attach(name+'-filmstrip.json',{body:JSON.stringify({points,overlay,frames:results},null,2),contentType:'application/json'});
  return {frames:results,overlay};
 };
}
/** A legitimate dark loading overlay fades away. A white flash, reversal or
 * unrelated colour is not made acceptable by a correct final screenshot. */
export function assertContinuousComposition(shots:{pixels:number[][]}[],expected:number[][],overlay:number[]){
 expect(shots.length,'compositor filmstrip must contain first/intermediate frames').toBeGreaterThan(1);
 expect(shots[0].pixels,'first composited frame is the legitimate loading canvas, never the native child').toEqual([overlay,overlay]);
 let previous=-.03,intermediate=false;
 for(const shot of shots){
  const channels=shot.pixels.flatMap((pixel,i)=>pixel.map((v,c)=>({v,base:overlay[c],delta:expected[i][c]-overlay[c]}))).filter(x=>Math.abs(x.delta)>15);
  const alpha=channels.reduce((sum,c)=>sum+(c.v-c.base)/c.delta,0)/channels.length;
  if(alpha>.03&&alpha<.97)intermediate=true;
  expect(alpha,'no bright/native flash during the legitimate fade').toBeLessThanOrEqual(1.03);
  expect(alpha,'no blackout beyond the loading overlay').toBeGreaterThanOrEqual(-.03);
  expect(alpha,'composited background must not regress while the overlay leaves').toBeGreaterThanOrEqual(previous-.04);
  for(const c of channels)expect(Math.abs(c.v-(c.base+c.delta*alpha)),'both sample points must be the same continuous overlay blend').toBeLessThanOrEqual(4);
  previous=alpha;
 }
 expect(intermediate,'the real, non-disabled transition must have intermediate composited frames').toBe(true);
 expect(shots.at(-1)!.pixels,'final compositor frame is exactly the original required background').toEqual(expected);
}
