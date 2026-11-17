// Independent review R1/R2 reproduced against real auth/security stores.
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import BackupCenter from './BackupCenter.vue';
import {auth,acceptLogin,clearSecurity,isAdmin,security,securityChecked} from '../home/auth';
import {homeSettings} from '../home/settings';
import {setAppearance} from '../../stores/appearance';
import {clientPreferenceSync,startClientPreferenceSync} from './clientPreferenceSync';
import {defaultClientPreferences,type ClientPreferences} from './clientPreferenceContract';
import type {BackupSnapshot} from '../../api/backups';

let app:App|undefined,stop:(()=>void)|undefined,remote:ClientPreferences,state:BackupSnapshot;
let calls:{method:string;path:string;body?:any}[];
const owner={id:'review-alice',username:'review-alice',display_name:'review',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false};
const record={id:'review-settings-zip',filename:'stella-settings-review.zip',scope:'settings' as const,created_at:'2026-10-18T01:00:00Z',bytes:1000,sha256:'a'.repeat(64),verified:true};
const flush=async()=>{for(let i=0;i<80;i++)await Promise.resolve();await nextTick();};
const response=(x:unknown,status=200)=>new Response(JSON.stringify(x),{status});
function button(root:ParentNode,label:string){const b=[...root.querySelectorAll('button')].find(b=>b.textContent?.trim()===label);expect(b,label).toBeDefined();return b!;}
function writes(){return calls.filter(c=>c.method==='PUT' && c.path.endsWith('/client-preferences'));}
beforeEach(()=>{
  vi.useFakeTimers();localStorage.clear();Object.assign(auth,{me:{...owner},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false,checked:true});
  Object.assign(homeSettings,defaultClientPreferences().home);setAppearance('A');
  Object.assign(security,{enabled:true,configured:true,elevated:true,expires_at:null,setup_required:false});securityChecked.value=true;
  remote={...defaultClientPreferences(),revision:1};calls=[];
  state={config:{revision:0,enabled:false,scope:'settings',directory:'',frequency:'daily',time:'03:00',timezone:'Asia/Shanghai',weekday:0},records:[record],job:null,storage:{node:'offline-review',available:true,free_bytes:10000,error:null},next_run:null,capabilities:{settings_restore:true,full_restore:'maintenance_cli'}};
  vi.stubGlobal('fetch',vi.fn(async(path:string,options:RequestInit={})=>{
    const method=options.method||'GET',body=options.body?JSON.parse(String(options.body)):undefined;calls.push({method,path,body});
    if(path==='/operations/backups/client-preferences'){
      if(method==='PUT'){
        if(body.expected_revision!==remote.revision)return response({detail:{code:'revision_conflict'}},409);
        const {expected_revision,...content}=body;remote={...content,revision:expected_revision+1};
      }
      return response(remote);
    }
    if(path===`/operations/backups/${record.id}/restore` && method==='POST'){
      state.job={id:'review-current-restore',kind:'restore',scope:'settings',state:'running',stage:'restore',record_id:record.id,error:null};return response(state.job,202);
    }
    if(path==='/operations/backups' && method==='GET')return response(state);
    throw Error('unexpected offline path '+method+' '+path);
  }));
});
afterEach(()=>{app?.unmount();app=undefined;stop?.();stop=undefined;clearSecurity();document.body.innerHTML='';localStorage.clear();vi.unstubAllGlobals();vi.useRealTimers();});
async function mountCenter(){const root=document.createElement('div');document.body.append(root);app=createApp(BackupCenter);app.mount(root);await flush();return root;}
async function startRestore(){stop=startClientPreferenceSync();await clientPreferenceSync.ensureConfirmed();const root=await mountCenter();button(root,'恢复设置').click();await nextTick();const dialog=document.querySelector('[role="dialog"]')!,input=dialog.querySelector<HTMLInputElement>('input')!;input.value=record.filename;input.dispatchEvent(new Event('input',{bubbles:true}));await nextTick();button(dialog,'确认恢复设置').click();await flush();expect(clientPreferenceSync.state.phase).toBe('restoring');expect(state.job?.state).toBe('running');return root;}
it('control: an active restore pauses ordinary input and terminal polling applies with no echo',async()=>{
  await startRestore();const before=writes().length;await vi.advanceTimersByTimeAsync(800);expect(writes()).toHaveLength(before);
  remote={...defaultClientPreferences(),revision:2,appearance:'B'};remote.home.siteTitle='restored control';state.job!.state='succeeded';await vi.advanceTimersByTimeAsync(1800);await flush();
  expect(clientPreferenceSync.state.phase).toBe('synced');expect(homeSettings.siteTitle).toBe('restored control');await vi.advanceTimersByTimeAsync(800);expect(writes()).toHaveLength(before);
});
it('R1: returning after the current restore finishes recovers the App-owned pause without page reload',async()=>{
  await startRestore();const before=writes().length;app!.unmount();app=undefined;
  remote={...defaultClientPreferences(),revision:2,appearance:'B'};remote.home.siteTitle='restored after leaving';state.job!.state='succeeded';
  await mountCenter();await vi.advanceTimersByTimeAsync(2000);await flush();
  expect(clientPreferenceSync.state.phase,'the real current operation must resume from its terminal status').toBe('synced');
  expect(homeSettings.siteTitle).toBe('restored after leaving');await expect(clientPreferenceSync.ensureConfirmed()).resolves.toBeUndefined();
  await vi.advanceTimersByTimeAsync(800);expect(writes()).toHaveLength(before);
  expect(calls.filter(c=>c.method==='POST')).toHaveLength(1);
});
it('R2: same-owner login without management elevation does not lift an active restore upload pause',async()=>{
  await startRestore();const before=writes().length;
  auth.requestEpoch++;auth.suspended=true;clearSecurity();await flush();
  acceptLogin({...owner});await flush();expect(isAdmin.value).toBe(true);expect(state.job!.state).toBe('running');
  homeSettings.siteTitle='input while restore still running after relogin';await vi.advanceTimersByTimeAsync(800);await flush();
  expect(writes(),'ordinary login must not resume uploads before restore reconciliation').toHaveLength(before);
  expect(clientPreferenceSync.state.phase).toBe('restoring');
  remote={...defaultClientPreferences(),revision:2,appearance:'B'};remote.home.siteTitle='server restored';state.job!.state='succeeded';
  await vi.advanceTimersByTimeAsync(2000);await flush();
  expect(homeSettings.siteTitle).toBe('input while restore still running after relogin');
  expect(clientPreferenceSync.state.phase).toBe('conflict');expect(writes()).toHaveLength(before);
  await clientPreferenceSync.useServer();expect(homeSettings.siteTitle).toBe('server restored');
  expect(isAdmin.value).toBe(true);expect(calls.filter(c=>c.method==='POST')).toHaveLength(1);
});
it('same owner may leave and reauthenticate then reconcile the admitted terminal restore on return',async()=>{
  await startRestore();const before=writes().length;app!.unmount();app=undefined;
  auth.suspended=true;clearSecurity();await flush();acceptLogin({...owner});await flush();
  expect(clientPreferenceSync.state.phase).toBe('restoring');
  remote={...defaultClientPreferences(),revision:2};remote.home.siteTitle='restored while away';state.job!.state='succeeded';
  await mountCenter();await flush();expect(clientPreferenceSync.state.phase).toBe('synced');expect(homeSettings.siteTitle).toBe('restored while away');
  await vi.advanceTimersByTimeAsync(800);expect(writes()).toHaveLength(before);expect(isAdmin.value).toBe(true);
});
it('does not adopt a historical succeeded job that was never admitted by this App',async()=>{
  state.job={id:'historical-success',kind:'restore',scope:'settings',state:'succeeded',stage:'done',record_id:record.id,error:null};
  stop=startClientPreferenceSync();await clientPreferenceSync.ensureConfirmed();const before=calls.filter(c=>c.path.endsWith('/client-preferences')).length;
  await mountCenter();await vi.advanceTimersByTimeAsync(3000);await flush();
  expect(calls.filter(c=>c.path.endsWith('/client-preferences'))).toHaveLength(before);expect(writes()).toHaveLength(0);
  expect(clientPreferenceSync.state.phase).toBe('synced');expect(calls.filter(c=>c.method==='POST')).toHaveLength(0);
});
