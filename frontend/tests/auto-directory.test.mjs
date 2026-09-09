import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium } from '@playwright/test';

// Real Vue component, real browser; no store/backend/editor dependencies.
test('auto directory: hierarchy, responsive defaults, scoped persistence and safe rendering', async t => {
  const server = await createServer({ configFile: false, appType: 'custom', plugins: [vue()], server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  server.middlewares.use('/__directory_test', async (req, res, next) => {
    try {
      res.setHeader('Content-Type', 'text/html');
      res.end(await server.transformIndexHtml('/__directory_test', `<meta name="viewport" content="width=device-width,initial-scale=1"><div id="app"></div><script type="module">
        import {createApp,h,reactive,nextTick} from 'vue';
        import AutoDirectory from '/src/modules/notes/AutoDirectory.vue';
        import '/src/style.css';
        const doc=(id,parent_id,title=id)=>Object.freeze({id,parent_id,title,workspace_id:'w',content:'untouched',is_folder:false});
        window.initialDocs=Object.freeze([doc('root',null),doc('a','root','Alpha'),doc('b','root','Beta'),doc('c','a','Grandchild'),doc('d','c','Deep'),doc('orphan','missing')]);
        window.state=reactive({docs:window.initialDocs,docId:'root',workspaceId:'w',userId:'u',hasBody:true});
        window.events=[]; window.tick=nextTick;
        createApp({render:()=>h(AutoDirectory,{...window.state,onOpen:id=>window.events.push(id),onCreateChild:()=>window.events.push('create')})}).mount('#app');
      </script>`));
    } catch (e) { next(e); }
  });
  await server.listen(); t.after(() => server.close());
  const browser = await chromium.launch({ executablePath: '/usr/sbin/google-chrome-stable', args: ['--no-sandbox'], headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
  page.setDefaultTimeout(2500);
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  const url=`http://127.0.0.1:${server.httpServer.address().port}/__directory_test`;
  await page.goto(url);
  const root = page.getByRole('button', { name: '目录 · 2 个子页面', exact: true });
  await root.waitFor();
  assert.equal(await root.getAttribute('aria-expanded'), 'true');
  assert.equal(await page.getByRole('button', { name: 'Grandchild', exact: true }).count(), 0);
  await page.getByRole('button', { name: '展开 Alpha 的子页面', exact: true }).click();
  await page.getByRole('button', { name: 'Grandchild', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Deep', exact: true }).count(), 0);
  assert.deepEqual(await page.evaluate(()=>window.events), []);
  await page.getByRole('button', { name: 'Alpha', exact: true }).click();
  await page.getByRole('button', { name: '新建子页面', exact: true }).click();
  assert.deepEqual(await page.evaluate(()=>window.events), ['a','create']);
  await root.click();
  await page.setViewportSize({ width: 390, height: 800 });
  await page.reload(); await root.waitFor();
  assert.equal(await root.getAttribute('aria-expanded'), 'false');
  await page.setViewportSize({ width: 1100, height: 800 });
  await page.waitForTimeout(80);
  assert.equal(await root.getAttribute('aria-expanded'), 'false');
  await page.evaluate(async()=>{window.state.userId='other';await window.tick()});
  assert.equal(await root.getAttribute('aria-expanded'), 'true');
  await page.setViewportSize({ width: 768, height: 800 });
  await page.waitForFunction(()=>document.querySelector('.directory-toggle')?.getAttribute('aria-expanded')==='false');
  await page.evaluate(async()=>{window.state.hasBody=false;await window.tick()});
  assert.equal(await root.getAttribute('aria-expanded'), 'true');
  await root.click();
  await page.evaluate(async()=>{window.state.hasBody=true;window.state.hasBody=false;await window.tick()});
  assert.equal(await root.getAttribute('aria-expanded'), 'false');
  await page.evaluate(async()=>{window.state.workspaceId='different';await window.tick()});
  assert.equal(await page.locator('.auto-directory').count(), 0);
  await page.evaluate(async()=>{window.state.workspaceId='w';window.state.docId='b';await window.tick()});
  assert.equal(await page.locator('.auto-directory').count(), 0);
  await page.evaluate(async()=>{window.state.userId='fresh';window.state.docId='root';window.state.docs=Object.freeze([...window.initialDocs.filter(d=>d.id!=='root'),Object.freeze({...window.initialDocs[0],parent_id:'c'}),window.initialDocs[1],...Array.from({length:90},(_,i)=>Object.freeze({id:'long'+i,parent_id:'root',workspace_id:'w',title:'long'.repeat(200)}))]);await window.tick()});
  await page.setViewportSize({ width: 320, height: 700 });
  await page.getByRole('button', { name: '展开 Alpha 的子页面', exact: true }).click();
  await page.getByRole('button', { name: '展开 Grandchild 的子页面', exact: true }).click();
  assert.equal(await page.getByRole('button',{name:'root',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Alpha',exact:true}).count(),1);
  const layout=await page.evaluate(()=>{const el=document.querySelector('.directory-list');return {width:document.documentElement.scrollWidth,viewport:innerWidth,height:el.clientHeight,scroll:el.scrollHeight,max:innerHeight*.35,title:getComputedStyle(document.querySelector('.directory-title')).textOverflow}});
  assert.ok(layout.width<=layout.viewport); assert.ok(layout.height<=layout.max+1); assert.ok(layout.scroll>layout.height); assert.equal(layout.title,'ellipsis');
  assert.equal(await page.evaluate(()=>window.initialDocs[2].content),'untouched');
  assert.equal(await page.getByRole('button',{name:'目录 · 92 个子页面',exact:true}).count(),1);
  // Positive mobile choice survives remount/reload, even with a nonempty body.
  await page.reload(); await root.waitFor();
  assert.equal(await root.getAttribute('aria-expanded'),'false');
  await root.focus(); await page.keyboard.press('Space');
  assert.equal(await root.getAttribute('aria-expanded'),'true');
  await page.reload(); await root.waitFor();
  assert.equal(await root.getAttribute('aria-expanded'),'true');
  // Same IDs in another workspace must not pick up this workspace's preference.
  await page.evaluate(async()=>{window.state.workspaceId='w2';window.state.docs=window.initialDocs.map(d=>({...d,workspace_id:'w2'}));await window.tick()});
  assert.equal(await root.getAttribute('aria-expanded'),'false');
  await page.evaluate(async()=>{window.state.workspaceId='w';window.state.docs=window.initialDocs;await window.tick()});
  assert.equal(await root.getAttribute('aria-expanded'),'true');
  assert.deepEqual(errors,[]);
  // Restricted storage never throws or loses an explicit choice during resize.
  const restricted=await browser.newPage({viewport:{width:390,height:800}});
  restricted.setDefaultTimeout(2500);
  restricted.on('pageerror',e=>errors.push(e.message));
  await restricted.addInitScript(()=>{Storage.prototype.getItem=()=>{throw new Error('denied')};Storage.prototype.setItem=()=>{throw new Error('denied')}});
  await restricted.goto(url);
  const restrictedRoot=restricted.getByRole('button',{name:'目录 · 2 个子页面',exact:true});
  await restrictedRoot.waitFor();
  assert.equal(await restrictedRoot.getAttribute('aria-expanded'),'false');
  await restrictedRoot.click();
  await restricted.setViewportSize({width:1000,height:800});
  await restricted.setViewportSize({width:390,height:800});
  await restricted.evaluate(async()=>{window.state.docId='a';await window.tick();window.state.docId='root';await window.tick()});
  assert.equal(await restrictedRoot.getAttribute('aria-expanded'),'true');
  assert.deepEqual(errors,[]);
});
