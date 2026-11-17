import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const results=[];
try{
 for(const width of [1280,390]){
  const page=await browser.newPage({viewport:{width,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.ENTRY_FIXTURE_URL);await page.getByText('正常汇报事务 · 上一笔完成请求').waitFor();
  const data=await page.evaluate(()=>({title:document.querySelector('h2')?.textContent,forms:document.querySelectorAll('form,input,select').length,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('article,p,strong,code,a,button')].filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+1||r.left<0;}).map(e=>e.textContent),text:document.body.innerText,links:[...document.querySelectorAll('a')].map(a=>a.getAttribute('href'))}));
  if(data.forms||data.overflow.length||data.scrollWidth>width||errors.length)throw new Error(JSON.stringify({data,errors}));
  await page.screenshot({path:process.env.ENTRY_SCREENSHOTS+`/ui-${width}.png`,fullPage:true});results.push({width,...data,errors});await page.close();
 }
 await writeFile(process.env.ENTRY_SCREENSHOTS+'/UI.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
}finally{await browser.close();}
