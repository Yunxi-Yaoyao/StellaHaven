// This is run only by the owned PostgreSQL HTTP harness, never against a developer/live origin.
import {afterEach,expect,it,vi} from 'vitest';
import {createApp,h,nextTick,ref,type App} from 'vue';
import JSZip from 'jszip';
import {createHash} from 'node:crypto';
import {writeFile} from 'node:fs/promises';
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:process.env.STELLA_PREFS_TEST_OWNER},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),isAdmin:ref(true),refreshAccess:vi.fn(async()=>false)};});
import BackupCenter from './BackupCenter.vue';
import {homeSettings} from '../home/settings';
import {setAppearance,appearance} from '../../stores/appearance';
import {defaultClientPreferences} from './clientPreferenceContract';
import {clientPreferenceSync,startClientPreferenceSync} from './clientPreferenceSync';
import {notifyClientPreferenceChange} from './clientPreferenceEvents';
import {getBackups,getClientPreferences} from '../../api/backups';
let app:App|undefined,stop:(()=>void)|undefined;
afterEach(()=>{app?.unmount();stop?.();document.body.innerHTML='';localStorage.clear();vi.unstubAllGlobals();});
async function until(predicate:()=>boolean){const end=Date.now()+20000;while(!predicate()){if(Date.now()>end)throw Error('owned HTTP/Vue state deadline exceeded');await new Promise(r=>setTimeout(r,20));await nextTick();}}
function button(root:ParentNode,label:string){const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===label);expect(b,label).toBeDefined();return b!;}
it.skipIf(!process.env.STELLA_PREFS_TEST_BASE)('real Vue settings → HTTP/PG → POST ZIP → settings restore → live UI readback',async()=>{
  const base=process.env.STELLA_PREFS_TEST_BASE!;expect(base).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  const originalFetch=globalThis.fetch,calls:{method:string;path:string}[]=[];
  vi.stubGlobal('fetch',async(path:string,options:RequestInit={})=>{
    expect(path).toMatch(/^\/(operations\/backups|auth\/me)/);calls.push({method:options.method||'GET',path});
    const headers=new Headers(options.headers);headers.set('Origin',base);headers.set('Cookie',process.env.STELLA_PREFS_TEST_COOKIE!);
    return originalFetch(new URL(path,base),{...options,headers});
  });
  Object.assign(homeSettings,defaultClientPreferences().home);setAppearance('A');
  localStorage.setItem('stella_token','LOCAL-PRIVATE-TOKEN-NEVER-IN-ZIP');localStorage.setItem('stella_note_draft_private','LOCAL-PRIVATE-DRAFT-NEVER-IN-ZIP');
  stop=startClientPreferenceSync();try{await clientPreferenceSync.ensureConfirmed();}catch{throw Error(JSON.stringify({phase:clientPreferenceSync.state.phase,message:clientPreferenceSync.state.message,requests:calls}));}
  const noteDraft=ref('initial draft');
  const root=document.createElement('div');document.body.append(root);app=createApp({setup:()=>()=>h('main',[h('h1',{'data-home-title':true},homeSettings.siteTitle),h('textarea',{value:noteDraft.value,onInput:(event:Event)=>{noteDraft.value=(event.target as HTMLTextAreaElement).value;}}),h(BackupCenter)])});app.mount(root);await until(()=>!!root.querySelector('[aria-label="备份目录"]'));
  const editor=root.querySelector('textarea')!;editor.value='mounted unsaved editor draft';editor.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();
  // Ordinary edits must reach PG before any manual backup is requested.
  homeSettings.siteTitle='PG / HTTP 最新主页';homeSettings.bgCrop={cx:.31,cy:.42,w:.73,h:.84};setAppearance('B');localStorage.setItem('stella_sidebar_fold','1');notifyClientPreferenceChange('stella_sidebar_fold');
  await until(()=>clientPreferenceSync.state.phase==='synced' && clientPreferenceSync.state.revision===2);
  const saved=await getClientPreferences();expect(saved.home.siteTitle).toBe('PG / HTTP 最新主页');expect(saved.appearance).toBe('B');expect(saved.ui.sidebarFold).toBe(true);
  expect(calls.some(c=>c.method==='POST' && c.path==='/operations/backups')).toBe(false);
  button(root,'备份所有设置').click();await until(()=>!!root.querySelector('[data-backup-id]') && root.textContent!.includes('备份已完成'));
  const status=await getBackups(),record=status.records[0]!;expect(status.config.enabled).toBe(false);
  const downloaded=await fetch(`/operations/backups/${record.id}/download`),bytes=Buffer.from(await downloaded.arrayBuffer());expect(downloaded.status).toBe(200);
  const zip=await JSZip.loadAsync(bytes),settings=JSON.parse(await zip.file('settings.json')!.async('string'));
  const bundled=JSON.parse(settings.config.find((row:any)=>row.key==='client-preferences:'+process.env.STELLA_PREFS_TEST_OWNER).value);expect(bundled).toEqual(saved);
  const raw=(await Promise.all(Object.values(zip.files).filter(entry=>!entry.dir).map(entry=>entry.async('string')))).join('\n');
  for(const secret of ['LOCAL-PRIVATE-TOKEN-NEVER-IN-ZIP','LOCAL-PRIVATE-DRAFT-NEVER-IN-ZIP','PG-PRIVATE-NOTE-BODY','PG-PRIVATE-WEB-SOURCE','PG-PRIVATE-BROWSER-TOKEN','PG-PRIVATE-ATTACHMENT'])expect(raw.includes(secret)).toBe(false);
  homeSettings.siteTitle='稍后的主页输入';setAppearance('A');localStorage.setItem('stella_sidebar_fold','0');notifyClientPreferenceChange('stella_sidebar_fold');await clientPreferenceSync.ensureConfirmed();
  const changed=await getClientPreferences();expect(changed.revision).toBeGreaterThan(saved.revision);
  button(root,'恢复设置').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!;const input=dialog.querySelector<HTMLInputElement>('input')!;input.value=record.filename;input.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();button(dialog,'确认恢复设置').click();
  await until(()=>clientPreferenceSync.state.phase==='synced' && clientPreferenceSync.state.revision!>changed.revision && homeSettings.siteTitle===saved.home.siteTitle);
  const restored=await getClientPreferences();expect(restored.home).toEqual(saved.home);expect(restored.ui).toEqual(saved.ui);expect(appearance.value).toBe('B');expect(document.documentElement.dataset.appearance).toBe('B');expect(root.querySelector('[data-home-title]')!.textContent).toBe(saved.home.siteTitle);
  expect(localStorage.getItem('stella_note_draft_private')).toBe('LOCAL-PRIVATE-DRAFT-NEVER-IN-ZIP');expect(root.querySelector('textarea')!.value).toBe('mounted unsaved editor draft');expect(root.textContent).toContain('保存当前工作后自行刷新');
  const puts=calls.filter(c=>c.method==='PUT').length;await new Promise(r=>setTimeout(r,600));expect(calls.filter(c=>c.method==='PUT')).toHaveLength(puts);
  const report={kind:'actual owned PG18 + FastAPI HTTP + Vue DOM/store integration',archive_sha256:createHash('sha256').update(bytes).digest('hex'),archive_bytes:bytes.length,record_id:record.id,saved_revision:saved.revision,changed_revision:changed.revision,restored_revision:restored.revision,home:restored.home,appearance:restored.appearance,ui:restored.ui,private_zip_sentinels_absent:true,mounted_draft_preserved:true,no_restore_echo_put:true,requests:calls};
  await writeFile(process.env.STELLA_PREFS_TEST_REPORT!,JSON.stringify(report,null,2));
},30000);
