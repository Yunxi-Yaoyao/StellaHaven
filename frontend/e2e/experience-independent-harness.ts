import {test as base,expect,type Page} from '@playwright/test';
import fs from 'node:fs';
export const MAIN='http://127.0.0.1:15487';
export const CHILD='http://127.0.0.1:15488'; // Intercepted, genuinely different origin; no server/proxy.
export const ID='qa-drive';
export const expected=[
 {id:'home',label:'首页',href:'/'},
 {id:ID,label:'测试网盘',href:'/apps/'+ID},
 {id:'quota',label:'测试额度',href:'/apps/quota'},
 {id:'settings',label:'控制中心',href:'/settings'},
];
export const entries=[{id:'home',title:'首页'},{id:ID,title:'测试网盘'},{id:'quota',title:'测试额度'},{id:'settings',title:'控制中心'},{id:'notes',visible:false},{id:'status',visible:false}];
export const defaultModule=()=>({id:ID,name:'测试网盘',icon:'drive',mode:'isolated_proxy',adapter:'generic',browser_url:CHILD+'/frame',origin:CHILD,enabled:true,keep_alive:true,background:'solid',injection:{active:null,draft:null,previous:null}});
type GateName='auth'|'navigation'|'modules';
export class Gate {
 private resolve!:()=>void; private promise:Promise<void>; released=false; status=200; requests=0;
 constructor(){this.promise=new Promise(r=>this.resolve=r);}
 release(status=200){this.status=status;this.released=true;this.resolve();}
 async wait(){this.requests++;await this.promise;}
}
export type HarnessOptions={held?:GateName[];module?:any;storage?:Record<string,string>;background?:string;childHTML?:()=>string;childScript?:string;holdChildScript?:boolean};
export async function setup(page:Page,options:HarnessOptions={}){
 const gates={auth:new Gate(),navigation:new Gate(),modules:new Gate(),script:new Gate()};
 for(const name of ['auth','navigation','modules'] as GateName[])if(!options.held?.includes(name))gates[name].release();
 if(!options.holdChildScript)gates.script.release();
 const modules=[options.module||defaultModule(),{...defaultModule(),id:'quota',name:'测试额度',mode:'link'}];
 const user={id:'qa-owner',username:'qa-owner',display_name:'隔离QA',is_admin:false,avatar_url:'/avatar.png',home_bg:options.background||MAIN+'/qa-pattern.svg',email:'',email_verified:false};
 const requests:any[]=[],unknown:string[]=[],errors:string[]=[],consoleErrors:string[]=[];
 await page.context().addInitScript(({storage,main})=>{
  if(location.origin===main){localStorage.setItem('stella_live2d','off');localStorage.setItem('stella_home_particles','off');for(const [k,v]of Object.entries(storage))localStorage.setItem(k,v);}
  const w=window as any;w.__experience={navigation:[],messages:[],frames:[],events:[],start:performance.timeOrigin};
  const stamp=()=>performance.now();
  window.addEventListener('message',e=>{if(e.data?.type?.startsWith('stella-bg-'))w.__experience.messages.push({t:stamp(),origin:e.origin,sourceParent:e.source===parent,data:e.data});});
  document.addEventListener('DOMContentLoaded',()=>w.__experience.events.push({type:'DCL',t:stamp()}));
  window.addEventListener('load',()=>w.__experience.events.push({type:'load',t:stamp()}));
  let prev='',framePrev='';
  function sample(){
   const rows=[...document.querySelectorAll<HTMLAnchorElement>('.sidebar nav a.nav-item')].filter(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)!==0&&s.pointerEvents!=='none'&&r.width>0&&r.height>0&&!el.closest('[inert]');}).map(el=>{
    const href=el.getAttribute('href')||'',r=el.getBoundingClientRect();return {id:href.startsWith('/apps/')?href.split('/')[2]:href==='/'?'home':href.slice(1),label:el.querySelector('.label')?.textContent?.trim()||el.textContent?.trim(),href,x:r.x,y:r.y,width:r.width,height:r.height};
   });
   const next=JSON.stringify(rows);if(next!==prev){prev=next;w.__experience.navigation.push({t:stamp(),path:location.pathname,rows});}
   const frames=[...document.querySelectorAll<HTMLIFrameElement>('.external-page iframe')].map(f=>{const s=getComputedStyle(f),r=f.getBoundingClientRect();return {src:f.src,opacity:s.opacity,visibility:s.visibility,display:s.display,x:r.x,y:r.y,width:r.width,height:r.height};});
   const fp=JSON.stringify(frames);if(fp!==framePrev){framePrev=fp;w.__experience.frames.push({t:stamp(),frames});}
  }
  new MutationObserver(sample).observe(document,{childList:true,attributes:true,subtree:true,characterData:true});
  function tick(){sample();requestAnimationFrame(tick);}requestAnimationFrame(tick);
 },{storage:options.storage||{},main:MAIN});
 page.on('pageerror',e=>errors.push(e.stack||e.message));
 page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
 await page.context().routeWebSocket('**/*',ws=>{
  const u=new URL(ws.url());if(u.origin===MAIN.replace('http:','ws:')&&['/','/ws/notifications'].includes(u.pathname)){if(u.pathname==='/')ws.send(JSON.stringify({type:'connected'}));return;}
  unknown.push(ws.url());ws.close();
 });
 await page.context().route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();
  const json=(data:any,status=200)=>route.fulfill({json:data,status});
  if(u.origin===CHILD&&m==='GET'&&p==='/frame')return route.fulfill({contentType:'text/html',body:options.childHTML?.()||'<!doctype html><html><body><main>受控跨域网站</main></body></html>'});
  if(u.origin===CHILD&&m==='GET'&&p==='/template.js'){await gates.script.wait();return route.fulfill({contentType:'application/javascript',body:options.childScript||''});}
  if(u.origin!==MAIN){unknown.push(m+' '+req.url());return route.abort('blockedbyclient');}
  if(m==='GET'&&(p.startsWith('/src/')||p.startsWith('/@')||p.startsWith('/node_modules/')||['/avatar.png','/favicon.svg'].includes(p)))return route.continue();
  if(m==='GET'&&req.isNavigationRequest()&&req.frame()===page.mainFrame()&&(p==='/'||p==='/drive'||p==='/settings'||p==='/notes'||p.startsWith('/apps/')||p==='/login'))return route.continue();
  if(p==='/qa-pattern.svg')return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1000"><rect width="600" height="1000" fill="#e43c50"/><rect x="600" width="600" height="1000" fill="#28b8ca"/></svg>'});
  requests.push({t:Date.now(),path:p,method:m});
  if(p==='/auth/me'&&m==='GET'){await gates.auth.wait();return json(user,gates.auth.status);}
  if(p==='/navigation'&&m==='GET'){await gates.navigation.wait();return json({entries,legacy_routes:{drive:ID}},gates.navigation.status);}
  if(p==='/external-modules'&&m==='GET'){await gates.modules.wait();return json(modules,gates.modules.status);}
  if(p==='/auth/security'&&m==='GET')return json({enabled:true,configured:true,elevated:false,single_user:true,setup_required:false});
  if(p==='/notifications/unread-count'&&m==='GET')return json({count:0});
  if(p==='/auth/activity'&&m==='POST')return json({ok:true});
  if(p==='/external-modules/'+ID&&m==='GET')return json(modules[0]);
  if(p==='/external-modules/'+ID+'/launch'&&m==='POST')return json({mode:'isolated_proxy',method:'GET',url:CHILD+'/frame'});
  if(m==='GET'&&['/auth/avatars','/auth/sessions','/homebg/','/website-templates'].includes(p))return json([]);
  if(p==='/auth/email-service'&&m==='GET')return json({ready:false});
  if(p==='/config/public-host'&&m==='GET')return json({value:''});
  unknown.push(m+' '+req.url());return route.abort('blockedbyclient');
 });
 return {gates,requests,unknown,errors,consoleErrors,modules,user};
}
export async function frames(page:Page,count=3){await page.evaluate(n=>new Promise<void>(resolve=>{function run(){if(--n<=0)resolve();else requestAnimationFrame(run);}requestAnimationFrame(run);}),count);}
export async function rows(page:Page){return page.locator('.sidebar nav a.nav-item').evaluateAll(els=>els.map(el=>{const href=el.getAttribute('href')||'';return{id:href.startsWith('/apps/')?href.split('/')[2]:href==='/'?'home':href.slice(1),label:el.querySelector('.label')?.textContent?.trim(),href};}));}
export const test=base.extend<{evidence: {h?:Awaited<ReturnType<typeof setup>>}}>({evidence:async({page},use,info)=>{
 const evidence:{h?:Awaited<ReturnType<typeof setup>>}={};await use(evidence);
 const data=await page.evaluate(()=> (window as any).__experience).catch(()=>null);
 const childStates=await Promise.all(page.frames().filter(f=>f!==page.mainFrame()&&f.url().startsWith(CHILD)).map(f=>f.evaluate(()=>({url:location.href,timeline:(window as any).__experience,roots:[document.documentElement,document.body,document.getElementById('root')].filter(Boolean).map(e=>({tag:e!.tagName,background:getComputedStyle(e!).backgroundColor,scheme:getComputedStyle(e!).colorScheme,image:getComputedStyle(e!).backgroundImage}))})).catch(()=>null)));
 const parent=await page.locator('.external-page').evaluateAll(els=>els.map(el=>({background:getComputedStyle(el).backgroundImage,scheme:getComputedStyle(el).colorScheme,frameScheme:el.querySelector('iframe')&&getComputedStyle(el.querySelector('iframe')!).colorScheme}))).catch(()=>[]);
 const timeline=JSON.stringify({browser:data,children:childStates,parent,requests:evidence.h?.requests,unknown:evidence.h?.unknown,pageErrors:evidence.h?.errors,consoleErrors:evidence.h?.consoleErrors},null,2);
 fs.writeFileSync(info.outputPath('experience-timeline.json'),timeline);
 await info.attach('experience-timeline.json',{body:timeline,contentType:'application/json'});
 await page.screenshot({path:info.outputPath('final.png')}).catch(()=>{});
 if(evidence.h){expect.soft(evidence.h.unknown,'all unmatched network is denied; fixture must declare every request').toEqual([]);expect.soft(evidence.h.errors,'no runtime errors').toEqual([]);}
}});
export {expect};
