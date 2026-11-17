import {test,expect} from '@playwright/test';
import {mkdirSync,writeFileSync} from 'node:fs';
const out=process.env.WEBSITE_UI_EVIDENCE!;
test('real HTTP audit of every button and preservation payload',async({page,request})=>{
 await request.post('/__website-ui/reset',{data:{}});
 await page.goto('/tests/website-settings.html?module=owned');
 await expect(page.locator('.inline-editor')).toBeVisible();
 const before=await (await request.get('/__website-ui/state')).json();
 const buttons=await page.locator('.inline-editor button').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect(),c=getComputedStyle(e);return {text:e.textContent,label:e.getAttribute('aria-label'),x:r.x,y:r.y,width:r.width,height:r.height,font:c.fontSize,display:c.display,padding:c.padding};}));
 mkdirSync(out,{recursive:true});const label=process.env.WEBSITE_UI_AUDIT_LABEL||'current';writeFileSync(out+'/'+label+'-http-buttons.json',JSON.stringify({buttons,before},null,2));
 await page.screenshot({path:out+'/'+label+'-http-desktop.png',fullPage:true});
 await page.getByLabel('显示名称',{exact:true}).fill('保留凭据审计');await page.getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.inline-editor')).toHaveCount(0);
 const after=await (await request.get('/__website-ui/state')).json();expect(after.modules[0]).toEqual({...before.modules[0],name:'保留凭据审计'});expect(after.tokenUnchanged).toBe(true);writeFileSync(out+'/'+label+'-http-save.json',JSON.stringify(after,null,2));
});
