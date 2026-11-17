// Production App regression. Reuse the strict synthetic HTTP setup, not a copied App.
// frontend cwd; STELLA_APP_DIST / STELLA_GROUP_EVIDENCE / STELLA_CANVAS_CACHE must be absolute.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';

const cache=process.env.STELLA_CANVAS_CACHE;
assert(cache&&path.isAbsolute(cache),'set an owned STELLA_CANVAS_CACHE under frontend for module resolution');
fs.mkdirSync(cache,{recursive:true});
const fixture=fileURLToPath(new URL('./app-built.mjs',import.meta.url));
const original=fs.readFileSync(fixture,'utf8');
const start='  const shot=async name=>';
const end=' assert.deepEqual(result.errors,[]);';
assert(original.includes(start)&&original.includes(end),'fixture anchors changed; review adapter');
let source=original.slice(0,original.indexOf(start));
function replace(from,to){assert(source.includes(from),'fixture anchor changed: '+from);source=source.replace(from,to);}
replace('for(const width of [1365,1920,320,390,746]){',`for(const {width,height,zoom} of [
 {width:320,height:520,zoom:1},{width:320,height:520,zoom:1.25},
 {width:390,height:520,zoom:1},{width:390,height:520,zoom:1.25},
 {width:1365,height:900,zoom:1},{width:1365,height:900,zoom:1.25}
]){`);
replace('viewport:{width,height:width<500?900:1080}','viewport:{width,height}');
// Only this focused test adds live inventory and real traffic points. The original
// failing diagnostic is rerun separately with its unchanged no-inventory fixture.
replace('latest_metrics:[],latest_sys_metric:null','interfaces:{eth0:{up:true,is_default:true,is_physical:true}},latest_metrics:[],latest_sys_metric:null');
replace("(/^\\/monitors\\/\\d+\\/series$/.test(p)&&[...u.searchParams.keys()].every(k=>['start','end','step','limit'].includes(k)))", "(/^\\/monitors\\/\\d+\\/series$/.test(p)&&[...u.searchParams.keys()].every(k=>['start','end','step','limit'].includes(k)))||(p==='/nodes/7/metrics'&&u.searchParams.get('iface')==='eth0'&&[...u.searchParams.keys()].every(k=>['iface','start','end','limit'].includes(k)))");
replace("   if(m==='GET'&&p==='/nodes/map-topology')", "   if(m==='GET'&&p==='/nodes/7/metrics')return json(Array.from({length:12},(_,i)=>({iface:'eth0',ts:new Date(Date.parse(now)-i*5000).toISOString(),rx_delta:625000+(i%4)*125000,tx_delta:125000+(i%3)*25000})));\n   if(m==='GET'&&p==='/nodes/map-topology')");
source+=String.raw`
  const shot=async name=>{const file=path.join(out,name+'-'+width+'-css'+zoom+'.png');await page.screenshot({path:file});result.screenshots.push(file);};
  await page.goto(origin+'/status?view=overview#service-monitors');
  await page.getByText(long,{exact:true}).waitFor();
  await page.evaluate(zoom=>{document.documentElement.style.zoom=String(zoom);window.dispatchEvent(new Event('resize'));},zoom);
  await page.waitForTimeout(300);
  await page.locator('.ov-chart canvas').waitFor();
  await page.waitForFunction(()=>!document.querySelector('.traffic-hint'));
  await page.locator('.ov-chart').scrollIntoViewIfNeeded();await page.waitForTimeout(250);
  const chartGeometry=await page.locator('.ov-chart canvas').evaluate(canvas=>{
    const host=canvas.closest('.ov-chart'),box=canvas.closest('.chart-box');
    const rect=el=>el.getBoundingClientRect().toJSON();
    const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
    let colored=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i+3]>100&&Math.max(pixels[i],pixels[i+1],pixels[i+2])-Math.min(pixels[i],pixels[i+1],pixels[i+2])>35)colored++;
    return {canvas:rect(canvas),host:rect(host),box:rect(box),physical:[canvas.width,canvas.height],pointerEvents:getComputedStyle(canvas).pointerEvents,colored};
  });
  const within=(child,parent)=>child.left>=parent.left-1&&child.top>=parent.top-1&&child.right<=parent.right+1&&child.bottom<=parent.bottom+1;
  assert(chartGeometry.physical.every(n=>n>0));assert(chartGeometry.colored>20,JSON.stringify(chartGeometry));
  assert(within(chartGeometry.canvas,chartGeometry.host)&&within(chartGeometry.canvas,chartGeometry.box),JSON.stringify(chartGeometry));
  assert.notEqual(chartGeometry.pointerEvents,'none','traffic tooltip must remain interactive');
  const r=await page.locator('.ov-chart canvas').boundingBox();
  await page.mouse.move(r.x+r.width*0.7,r.y+r.height*0.5);
  await page.waitForFunction(()=>[...document.querySelectorAll('.ov-chart div')].some(el=>el.textContent.includes('↓ 下载')&&el.textContent.includes('bps')&&getComputedStyle(el).visibility!=='hidden'&&+getComputedStyle(el).opacity>0));
  await shot('traffic-hover');await page.mouse.move(0,0);
  const card=page.locator('.mon-card').first();
  await card.locator('.mon-heading button').scrollIntoViewIfNeeded();await page.waitForTimeout(250);
  await card.locator('.mon-heading button').click();await page.getByRole('heading',{name:'监控组设置'}).waitFor();
  await page.locator('.group-dialog').evaluate(el=>el.scrollTop=el.scrollHeight);await shot('settings-footer');
  await page.getByRole('button',{name:'关闭监控组设置',exact:true}).click();
  const add=page.getByRole('button',{name:'添加监控',exact:true});await add.scrollIntoViewIfNeeded();await page.waitForTimeout(200);
  const hit=await add.evaluate(el=>{const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return {button:r.toJSON(),hit:hit?.outerHTML,owned:hit===el||el.contains(hit)};});
  assert(hit.owned,JSON.stringify(hit));
  const canvases=await page.locator('.ov-chart canvas,.spark canvas').evaluateAll(canvases=>canvases.map(canvas=>{const host=canvas.closest('.ov-chart,.spark'),rect=el=>el.getBoundingClientRect().toJSON();return {canvas:rect(canvas),host:rect(host),parent:rect(canvas.parentElement)};}));
  assert(canvases.length>0);assert(canvases.every(c=>within(c.canvas,c.host)&&within(c.canvas,c.parent)),JSON.stringify(canvases));
  const overflow=await page.locator('.overview').evaluate(el=>({scroll:el.scrollWidth,client:el.clientWidth,documentScroll:document.documentElement.scrollWidth,window:innerWidth}));
  assert(overflow.scroll<=overflow.client+1&&overflow.documentScroll<=overflow.window+1,JSON.stringify(overflow));
  await shot('add-monitor-hit-test');await add.click();await page.getByLabel('监控组名称',{exact:true}).waitFor();await shot('new-monitor');
  await page.getByRole('button',{name:'取消',exact:true}).click();
  result.checks.push({width,height,cssZoom:zoom,nativeZoom:false,chartGeometry,tooltipHover:true,hit,canvases,overflow,ordinaryClickOpenedEditor:true});
  await context.close();
 }
`+original.slice(original.indexOf(end));
const generated=path.join(cache,'canvas-geometry.generated.mjs');fs.writeFileSync(generated,source);
const sha=s=>createHash('sha256').update(s).digest('hex');
const out=process.env.STELLA_GROUP_EVIDENCE;assert(out&&path.isAbsolute(out));fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(out,'adapter-provenance.json'),JSON.stringify({fixture,fixture_sha256:sha(original),generated,generated_sha256:sha(source),adapter_sha256:sha(fs.readFileSync(fileURLToPath(import.meta.url)))},null,2));
const run=spawnSync(process.execPath,[generated],{stdio:'inherit',env:process.env});
if(run.error)throw run.error;process.exit(run.status??1);
