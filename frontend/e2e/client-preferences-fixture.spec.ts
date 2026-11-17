import {test,expect} from '@playwright/test';
import {setup,MAIN,ID} from './experience-independent-harness';

const endpoint='/operations/backups/client-preferences';
test('real App reads the persisted owner DTO without startup upload or animation reset',async({page})=>{
 const h=await setup(page,{storage:{stella_home_bg_quality:'original'}});
 await page.goto('/apps/'+ID);await expect(page.locator('.external-page iframe')).toBeVisible();
 await expect.poll(()=>page.evaluate(async()=>{const p='/src/modules/settings/clientPreferenceSync.ts';return (await import(p)).clientPreferenceSync.state.phase;})).toBe('synced');
 const preferences=h.requests.filter(r=>r.path===endpoint);
 expect(preferences.length).toBeGreaterThan(0);expect(preferences.every(r=>r.method==='GET')).toBe(true);
 expect(await page.evaluate(()=>({live2d:localStorage.getItem('stella_live2d'),particles:localStorage.getItem('stella_home_particles'),quality:localStorage.getItem('stella_home_bg_quality'),owner:localStorage.getItem('stella_client_preferences_owner')}))).toEqual({live2d:'off',particles:'off',quality:'original',owner:'qa-owner'});
 expect(h.unknown).toEqual([]);expect(h.errors).toEqual([]);
});
test('real App explicit quality change uses revision-aware PUT and confirmed GET',async({page})=>{
 const h=await setup(page);const payloads:any[]=[];page.on('request',request=>{if(new URL(request.url()).pathname===endpoint&&request.method()==='PUT')payloads.push(request.postDataJSON());});await page.goto('/apps/'+ID);await expect(page.locator('.external-page iframe')).toBeVisible();
 await page.evaluate(async()=>{const p='/src/modules/settings/clientPreferenceSync.ts';await(await import(p)).clientPreferenceSync.ensureConfirmed();const quality='/src/modules/home/backgroundMedia.ts';(await import(quality)).setBackgroundQuality('compressed2');await(await import(p)).clientPreferenceSync.ensureConfirmed();});
 const writes=h.requests.filter(r=>r.path===endpoint&&r.method==='PUT');expect(writes).toHaveLength(1);
 expect(payloads).toHaveLength(1);expect(Object.keys(payloads[0]).sort()).toEqual(['appearance','expected_revision','home','ui']);expect(payloads[0]).toMatchObject({expected_revision:1,home:{live2d:false,particles:'off'},ui:{backgroundQuality:'compressed2'}});
 const confirmed=await page.evaluate(async()=>{const p='/src/modules/settings/clientPreferenceSync.ts';return {...(await import(p)).clientPreferenceSync.state};});expect(confirmed).toMatchObject({phase:'synced',revision:2});
 expect(h.requests.filter(r=>r.path===endpoint).at(-1).method).toBe('GET');expect(h.unknown).toEqual([]);expect(h.errors).toEqual([]);
});
for(const method of ['GET','POST'])test('negative control: experience denies unmatched '+method+' and its empty-unknown assertion still fails',async({page},info)=>{
 const h=await setup(page);await page.goto('/apps/'+ID);await expect(page.locator('.external-page iframe')).toBeVisible();expect(h.unknown).toEqual([]);
 const target=method==='GET'?endpoint+'/unknown':endpoint;
 const rejected=await page.evaluate(async({target,method})=>{try{await fetch(target,{method});return false;}catch{return true;}},{target,method});expect(rejected).toBe(true);
 expect(h.unknown).toEqual([method+' '+MAIN+target]);
 expect(()=>expect(h.unknown,'all unmatched network is denied; fixture must declare every request').toEqual([])).toThrow();
 await info.attach('denied-unknown.json',{body:JSON.stringify({unknown:h.unknown,rejected}),contentType:'application/json'});expect(h.errors).toEqual([]);
});
