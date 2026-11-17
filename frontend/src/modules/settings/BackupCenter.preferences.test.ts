import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),isAdmin:ref(true),refreshAccess:vi.fn(async()=>false)};});
import BackupCenter from './BackupCenter.vue';
import {auth} from '../home/auth';
import {homeSettings} from '../home/settings';
import {appearance,setAppearance} from '../../stores/appearance';
import {clientPreferenceSync,startClientPreferenceSync} from './clientPreferenceSync';
import {defaultClientPreferences,type ClientPreferences} from './clientPreferenceContract';
import type {BackupSnapshot,BackupJob} from '../../api/backups';
let app:App|undefined,stop:(()=>void)|undefined,remote:ClientPreferences,state:BackupSnapshot;
let calls:{method:string;path:string;body?:any}[], holdPrefs:Promise<Response>|null=null;
let jobState:BackupJob['state']='succeeded';
const settle=async()=>{for(let i=0;i<60;i++)await Promise.resolve();await nextTick();};
const response=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
const record={id:'settings-zip',filename:'stella-settings.zip',scope:'settings' as const,created_at:'2026-10-18T01:00:00Z',bytes:1000,sha256:'a'.repeat(64),verified:true};
beforeEach(()=>{
  vi.useFakeTimers();localStorage.clear();Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});Object.assign(homeSettings,defaultClientPreferences().home);setAppearance('A');remote=defaultClientPreferences();calls=[];holdPrefs=null;jobState='succeeded';
  state={config:{revision:0,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0},records:[record],job:null,storage:{node:'fixture',available:true,free_bytes:10000,error:null},next_run:null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}};
  vi.stubGlobal('fetch',vi.fn(async(path:string,options:RequestInit={})=>{
    const method=options.method||'GET',body=options.body?JSON.parse(String(options.body)):undefined;calls.push({method,path,body});
    if(path.endsWith('/client-preferences')){
      if(method==='PUT'){if(holdPrefs)return holdPrefs;const {expected_revision,...content}=body;remote={...content,revision:expected_revision+1};}return response(remote);
    }
    if(method==='POST'){
      const job:BackupJob={id:'job-new',kind:path.endsWith('/restore')?'restore':'backup',scope:'settings',state:jobState,stage:'done',record_id:record.id,error:null};
      if(job.kind==='restore' && jobState==='succeeded'){remote={...defaultClientPreferences(),revision:remote.revision+1,appearance:'B'};remote.home.siteTitle='ZIP 中的主页';remote.home.bgCrop={cx:.4,cy:.3,w:.8,h:.9};remote.ui.sidebarFold=true;}
      state.job=job;return response(job,202);
    }
    return response(state);
  }));
});
afterEach(()=>{app?.unmount();stop?.();app=undefined;stop=undefined;document.body.innerHTML='';vi.unstubAllGlobals();vi.useRealTimers();localStorage.clear();});
async function mount(){stop=startClientPreferenceSync();await clientPreferenceSync.ensureConfirmed();const root=document.createElement('div');document.body.append(root);app=createApp(BackupCenter);app.mount(root);await settle();return root;}
function button(root:ParentNode,label:string){const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===label);expect(b,label).toBeDefined();return b!;}
it('waits for preference PUT and GET confirmation before a manual backup, including edits outside the backup page',async()=>{
  const root=await mount();homeSettings.siteTitle='最新主页';setAppearance('B');button(root,'备份所有设置').click();button(root,'备份所有设置').click();await settle();
  expect(remote.home.siteTitle).toBe('最新主页');expect(remote.appearance).toBe('B');const post=calls.findIndex(c=>c.path==='/operations/backups'&&c.method==='POST');expect(post).toBeGreaterThan(0);expect(calls[post-1]).toMatchObject({path:'/operations/backups/client-preferences',method:'GET'});expect(calls.filter(c=>c.path==='/operations/backups'&&c.method==='POST')).toHaveLength(1);
});
it('successful settings restore GETs and applies live home/appearance without reloading or touching a note draft',async()=>{
  const root=await mount();localStorage.setItem('stella_note_draft_fixture','unsaved private draft');const body=document.createElement('textarea');body.value='未保存的编辑';root.append(body);
  button(root,'恢复设置').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!;const input=dialog.querySelector<HTMLInputElement>('input')!;input.value=record.filename;input.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();button(dialog,'确认恢复设置').click();await settle();
  expect(homeSettings.siteTitle).toBe('ZIP 中的主页');expect(homeSettings.bgCrop.cx).toBe(.4);expect(appearance.value).toBe('B');expect(document.documentElement.dataset.appearance).toBe('B');expect(localStorage.getItem('stella_sidebar_fold')).toBe('1');expect(localStorage.getItem('stella_note_draft_fixture')).toBe('unsaved private draft');expect(body.value).toBe('未保存的编辑');expect(root.querySelector('[data-client-preferences]')?.textContent).toContain('部分布局将在刷新后生效，请先保存当前工作。');expect(root.querySelector('[data-client-preferences] button')?.textContent).toBe('知道了');
  const puts=calls.filter(c=>c.method==='PUT').length;await vi.advanceTimersByTimeAsync(600);await settle();expect(calls.filter(c=>c.method==='PUT')).toHaveLength(puts);expect(state.config.enabled).toBe(false);
});
it('reattaches an active restore after same-owner reauthentication and applies only its fresh terminal readback',async()=>{
  const root=await mount();jobState='running';button(root,'恢复设置').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!,input=dialog.querySelector<HTMLInputElement>('input')!;input.value=record.filename;input.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();button(dialog,'确认恢复设置').click();await settle();
  auth.sessionGeneration++;await settle();expect(clientPreferenceSync.state.phase).toBe('restoring');
  remote={...defaultClientPreferences(),revision:remote.revision+1,appearance:'B'};remote.home.siteTitle='新会话确认的恢复';state.job!.state='succeeded';await vi.advanceTimersByTimeAsync(2000);await settle();expect(homeSettings.siteTitle).toBe('新会话确认的恢复');expect(appearance.value).toBe('B');expect(clientPreferenceSync.state.phase).toBe('synced');
});
it('does not submit or replay a backup when preference confirmation fails; sync retry only saves preferences',async()=>{
  const root=await mount();holdPrefs=Promise.resolve(response({detail:'offline'},503));homeSettings.siteTitle='保留输入';button(root,'备份所有设置').click();await settle();
  expect(root.textContent).toContain('未创建备份');expect(root.querySelector('[data-client-preferences][role="alert"]')).not.toBeNull();expect(calls.some(c=>c.method==='POST')).toBe(false);expect(homeSettings.siteTitle).toBe('保留输入');
  holdPrefs=null;button(root,'重试偏好同步').click();await settle();await clientPreferenceSync.ensureConfirmed();expect(calls.some(c=>c.method==='POST')).toBe(false);
  button(root,'备份所有设置').click();await settle();expect(calls.filter(c=>c.path==='/operations/backups'&&c.method==='POST')).toHaveLength(1);
});
it('leaving the backup view while its shared preference confirmation is pending prevents a late backup POST',async()=>{
  const root=await mount();let finish!:(r:Response)=>void;holdPrefs=new Promise(r=>{finish=r;});homeSettings.siteTitle='延迟确认';button(root,'备份所有设置').click();await settle();expect(calls.some(c=>c.method==='POST')).toBe(false);
  app!.unmount();app=undefined;const body=calls.filter(c=>c.method==='PUT').at(-1)!.body;const {expected_revision,...content}=body;remote={...content,revision:expected_revision+1};holdPrefs=null;finish(response(remote));await settle();await clientPreferenceSync.ensureConfirmed();expect(calls.some(c=>c.method==='POST')).toBe(false);
});
it.each([['',true,true],['/custom-missing',true,false],['',false,false]] as const)('only safe empty default permits manual first backup: %s %s',async(directory,canInitialize,enabled)=>{
  state.config.directory=directory;Object.assign(state.storage,{available:false,can_initialize_default:canInitialize,error:null});const root=await mount();
  expect(calls.some(c=>c.method==='POST')).toBe(false);expect(button(root,'备份所有设置').disabled).toBe(!enabled);expect(button(root,'备份全部数据').disabled).toBe(!enabled);
  for(const label of ['下载 ZIP','校验 ZIP','删除 ZIP','恢复设置'])expect(button(root,label).disabled).toBe(true);
  if(enabled){expect(root.textContent).toContain('默认目录将在首次手动备份或启用计划后的执行时创建');expect(root.querySelector('.storage-note.error')).toBeNull();button(root,'备份所有设置').click();await settle();expect(calls.filter(c=>c.path==='/operations/backups'&&c.method==='POST')).toHaveLength(1);}
});
