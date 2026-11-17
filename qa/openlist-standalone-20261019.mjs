import {chromium} from '/opt/hermes-workstation/stella-preview-20261018/frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import assert from 'node:assert/strict'
const out='/opt/hermes-workstation/docs/Stella-反馈梳理-20261018/external-runtime'
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome-stable',headless:true,args:['--no-sandbox','--no-proxy-server']})
const context=await browser.newContext({viewport:{width:1280,height:900}})
const result={scope:'standalone isolated OpenList UI only, not Stella iframe',externalRequests:[],pageErrors:[]}
await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin==='http://localhost:25444'||['data:','blob:'].includes(u.protocol))return r.continue();result.externalRequests.push(u.hostname+u.pathname);return r.abort()})
const page=await context.newPage();page.on('pageerror',e=>result.pageErrors.push(e.message))
try{
 await page.goto('http://localhost:25444/isolated-test',{waitUntil:'domcontentloaded'});
 await page.getByPlaceholder('输入您的用户名').waitFor();
 const cred=JSON.parse(fs.readFileSync('/var/lib/stella-external-runtime-20261019/private/openlist.json','utf8'));
 await page.getByPlaceholder('输入您的用户名').fill(cred.username);
 await page.getByPlaceholder('输入您的密码').fill(cred.password);
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.getByText('README-ISOLATED-TEST.txt',{exact:true}).waitFor({timeout:45000});
 result.normal_ui_login=true;
 result.directory_visible=true;
 result.title=await page.title();result.body=(await page.locator('body').innerText()).slice(0,1400);
 await page.screenshot({path:out+'/evidence/openlist-standalone.png',fullPage:true});
 result.screenshot='evidence/openlist-standalone.png';
 assert.equal(result.pageErrors.length,0);
}catch(e){result.error=e.message;result.body=(await page.locator('body').innerText()).slice(0,1600);if(await page.locator('input[type=password]:visible').count()===0)await page.screenshot({path:out+'/evidence/openlist-standalone-failed.png',fullPage:true});process.exitCode=1}finally{fs.writeFileSync(out+'/evidence/openlist-standalone.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close()}
