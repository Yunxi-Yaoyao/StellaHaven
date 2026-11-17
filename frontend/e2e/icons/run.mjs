// Isolated production-built fixture. Never boots App, auth, API or a proxy.
import { build, preview } from 'vite';
import vue from '@vitejs/plugin-vue';
import { chromium, expect } from '@playwright/test';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const root = process.cwd();
const scratch = process.env.TMPDIR;
if (!scratch || !scratch.startsWith('/root/.hermes/cache/scratch/')) throw new Error('Use an isolated scratch TMPDIR');
const evidence = process.env.ICONS_EVIDENCE || '/opt/hermes-workstation/docs/Stella-API/remediation';
await mkdir(evidence, { recursive:true });
const outDir = path.join(scratch, 'icons-fixture-dist');
const sources = ['src/shell/Icon.vue','src/modules/settings/IconPicker.vue','src/icons/navigation-icons.json','src/icons/navigationIcons.ts','src/style.css','e2e/icons/main.ts','e2e/icons/fixture.css','e2e/icons/index.html'];
const hashes = async () => Object.fromEntries(await Promise.all(sources.map(async file => [file,createHash('sha256').update(await readFile(path.join(root,file))).digest('hex')])));
const before = await hashes();
await build({ configFile:false, root, cacheDir:path.join(scratch,'vite-icons'), plugins:[vue()], build:{outDir,emptyOutDir:true,rollupOptions:{input:path.join(root,'e2e/icons/index.html')}} });
const server = await preview({ configFile:false, root, build:{outDir}, preview:{host:'127.0.0.1',port:0,proxy:{}} });
const base = server.resolvedUrls.local[0];
const browser = await chromium.launch({headless:true});
const errors = [], requests = [], measurements = [], screenshots = [];
async function screenshot(page, name, fullPage=false) {
  const file = path.join(evidence,`icons-${name}.png`); await page.screenshot({path:file,fullPage}); screenshots.push(file);
}
try {
  for (const [label,width,height] of [['desktop',1100,980],['mobile',390,844],['small',320,760],['landscape',740,390],['zoom200-equivalent',550,490]]) {
    const context = await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
    await context.route('**/*', route => {
      const url=route.request().url();
      if (!url.startsWith(base)) { requests.push(url); return route.abort(); }
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if(message.type()==='error') errors.push(message.text()); });
    await page.goto(base+'e2e/icons/index.html'); await page.evaluate(() => document.fonts.ready);
    const trigger = page.getByRole('button', {name:/选择图标/}); await trigger.click();
    await expect(page.getByRole('searchbox')).toBeFocused();
    await expect(page.getByRole('radio')).toHaveCount(122);
    const geometry = await page.evaluate(() => {
      const panel=document.querySelector('.picker-panel'), grid=document.querySelector('.icon-grid');
      const buttons=[...grid.querySelectorAll('button')];
      return {viewport:innerWidth,document:document.documentElement.scrollWidth,panelWidth:panel.clientWidth,gridWidth:grid.clientWidth,gridScroll:grid.scrollWidth,columns:buttons.filter(b=>b.offsetTop===buttons[0].offsetTop).length,minTouch:Math.min(...[...document.querySelectorAll('.categories button')].map(b=>b.getBoundingClientRect().height))};
    });
    expect(geometry.document).toBeLessThanOrEqual(width);
    expect(geometry.gridScroll).toBeLessThanOrEqual(geometry.gridWidth);
    if(width<=600) expect(geometry.minTouch).toBeGreaterThanOrEqual(44);
    measurements.push({label,...geometry});
    const radios=page.getByRole('radio'); await radios.first().focus(); await page.keyboard.press('ArrowDown');
    await expect(radios.nth(geometry.columns)).toBeFocused();
    await page.keyboard.press('End'); await expect(radios.last()).toBeFocused();
    await page.keyboard.press('Home'); await expect(radios.first()).toBeFocused();
    await expect(page.locator('output')).toHaveAttribute('data-selected','notebook-pen');
    await page.getByRole('button',{name:'媒体创作',exact:true}).click();
    await screenshot(page, label+'-media');
    await page.getByRole('button',{name:'全部',exact:true}).click();
    for(const query of ['数据库',' DATABASE ','postgres']) {
      await page.getByRole('searchbox').fill(query); await expect(radios).toHaveCount(1); await expect(radios).toHaveAccessibleName('数据库');
    }
    await screenshot(page,label+'-search');
    await radios.first().focus(); await page.keyboard.press('Enter');
    await expect(trigger).toBeFocused(); await expect(page.locator('output')).toHaveAttribute('data-selected','database');
    await expect(page.getByLabel('网站名称',{exact:true})).toHaveValue('我的知识库');
    await expect(page.getByLabel('地址',{exact:true})).toHaveValue('https://example.test/knowledge');
    await trigger.click(); await page.getByRole('searchbox').fill('不存在的图标-no-result');
    await expect(page.getByText('没有找到图标',{exact:true})).toBeVisible();
    await screenshot(page,label+'-empty');
    await page.keyboard.press('Escape'); await expect(trigger).toBeFocused();
    await trigger.click(); await page.getByRole('button',{name:'清除筛选',exact:true}).click();
    await page.getByRole('searchbox').fill('cloud');
    await page.getByRole('radio',{name:'云端',exact:true}).focus(); await page.keyboard.press('Space');
    await expect(page.locator('output')).toHaveAttribute('data-selected','cloud');
    await screenshot(page,label+'-selected');
    await context.close();
  }
  const context = await browser.newContext({viewport:{width:1200,height:950}});
  const page=await context.newPage();
  await context.route('**/*',route=>route.request().url().startsWith(base)?route.continue():route.abort());
  await page.goto(base+'e2e/icons/index.html?atlas'); await page.evaluate(()=>document.fonts.ready);
  await expect(page.locator('.atlas svg')).toHaveCount(122); await screenshot(page,'catalog-atlas',true);
  await page.goto(base+'e2e/icons/index.html?icon=future-icon-v2');
  await page.getByRole('button',{name:/选择图标/}).click();
  await expect(page.getByText('未知图标：future-icon-v2（保留原值）',{exact:true})).toBeVisible();
  await page.getByRole('searchbox').press('Escape');
  await expect(page.locator('output')).toHaveAttribute('data-selected','future-icon-v2');
  await screenshot(page,'unknown-preserved');
  await context.close();
  expect(requests).toEqual([]); expect(errors).toEqual([]); expect(await hashes()).toEqual(before);
  await writeFile(path.join(evidence,'icons-browser-report.json'),JSON.stringify({fixture:'Production-built real IconPicker/Icon with synthetic parent fields. No App/production API.',commit:execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),status:execFileSync('git',['status','--short'],{cwd:root,encoding:'utf8'}),sources:before,measurements,screenshots,errors,externalRequests:requests},null,2));
  console.log(JSON.stringify({passed:true,measurements,screenshots,errors,externalRequests:requests},null,2));
} finally { await browser.close(); await server.close(); }
