import {test,expect,setup,frames,rows,expected,ID} from './experience-independent-harness';
import type {Page} from '@playwright/test';
async function firstComplete(page:Page){
 const history=await page.evaluate(()=> (window as any).__experience.navigation);
 const clickable=history.filter((s:any)=>s.rows.length);
 expect.soft(clickable.length,'observed at least one real interactive navigation snapshot').toBeGreaterThan(0);
 const simplified=(s:any)=>s.rows.map(({id,label,href}:any)=>({id,label,href}));
 expect.soft(clickable[0]&&simplified(clickable[0]),'FIRST clickable menu is complete, renamed, hidden-filtered and correctly ordered').toEqual(expected);
 expect.soft(clickable.filter((s:any)=>JSON.stringify(simplified(s))!==JSON.stringify(expected)),'no partial/default/intermediate menu at any observed frame').toEqual([]);
}
for(const first of ['navigation','modules'] as const){
 test(`navigation startup holds auth and both sources; ${first} first`,async({page,evidence},info)=>{
  const h=evidence.h=await setup(page,{held:['auth','navigation','modules']});
  await page.goto('/apps/'+ID,{waitUntil:'domcontentloaded'});
  await expect(page.locator('.sidebar')).toBeVisible();
  await expect.poll(()=>h.gates.auth.requests).toBe(1);await frames(page);
  expect.soft(await rows(page),'authentication unresolved: no clickable default menu').toEqual([]);
  await page.screenshot({path:info.outputPath('01-auth-held.png')});
  h.gates.auth.release();await expect.poll(()=>h.gates.modules.requests).toBe(1);await frames(page);
  expect.soft(await rows(page),'both sources pending: noninteractive placeholder only').toEqual([]);
  expect.soft(await page.locator('.sidebar [role=status]').count(),'visible sidebar loading status').toBeGreaterThan(0);
  h.gates[first].release();await frames(page,5);
  expect.soft(await rows(page),'one source resolved: never publish a partial menu').toEqual([]);
  await page.screenshot({path:info.outputPath('02-one-source.png')});
  h.gates[first==='navigation'?'modules':'navigation'].release();
  await expect.poll(()=>rows(page)).toEqual(expected);await frames(page);await firstComplete(page);
 });
}
for(const failing of ['navigation','modules'] as const){
 test(`navigation ${failing} failure offers sidebar retry`,async({page,evidence})=>{
  const h=evidence.h=await setup(page,{held:[failing]});await page.goto('/apps/'+ID);
  await expect.poll(()=>h.gates[failing].requests).toBe(1);h.gates[failing].release(503);
  // A sidebar error, not an unrelated page error or a Settings-only retry.
  await expect(page.locator('.sidebar [role=alert]')).toContainText(/失败|错误|重试/);
  expect.soft(await rows(page)).toEqual([]);h.gates[failing].status=200;
  await page.locator('.sidebar').getByRole('button',{name:/重试/}).click();
  await expect.poll(()=>rows(page)).toEqual(expected);await firstComplete(page);
 });
}
test('navigation same-session watchdog keeps menu identity and positions',async({page,evidence})=>{
 const h=evidence.h=await setup(page);await page.clock.install();await page.goto('/apps/'+ID);
 await expect.poll(()=>rows(page)).toEqual(expected);await frames(page);
 const before=await page.evaluate(()=>{const nodes=[...document.querySelectorAll('.sidebar nav .nav-item')];(window as any).__navNodes=nodes;return nodes.map(e=>({href:e.getAttribute('href'),y:e.getBoundingClientRect().y}));});
 const calls={nav:h.gates.navigation.requests,modules:h.gates.modules.requests,auth:h.gates.auth.requests};
 await page.clock.fastForward(30001);await expect.poll(()=>h.gates.auth.requests).toBeGreaterThan(calls.auth);await frames(page);
 expect(h.gates.navigation.requests).toBe(calls.nav);expect(h.gates.modules.requests).toBe(calls.modules);
 expect(await rows(page)).toEqual(expected);
 const after=await page.evaluate(()=>({same:[...document.querySelectorAll('.sidebar nav .nav-item')].every((el,i)=>el===(window as any).__navNodes[i]),positions:[...document.querySelectorAll('.sidebar nav .nav-item')].map(e=>({href:e.getAttribute('href'),y:e.getBoundingClientRect().y}))}));
 expect(after.same).toBe(true);expect(after.positions).toEqual(before);
});
for(const path of ['/settings?section=navigation','/drive']){
 test(`navigation concurrent entry single-flight ${path}`,async({page,evidence})=>{
  const h=evidence.h=await setup(page,{held:['navigation','modules']});await page.goto(path,{waitUntil:'domcontentloaded'});
  await expect.poll(()=>h.gates.modules.requests).toBeGreaterThan(0);await frames(page,6);
  // Hold until all startup consumers (App, guard, Settings) have actually mounted.
  if(path.startsWith('/settings'))await expect(page.getByRole('heading',{name:'设置',exact:true})).toBeVisible();
  h.gates.navigation.release();h.gates.modules.release();await expect.poll(()=>rows(page)).toEqual(expected);
  expect.soft(h.gates.navigation.requests,'one request per source for concurrent startup').toBe(1);
  expect.soft(h.gates.modules.requests,'one request per source for concurrent startup').toBe(1);
  await firstComplete(page);
 });
}
