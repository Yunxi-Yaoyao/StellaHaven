import {test,expect,setup,MAIN,ID} from './experience-independent-harness';
for(const fn of ['fetchMe','refreshAccess'])test('review: real App rejects late '+fn+' after logout',async({page,evidence},info)=>{
 const h=evidence.h=await setup(page);await page.goto('/apps/'+ID);await expect(page.locator('.external-page iframe')).toBeVisible();
 let held:any;const endpoint=fn==='fetchMe'?'/auth/me':'/auth/refresh';
 await page.route(MAIN+endpoint,route=>{held=route;});
 await page.route(MAIN+'/auth/logout',route=>route.fulfill({json:{ok:true}}));
 await page.evaluate(async fn=>{const p='/src/modules/home/auth.ts';const mod=await import(p);(window as any).__oldAuth=mod[fn]();},fn);
 await expect.poll(()=>!!held).toBe(true);
 await page.evaluate(async()=>{const p='/src/modules/home/auth.ts';await(await import(p)).logout();});
 const read=()=>page.evaluate(async()=>{const p='/src/modules/home/auth.ts';return JSON.parse(JSON.stringify((await import(p)).auth));});
 const afterLogout=await read();expect(afterLogout.me).toBeNull();
 await held.fulfill({json:h.user});await page.evaluate(()=> (window as any).__oldAuth);
 const afterLate=await read();await info.attach('session-race.json',{body:JSON.stringify({afterLogout,afterLate}),contentType:'application/json'});
 expect(afterLate.me,'old-session response must not resurrect identity in real App').toBeNull();
});
