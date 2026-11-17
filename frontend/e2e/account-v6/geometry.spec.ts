import {test,expect,type Page} from '@playwright/test';
import {writeFileSync} from 'node:fs';
import {fixture,shot,aligned} from './geometry.fixture';

// Exact read-only notes API slice: no broad catch-all or production proxy.
async function notesFixture(page:Page){
 const f=await fixture(page),ws='11111111-1111-4111-8111-111111111111',id='22222222-2222-4222-8222-222222222222';
 const workspace={id:ws,name:'笔记本',user_id:'fixture-owner'};
 const doc={id,title:'全幅笔记正对照',workspace_id:ws,parent_id:null,file_path:'/notes/control.md',content:'# 全幅笔记正对照\n\n'+('可读的笔记正文，不应因设置页留边改变宽度。\n\n'.repeat(60)),content_hash:'fixture-not-used-for-write',status:'published',is_folder:false,is_pinned:false,is_favorite:false,has_draft:false,draft_updated_at:null,draft_device:null,created_at:'2026-10-21T01:00:00Z',updated_at:'2026-10-21T01:00:00Z'};
 const blocked:string[]=[];
 const reads:Record<string,unknown>={
  [`/workspaces/${ws}`]:workspace,'/workspaces/?limit=100':[workspace],'/workspaces/?user_id=fixture-owner&limit=100':[workspace],
  [`/documents/?workspace_id=${ws}&skip=0&limit=500`]:[{...doc,content:undefined}],[`/documents/${id}`]:doc,
  [`/documents/trash?workspace_id=${ws}`]:[],[`/documents/recent?workspace_id=${ws}`]:[],
  '/tags/?limit=200':[],'/doc-tags/':[],[`/doc-tags/?doc_id=${id}`]:[],[`/attachments/?doc_id=${id}`]:[],[`/attachments/?workspace_id=${ws}`]:[],
  [`/documents/${id}/backlinks`]:[],[`/web-projects/workspace/${ws}`]:[],[`/web-projects/workspace/${ws}/identities`]:[],[`/detached-sources?workspace_id=${ws}`]:[],
  [`/notes-tools/templates/${ws}`]:{root_id:null,items:[],recent_ids:[]},
  '/notes-preferences':{revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[]}
 };
 await page.route('**/*',route=>{const r=route.request(),u=new URL(r.url()),key=u.pathname+u.search;
  if(r.method()==='GET'&&['https://ipinfo.io/json','https://api.ip.sb/geoip'].includes(u.href)){blocked.push(u.href);return route.abort();}
  if(u.origin==='http://127.0.0.1:15487'&&key===`/notes-tools/templates/${ws}/initialize`&&r.method()==='POST'&&!r.postData())return route.fulfill({json:{root_id:null,items:[],recent_ids:[]}});
  if(u.origin==='http://127.0.0.1:15487'&&r.method()==='GET'){
   if(key===`/notes?doc=${id}`&&r.isNavigationRequest())return route.continue();
   if(Object.hasOwn(reads,key))return route.fulfill({json:reads[key]});
  }
  return route.fallback();
 });
 await page.routeWebSocket('**/*',socket=>{const u=new URL(socket.url());if(u.origin!=='ws://127.0.0.1:15487'||!['/ws/notifications',`/ws/${id}?device=Chrome`,`/ws/list/${ws}`].includes(u.pathname+u.search))f.unknown.push('WS '+socket.url());socket.close();});
 await page.addInitScript(({ws})=>{localStorage.setItem('stella_bootstrap',JSON.stringify({userId:'fixture-owner',workspaceId:ws}));localStorage.setItem('stella_list_fold','1');},{ws});
 return {...f,id,blocked};
}
const out=process.env.STELLA_ACCOUNT_OUTPUT||'/root/.hermes/cache/scratch/account-polish-v6/browser';
async function geometry(page:Page){return page.locator('.profile-data-row').evaluateAll(rows=>rows.map(row=>{
 const rect=(e:Element)=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height};};
 const value=row.querySelector('.profile-value')!,text=row.querySelector('.profile-value-text'),actions=row.querySelector('.profile-actions')!,label=row.querySelector('.profile-label')!;
 let glyph=null;if(text){const range=document.createRange();range.selectNodeContents(text);glyph=rect(range as unknown as Element);}
 return {row:rect(row),value:rect(value),actions:rect(actions),label:rect(label),glyph,status:row.querySelector('.email-state-trigger')?rect(row.querySelector('.email-state-trigger')!):null,buttons:[...actions.querySelectorAll('button')].map(rect),fonts:[label,text].filter(Boolean).map(e=>parseFloat(getComputedStyle(e!).fontSize)),error:!!row.querySelector('.profile-error'),text:text?.textContent,overflow:row.scrollWidth>row.clientWidth+1};
 }));}
async function rail(page:Page,label:string){
 const g=await geometry(page);writeFileSync(`${out}/${label}-rail.json`,JSON.stringify(g,null,2));
 for(const r of g){expect(Math.abs(r.actions.right-r.row.right)).toBeLessThanOrEqual(1);expect(Math.abs(r.buttons.at(-1)!.right-g[0]!.buttons.at(-1)!.right)).toBeLessThanOrEqual(1);expect(r.overflow).toBe(false);}
 const pane=await page.locator('.profile-settings').evaluate(e=>{const r=e.getBoundingClientRect(),p=e.parentElement!.getBoundingClientRect();return {w:r.width,left:r.left-p.left,right:p.right-r.right};});expect(pane.w).toBeLessThanOrEqual(760);expect(Math.abs(pane.left-pane.right)).toBeLessThanOrEqual(1);
}
async function compact(page:Page,width:number,label:string,long=false){
 await page.mouse.move(width-1,1);await page.waitForTimeout(200);const g=await geometry(page);await shot(page,label);writeFileSync(`${out}/${label}.json`,JSON.stringify(g,null,2));
 for(const r of g){expect(r.overflow).toBe(false);expect(r.fonts.every(n=>n>=13)).toBe(true);expect(r.row.right).toBeLessThanOrEqual(width);
  expect(Math.abs(r.value.y+r.value.h/2-r.actions.y-r.actions.h/2)).toBeLessThanOrEqual(1);
  if(!long&&!r.error)expect(r.row.h).toBeLessThanOrEqual(r.label.x===r.value.x?104:80);
  // Supersedes the parent's short-value gap oracle: Outline fixes actions at the row end.
  expect(Math.abs(r.actions.right-r.row.right)).toBeLessThanOrEqual(1);
  expect(Math.abs(r.actions.right-g[0]!.actions.right)).toBeLessThanOrEqual(1);
  expect(r.glyph!.right).toBeLessThanOrEqual(r.status?.x??r.actions.x);
  expect(Math.abs(r.label.x-g[0]!.label.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(r.value.x-g[0]!.value.x)).toBeLessThanOrEqual(1);
  if(width<=768)expect(r.buttons.every(b=>b.h>=44&&b.w>=44)).toBe(true);
 }
 const email=g[2]!;if(!long)expect(email.status!.x-email.glyph!.right).toBeLessThanOrEqual(16);
 if(width>=1200&&!long)for(const r of g){expect(Math.abs(r.label.y+r.label.h/2-r.value.y-r.value.h/2)).toBeLessThan(1);}
 return g;
}
test('Outline actions keep a common row-end rail independent of short values',async({page})=>{
 const f=await fixture(page);await page.setViewportSize({width:1365,height:920});await page.goto('/settings?section=profile');await expect(page.locator('.email-state-trigger')).toBeVisible();
 const g=await geometry(page);await shot(page,'outline-red-or-green');writeFileSync(`${out}/outline-rail.json`,JSON.stringify(g,null,2));
 for(const r of g){expect(Math.abs(r.actions.right-g[0]!.actions.right)).toBeLessThanOrEqual(1);expect(Math.abs(r.actions.right-r.row.right)).toBeLessThanOrEqual(1);}
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const width of [1200,1365,1920,1070,1090,1290,1310,390,320])test(`default density and state transitions ${width}`,async({page})=>{
 const f=await fixture(page);await page.setViewportSize({width,height:920});await page.goto('/settings?section=profile');await expect(page.locator('.email-state-trigger')).toHaveAttribute('data-state','unavailable');
 await compact(page,width,`density-${width}-default`);
 await page.getByRole('button',{name:'编辑昵称',exact:true}).click();await page.locator('#profile-name').fill('保留的草稿');await rail(page,`density-${width}-single`);await shot(page,`density-${width}-single`);
 await page.getByRole('button',{name:'编辑用户名',exact:true}).click();await page.getByRole('button',{name:'编辑邮箱',exact:true}).click();await aligned(page,true);await rail(page,`density-${width}-parallel`);await shot(page,`density-${width}-parallel`);
 f.failProfile(true);await page.getByRole('button',{name:'保存昵称',exact:true}).click();await expect(page.locator('#profile-name-error')).toContainText('草稿已保留');await page.locator('#profile-name').focus();await expect(page.locator('#profile-name')).toBeFocused();await rail(page,`density-${width}-error-focus`);await shot(page,`density-${width}-error-focus`);
 for(const row of await page.locator('.profile-data-row').all())await row.getByRole('button',{name:'取消',exact:true}).click();await compact(page,width,`density-${width}-cancelled`);
 await page.getByRole('button',{name:'编辑昵称',exact:true}).click();await expect(page.locator('#profile-name')).toHaveValue('保留的草稿');await page.locator('.profile-data-row').first().getByRole('button',{name:'取消',exact:true}).click();
 await page.locator('.email-state-trigger').hover();await expect(page.getByRole('tooltip')).toHaveText('邮件服务不可用');await page.locator('.email-state-trigger').focus();await expect(page.getByRole('tooltip')).toHaveText('邮件服务不可用');await page.screenshot({path:`${out}/density-${width}-hover-focus.png`});
 await page.locator('.email-state-trigger').click();await expect(page.getByRole('dialog',{name:'邮件服务不可用'})).toBeFocused();await page.keyboard.press('Escape');await expect(page.locator('.email-state-trigger')).toBeFocused();expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const width of [1200,1365,1920,320,390])test(`full long values remain readable ${width}`,async({page})=>{
 const f=await fixture(page,true);await page.setViewportSize({width,height:920});await page.goto('/settings?section=profile');await expect(page.locator('.email-state-trigger')).toHaveAttribute('data-state','unavailable');const g=await compact(page,width,`long-${width}`,true);expect(g[0]!.text).toHaveLength('很长且必须完整可读的昵称'.repeat(5).length);expect(g[2]!.text).toContain('@long-subdomain.example.test');
 for(const row of await page.locator('.profile-data-row').all())await row.getByRole('button',{name:/编辑/}).click();await aligned(page,true);await rail(page,`long-${width}-parallel`);await shot(page,`long-${width}-parallel`);expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const width of [320,390])test(`settings glyphs cannot overlap original navigation handle ${width}`,async({page})=>{
 const f=await fixture(page);await page.setViewportSize({width,height:740});await page.goto('/settings?section=profile');await expect(page.locator('.profile-value-text').first()).toBeVisible();
 for(const section of ['profile','authentication']){
  if(section==='authentication')await page.goto('/settings?section=authentication');
  const targets=section==='profile'?page.locator('.profile-value-text'):page.locator('.session-times dt');await expect(targets.first()).toBeVisible();
  for(let i=0;i<await targets.count();i++){
   await targets.nth(i).evaluate(el=>{const pane=document.querySelector('main.content')!;pane.scrollTop+=el.getBoundingClientRect().top-innerHeight/2;});
   const geometry=await targets.nth(i).evaluate(el=>{const h=document.querySelector('.notes-handle')!.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(el);const glyphs=[...range.getClientRects()].map(r=>({x:r.x,right:r.right,y:r.y,bottom:r.bottom}));return {handle:{x:h.x,right:h.right+8,y:h.y,bottom:h.bottom},glyphs};});
   writeFileSync(`${out}/handle-${width}-${section}-${i}.json`,JSON.stringify(geometry,null,2));
   await shot(page,`handle-${width}-${section}-${i}`);
   for(const r of geometry.glyphs){expect(r.x).toBeGreaterThanOrEqual(geometry.handle.right);expect(r.right<=geometry.handle.x||r.x>=geometry.handle.right||r.bottom<=geometry.handle.y||r.y>=geometry.handle.bottom).toBe(true);}
  }
 }
 // Real ordinary pointer clicks, Drawer inert isolation, focus return and Escape.
 await page.locator('.notes-handle').click();await expect(page.locator('.mobile-mask')).toBeVisible();await expect(page.locator('main.content')).toHaveAttribute('inert','');await page.keyboard.press('Escape');await expect(page.locator('.mobile-mask')).toHaveCount(0);await expect(page.locator('.notes-handle')).toBeFocused();expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
for(const width of [320,1365])test(`notes full-width positive control ${width}`,async({page})=>{
 const f=await notesFixture(page);await page.setViewportSize({width,height:920});await page.goto(`/notes?doc=${f.id}`);await page.waitForTimeout(300);writeFileSync(`${out}/notes-${width}-requests.json`,JSON.stringify({requests:f.requests,unknown:f.unknown,errors:f.errors},null,2));await expect(page.locator('.preview h1')).toHaveText('全幅笔记正对照');
 const g=await page.locator('main.content').evaluate(el=>{const css=getComputedStyle(el),r=el.getBoundingClientRect(),notes=el.querySelector('.notes-page')!.getBoundingClientRect();return {x:r.x,w:r.width,paddingLeft:css.paddingLeft,paddingRight:css.paddingRight,notesX:notes.x,notesWidth:notes.width};});
 expect(g.paddingLeft).toBe(width<=768?'12px':'32px');expect(g.paddingRight).toBe(g.paddingLeft);expect(g.notesWidth).toBeGreaterThan(width<=768?290:900);writeFileSync(`${out}/notes-${width}.json`,JSON.stringify({geometry:g,unknown:f.unknown,errors:f.errors,blocked:f.blocked},null,2));await shot(page,`notes-${width}`);
 if(width<=768){await page.locator('.notes-handle').click();await expect(page.locator('.mobile-mask')).toBeVisible();await page.keyboard.press('Escape');await expect(page.locator('.mobile-mask')).toHaveCount(0);await expect(page.locator('.notes-handle')).toBeFocused();}
 expect(f.unknown).toEqual([]);expect(f.errors).toEqual([]);
});
