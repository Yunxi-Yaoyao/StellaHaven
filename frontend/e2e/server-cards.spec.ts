import { test, expect, chromium } from '@playwright/test';
let browser:any,page:any;
const base='http://192.168.1.5:5173';
test.beforeAll(async()=>{browser=await chromium.launch({executablePath:'/usr/sbin/google-chrome-stable',args:['--no-sandbox'],headless:true});});
test.afterAll(async()=>browser.close());
test.beforeEach(async()=>{
 page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.route('**/*',async(route:any)=>{
  const p=new URL(route.request().url()).pathname;const ok=(json:any)=>route.fulfill({json});
  if(p==='/auth/me'||p==='/auth/refresh')return ok({id:'u',username:'test',is_admin:true});
  if(p==='/nodes/')return ok([{id:19,name:'Stella',host:'127.0.0.1',platform:'linux',installed:true,status:'offline',components:{}}]);
  if(p==='/nodes/host')return ok({installed:false,node_id:19,os:'Debian',local_install_supported:false});
  if(p==='/monitors/')return ok([]);
  if(p.startsWith('/auth/')||p.startsWith('/config/'))return ok({});
  if(p.includes('/series')||p.includes('/checks')||p==='/component-installs')return ok([]);
  return route.continue();
 });
});
test.afterEach(async()=>page.close());
test('managed host does not get a second installation card in container deployment',async()=>{
 await page.goto(base+'/status');await expect(page.locator('.card .name',{hasText:'Stella'})).toBeVisible();
 await expect(page.locator('.host-card')).toHaveCount(0);
});
test('monitor cards keep ID order across server refresh changes',async()=>{
 let calls=0;
 const a={id:1,name:'A monitor',type:'ping',target:'example.test',status:'up',interval:60,node_id:19};
 const b={...a,id:2,name:'B monitor',status:'down'};
 await page.route('**/monitors/',(route:any)=>{calls++;return route.fulfill({json:calls%2?[b,a]:[a,b]});});
 await page.goto(base+'/status?view=overview');
 await expect(page.locator('.mon-card .mon-name')).toHaveText(['A monitor','B monitor']);
 await expect.poll(()=>calls,{timeout:9000}).toBeGreaterThan(1);
 await expect(page.locator('.mon-card .mon-name')).toHaveText(['A monitor','B monitor']);
});
