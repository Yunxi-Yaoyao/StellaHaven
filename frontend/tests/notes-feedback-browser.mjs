// Isolated component/router/browser fixture; NOT resident-preview or backend acceptance.
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {chromium,expect} from '@playwright/test';
const out=process.env.STELLA_NOTES_FEEDBACK_EVIDENCE;
assert(out,'STELLA_NOTES_FEEDBACK_EVIDENCE is required');await mkdir(out,{recursive:true});
const cache=await mkdtemp('/root/.hermes/cache/scratch/notes-feedback-browser-');
const owner='11111111-1111-4111-8111-111111111111',workspace='22222222-2222-4222-8222-222222222222',folder='33333333-3333-4333-8333-333333333333';
const entry=`
import {createApp,h} from 'vue';import {createPinia} from 'pinia';import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
import NotesPage from '/src/modules/notes/NotesPage.vue';import SettingsPage from '/src/modules/settings/SettingsPage.vue';
import {auth} from '/src/modules/home/auth.ts';import {useNotesStore} from '/src/stores/notes.ts';import '/src/style.css';
auth.me={id:'${owner}',username:'fixture',display_name:'Fixture',avatar_url:'',home_bg:'',email:'',email_verified:false,is_admin:false};auth.checked=true;
const pinia=createPinia();const store=useNotesStore(pinia);store.userId='${owner}';store.workspaceId='${workspace}';
for(const name of ['bootstrap','refreshList','refreshRecent','refreshWorkspaces','refreshTags','refreshTrash'])store[name]=async()=>{};
window.WebSocket=class {static OPEN=1;readyState=1;close(){}};
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/notes',component:NotesPage},{path:'/settings',component:SettingsPage}]});
await router.push('/notes');await router.isReady();createApp({render:()=>h(RouterView)}).use(pinia).use(router).mount('#app');
`;
const server=await createServer({configFile:false,envDir:false,root:resolve('.'),appType:'custom',cacheDir:cache,plugins:[vue(),{name:'notes-feedback-fixture',configureServer(s){s.middlewares.use((req,res,next)=>{if(req.url==='/__notes_feedback'){res.setHeader('Content-Type','text/html');res.end('<html><body><div id="app" style="height:100vh"></div><script type="module" src="/__notes_feedback.mjs"></script></body></html>');}else next();});},resolveId(id){if(id==='/__notes_feedback.mjs')return '\0notes-feedback';},load(id){if(id==='\0notes-feedback')return entry;}}],optimizeDeps:{entries:[],include:['vue','pinia','vue-router','d3-force','html2canvas','jspdf','jszip','marked','@codemirror/commands','@codemirror/lang-markdown','@codemirror/language-data','@codemirror/language','@codemirror/search','@codemirror/state','@codemirror/view','@lezer/highlight','dompurify','mermaid']},server:{host:'127.0.0.1',port:0,strictPort:true}});
let browser,page;const errors=[],unexpected=[],results=[];const prefs={revision:0,delete_action:'trash',ask_before_delete:true,font_size:16,line_height:1.8,read_width:800,code_line_numbers:false,code_wrap:true,directory_sort:'updated',hidden_folders:[]};let offline=true;
try{await server.listen();const origin=server.resolvedUrls.local[0].replace(/\/$/,'');browser=await chromium.launch({executablePath:process.env.STELLA_CHROMIUM||'/usr/sbin/google-chrome-stable',headless:true,args:['--no-sandbox']});const context=await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:'block'});
await context.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(url.origin!==origin){unexpected.push(url.origin+url.pathname);return route.abort();}const key=req.method()+' '+url.pathname+url.search;let body,status=200;
if(key===`GET /web-projects/workspace/${workspace}/identities`){body=offline?{detail:'fixture offline'}:[];status=offline?503:200;}
else if(key===`GET /detached-sources?workspace_id=${workspace}`)body=[];
else if(key==='GET /notes-preferences')body=prefs;
else if(key==='PATCH /notes-preferences'){const p=req.postDataJSON();assert.equal(p.expected_revision,prefs.revision);Object.assign(prefs,p,{revision:prefs.revision+1});delete prefs.expected_revision;body={revision:prefs.revision};}
else if(key===`GET /documents/?workspace_id=${workspace}&skip=0&limit=500`)body=[{id:folder,workspace_id:workspace,title:'Fixture hidden folder',parent_id:null,is_folder:true}];
else if(key==='GET /auth/sessions?page=1&page_size=20')body={items:[],page:1,page_size:20,total:0};
else if(key==='GET /auth/avatars')body=[];
else if(key==='GET /config/public-host')body={value:''};
else {if(/^\/(?:auth|config|documents|notes-preferences|notes-tools|web-projects|detached-sources)(?:\/|$)/.test(url.pathname))unexpected.push(key);return route.continue();}return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});});
page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin+'/__notes_feedback',{waitUntil:'domcontentloaded'});
const retry=page.getByRole('button',{name:'重试',exact:true});await expect(retry).toBeVisible({timeout:60000});
const retrySkin=await retry.evaluate(el=>{const s=getComputedStyle(el);return {background:s.backgroundColor,color:s.color,border:s.borderRadius,font:s.fontFamily,padding:s.padding};});assert.notEqual(retrySkin.border,'0px');assert.notEqual(retrySkin.background,'rgb(239, 239, 239)');await retry.focus();assert.equal(await retry.evaluate(el=>getComputedStyle(el).outlineStyle),'solid');
await page.screenshot({path:out+'/desktop-retry.png'});offline=false;await retry.click();await expect(page.getByRole('button',{name:'新建笔记',exact:true})).toBeVisible();
const settings=page.getByRole('button',{name:'笔记设置',exact:true});const settingsSkin=await settings.evaluate(el=>{const s=getComputedStyle(el);return {background:s.backgroundColor,border:s.borderWidth,font:s.fontFamily};});assert.equal(settingsSkin.background,'rgba(0, 0, 0, 0)');assert.equal(settingsSkin.border,'0px');await settings.click();
await expect(page.locator('.notes-settings')).toHaveCount(1);await expect(page.getByText('Fixture hidden folder',{exact:true})).toBeVisible();await expect(page.getByText('在笔记页打开笔记设置 →')).toHaveCount(0);await expect(page.locator('.notes-page')).toHaveCount(0);
await page.getByText('Fixture hidden folder',{exact:true}).click();await expect(page.locator('.notes-settings header')).toContainText('已同步');assert.deepEqual(prefs.hidden_folders,[folder]);await page.screenshot({path:out+'/desktop-settings.png'});
await page.setViewportSize({width:393,height:852});await page.screenshot({path:out+'/mobile-settings.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
results.push({fixture:'isolated mocked API, real components/router/CSS/browser',retrySkin,settingsSkin,hiddenFolders:prefs.hidden_folders,desktop:true,mobile:true});assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);console.log(JSON.stringify({results,errors,unexpected},null,2));
}catch(e){console.log('Fixture failure DOM',await page?.locator('body').innerText());await page?.screenshot({path:out+'/failure.png'});throw e;}finally{await writeFile(out+'/browser.json',JSON.stringify({results,errors,unexpected},null,2));await browser?.close();await server.close();await rm(cache,{recursive:true,force:true});}
