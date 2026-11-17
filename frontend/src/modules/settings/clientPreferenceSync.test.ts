import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {nextTick} from 'vue';
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:vi.fn(async()=>false)}));
import {auth} from '../home/auth';
import {homeSettings} from '../home/settings';
import {appearance,setAppearance,hydrateAppearance,cancelAppearanceEdit} from '../../stores/appearance';
import {setBackgroundQuality} from '../home/backgroundMedia';
import {defaultClientPreferences,type ClientPreferences} from './clientPreferenceContract';
const modules=import.meta.glob('./clientPreferenceSync.ts',{eager:true});
const eventModules=import.meta.glob('./clientPreferenceEvents.ts',{eager:true});
let stop:undefined|(()=>void), remote:ClientPreferences, calls:{method:string;path:string;body?:any;signal?:AbortSignal}[];
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();await nextTick();};
beforeEach(()=>{
  vi.useFakeTimers();localStorage.clear();Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});
  Object.assign(homeSettings,defaultClientPreferences().home,{siteTitle:'内存中的真实设置',signature:'实际签名'});hydrateAppearance('B',null);remote=defaultClientPreferences();calls=[];
  vi.stubGlobal('fetch',vi.fn(async(path:string,options:RequestInit={})=>{
    const method=options.method||'GET',body=options.body?JSON.parse(String(options.body)):undefined;calls.push({method,path,body,signal:options.signal as AbortSignal});
    if(path!=='/operations/backups/client-preferences')throw Error('unexpected request');
    if(method==='PUT'){expect(body.expected_revision).toBe(remote.revision);const {expected_revision,...content}=body;remote={...content,revision:expected_revision+1};}
    return new Response(JSON.stringify(remote),{headers:{'Content-Type':'application/json'}});
  }));
});
afterEach(()=>{stop?.();stop=undefined;cancelAppearanceEdit();vi.useRealTimers();vi.unstubAllGlobals();localStorage.clear();});
it('keeps invalid startup preferences as an explicit sync error without aborting App or seeding defaults',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
 localStorage.setItem('stella_drive_bg_mode','invalid');localStorage.setItem('__stella_drive_bg_mode__','image');
 expect(()=>{stop=sync.startClientPreferenceSync();}).not.toThrow();await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('error');expect(sync.clientPreferenceSync.state.message).toContain('无效值');
 await expect(sync.clientPreferenceSync.ensureConfirmed()).rejects.toThrow();
 // Retry may read the legal remote, but strict capture still refuses the invalid input.
 await sync.clientPreferenceSync.retry();await vi.advanceTimersByTimeAsync(60000);
 expect(calls.map(c=>c.method)).toEqual(['GET']);expect(sync.clientPreferenceSync.state.phase).toBe('error');
 expect(localStorage.getItem('stella_drive_bg_mode')).toBe('invalid');expect(localStorage.getItem('__stella_drive_bg_mode__')).toBe('image');
 expect(localStorage.getItem(sync.CLIENT_PREFERENCE_OWNER_KEY)).toBeNull();
 stop!();stop=undefined;localStorage.removeItem('stella_drive_bg_mode');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 expect(sync.clientPreferenceSync.state.phase).toBe('synced');
});
it.each(['stored invalid','live invalid','owner mismatch','storage failure'] as const)('isolates %s during a layout signal without confirming or uploading it',async boundary=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
 const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const before=calls.length;
 let storage:{mockRestore:()=>void}|undefined;
 try{
  if(boundary==='stored invalid')localStorage.setItem('stella_drive_bg_mode','invalid');
  if(boundary==='owner mismatch')localStorage.setItem(sync.CLIENT_PREFERENCE_OWNER_KEY,'bob');
  if(boundary==='storage failure'){
   const original=Storage.prototype.getItem;storage=vi.spyOn(Storage.prototype,'getItem').mockImplementation(function(this:Storage,key:string){if(key===sync.CLIENT_PREFERENCE_OWNER_KEY)throw Error('storage denied');return original.call(this,key);});
  }
  expect(()=>events.notifyClientPreferenceChange('stella_drive_bg_mode',boundary==='live invalid'?'invalid':undefined)).not.toThrow();
  expect(sync.clientPreferenceSync.state.phase).toBe('error');expect(sync.clientPreferenceSync.state.message).toMatch(/无效值|另一账号|storage denied/);
  await expect(sync.clientPreferenceSync.ensureConfirmed()).rejects.toThrow();await vi.advanceTimersByTimeAsync(60000);expect(calls).toHaveLength(before);
 }finally{storage?.mockRestore();}
 expect(localStorage.getItem(sync.CLIENT_PREFERENCE_OWNER_KEY)).toBe(boundary==='owner mismatch'?'bob':'alice');
});
it('isolates strict capture failure from reactive home changes without replacing invalid input',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const before=calls.length;
 expect(()=>{homeSettings.theme='invalid' as typeof homeSettings.theme;}).not.toThrow();
 expect(sync.clientPreferenceSync.state.phase).toBe('error');await vi.advanceTimersByTimeAsync(60000);expect(calls).toHaveLength(before);expect(homeSettings.theme).toBe('invalid');
});
it('releases each subscriber once and never lets an old release stop a surviving or restarted sync',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');remote={...defaultClientPreferences(),revision:12};
 const first=sync.startClientPreferenceSync();stop=first;const second=sync.startClientPreferenceSync();
 try{
  await sync.clientPreferenceSync.ensureConfirmed();first();first();
  expect(sync.clientPreferenceSync.state.phase).toBe('synced');const before=calls.length;auth.requestEpoch++;await settle();expect(calls.length).toBe(before+1);
 }finally{second();first();stop=undefined;}
 expect(sync.clientPreferenceSync.state.phase).toBe('idle');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 first();expect(sync.clientPreferenceSync.state.phase).toBe('synced');
});
it('aborts a released read and removes watchers/signals before a clean reentrant startup',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');
 remote={...defaultClientPreferences(),revision:12};const fetch=vi.mocked(globalThis.fetch),original=fetch.getMockImplementation()!;let finish!:(r:Response)=>void;
 fetch.mockImplementationOnce(async(path:any,options:RequestInit={})=>{await original(path,options);return new Promise<Response>(resolve=>{finish=resolve;});});
 stop=sync.startClientPreferenceSync();await settle();const signal=calls[0]!.signal!;stop();expect(signal.aborted).toBe(true);
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const before=calls.length;
 finish(new Response(JSON.stringify({...defaultClientPreferences(),revision:99,home:{...defaultClientPreferences().home,siteTitle:'stale released response'}}),{headers:{'Content-Type':'application/json'}}));await settle();
 expect(sync.clientPreferenceSync.state.revision).toBe(12);expect(homeSettings.siteTitle).not.toBe('stale released response');
 stop();stop=undefined;auth.requestEpoch++;homeSettings.siteTitle='after release';
 expect(()=>events.notifyClientPreferenceChange('stella_drive_bg_mode','invalid')).not.toThrow();await vi.advanceTimersByTimeAsync(60000);
 expect(sync.clientPreferenceSync.state.phase).toBe('idle');expect(calls).toHaveLength(before);
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();expect(calls).toHaveLength(before+1);
});
it.each(['ui read','owner read','owner write'] as const)('keeps startup %s storage failure explicit without rebinding another owner or uploading',async boundary=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');remote={...defaultClientPreferences(),revision:12};localStorage.setItem(sync.CLIENT_PREFERENCE_OWNER_KEY,'bob');
 const get=Storage.prototype.getItem,set=Storage.prototype.setItem;
 const storage=boundary==='owner write'?vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,key:string,value:string){if(key===sync.CLIENT_PREFERENCE_OWNER_KEY)throw Error('storage denied');return set.call(this,key,value);}):vi.spyOn(Storage.prototype,'getItem').mockImplementation(function(this:Storage,key:string){if(key===(boundary==='ui read'?'stella_drive_bg_mode':sync.CLIENT_PREFERENCE_OWNER_KEY))throw Error('storage denied');return get.call(this,key);});
 try{
  expect(()=>{stop=sync.startClientPreferenceSync();}).not.toThrow();await settle();
  expect(sync.clientPreferenceSync.state.phase).toBe('error');expect(sync.clientPreferenceSync.state.message).toContain('storage denied');
  await expect(sync.clientPreferenceSync.ensureConfirmed()).rejects.toThrow();await sync.clientPreferenceSync.retry();await vi.advanceTimersByTimeAsync(60000);
  expect(calls.some(c=>c.method==='GET')).toBe(true);expect(calls.some(c=>c.method!=='GET')).toBe(false);
 }finally{storage.mockRestore();}
 expect(localStorage.getItem(sync.CLIENT_PREFERENCE_OWNER_KEY)).toBe('bob');
});
it('snapshots only validated UI even when unrelated home input is invalid, and reads remote without uploading defaults',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');homeSettings.theme='invalid' as typeof homeSettings.theme;remote={...defaultClientPreferences(),revision:12};
 expect(()=>{stop=sync.startClientPreferenceSync();}).not.toThrow();await settle();expect(sync.clientPreferenceSync.state.phase).toBe('error');
 await sync.clientPreferenceSync.retry();expect(calls.map(c=>c.method)).toEqual(['GET']);expect(sync.clientPreferenceSync.state.phase).toBe('error');
 homeSettings.theme='daybreak';remote.revision++;await sync.clientPreferenceSync.retry();expect(sync.clientPreferenceSync.state.phase).toBe('conflict');
 sync.clientPreferenceSync.useServer();await sync.clientPreferenceSync.ensureConfirmed();expect(sync.clientPreferenceSync.state.reloadRequired).toBe(false);expect(calls.every(c=>c.method==='GET')).toBe(true);
});
it('preserves an invalid signal while initial GET is held and refuses the zero-revision seed after readback',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');
 const fetch=vi.mocked(globalThis.fetch),original=fetch.getMockImplementation()!;let finish!:(r:Response)=>void;
 fetch.mockImplementationOnce(async(path:any,options:RequestInit={})=>{await original(path,options);return new Promise<Response>(resolve=>{finish=resolve;});});
 stop=sync.startClientPreferenceSync();await settle();expect(()=>events.notifyClientPreferenceChange('stella_drive_bg_mode','invalid')).not.toThrow();
 finish(new Response(JSON.stringify(remote),{headers:{'Content-Type':'application/json'}}));await settle();await vi.advanceTimersByTimeAsync(60000);
 expect(sync.clientPreferenceSync.state.phase).toBe('error');expect(sync.clientPreferenceSync.state.message).toContain('无效值');expect(calls.map(c=>c.method)).toEqual(['GET']);expect(localStorage.getItem(sync.CLIENT_PREFERENCE_OWNER_KEY)).toBeNull();
 await expect(sync.clientPreferenceSync.ensureConfirmed()).rejects.toThrow();
});
it('automatically rebases only explicit appearance after CAS while retaining remote home/ui and active editor',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 const fetch=vi.mocked(globalThis.fetch);const original=fetch.getMockImplementation()!;let reject=true;
 fetch.mockImplementation(async(path:any,options:RequestInit={})=>{
  if(options.method==='PUT' && reject){reject=false;remote={...remote,revision:remote.revision+1,home:{...remote.home,siteTitle:'另一设备标题'},ui:{...remote.ui,sidebarFold:true}};return new Response(JSON.stringify({detail:'conflict'}),{status:409,headers:{'Content-Type':'application/json'}});}
  return original(path,options);
 });
 s.beginAppearanceEdit();s.setPaletteColor('accent','#123456',true);await vi.advanceTimersByTimeAsync(600);await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('synced');expect(remote.customAppearance?.overrides.accent).toBe('#123456');expect(remote.home.siteTitle).toBe('另一设备标题');expect(remote.ui.sidebarFold).toBe(true);expect(s.appearanceEditing.value).toBe(true);expect(s.resolvedPalette.value.accent).toBe('#123456');
 await vi.advanceTimersByTimeAsync(60000);expect(calls.filter(c=>c.method==='PUT')).toHaveLength(2);s.finishAppearanceEdit();
});
it('retains the server custom slot when an explicit A/B-only conflict is narrowly synchronized',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();s.setAppearance('A');
 remote={...remote,revision:remote.revision+1,customAppearance:{version:1,base:'B',overrides:{accent:'#DDCCAA'}}};auth.requestEpoch++;await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('conflict');await sync.clientPreferenceSync.useLocalAppearance();await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('synced');expect(remote.appearance).toBe('A');expect(remote.customAppearance?.overrides.accent).toBe('#DDCCAA');
});
it.each(['home','ui'] as const)('never auto-merges or overwrites unsent %s edits together with appearance',async field=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 const fetch=vi.mocked(globalThis.fetch),original=fetch.getMockImplementation()!;let attempts=0;
 fetch.mockImplementation(async(path:any,options:RequestInit={})=>{if(options.method==='PUT'){attempts++;return new Response('{}',{status:409,headers:{'Content-Type':'application/json'}});}return original(path,options);});
 if(field==='home')homeSettings.siteTitle='本机新标题';else events.notifyClientPreferenceChange('stella_sidebar_fold','1');
 s.setPaletteColor('accent','#334455');await vi.advanceTimersByTimeAsync(600);await settle();expect(sync.clientPreferenceSync.state.phase).toBe('conflict');expect(attempts).toBe(1);
 await sync.clientPreferenceSync.useLocalAppearance();expect(attempts).toBe(1);expect(homeSettings.siteTitle).toBe(field==='home'?'本机新标题':'内存中的真实设置');expect(s.resolvedPalette.value.accent).toBe('#334455');
});
it('bounds appearance CAS retry to one rebase and keeps colors on repeated collision',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 const fetch=vi.mocked(globalThis.fetch),original=fetch.getMockImplementation()!;let attempts=0;fetch.mockImplementation(async(path:any,options:RequestInit={})=>{if(options.method==='PUT'){attempts++;remote={...remote,revision:remote.revision+1};return new Response('{}',{status:409,headers:{'Content-Type':'application/json'}});}return original(path,options);});
 s.setPaletteColor('accent','#334455');await vi.advanceTimersByTimeAsync(600);await settle();expect(sync.clientPreferenceSync.state.phase).toBe('conflict');expect(attempts).toBe(2);await vi.advanceTimersByTimeAsync(60000);expect(attempts).toBe(2);expect(s.resolvedPalette.value.accent).toBe('#334455');
});
it.each(['owner','epoch','sibling','color'] as const)('fences newer %s input during the narrowed write readback',async boundary=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 s.setPaletteColor('accent','#334455');auth.requestEpoch++;await settle();expect(sync.clientPreferenceSync.state.phase).toBe('conflict');
 const fetch=vi.mocked(globalThis.fetch),original=fetch.getMockImplementation()!;let finish!:(r:Response)=>void;let held:Response|undefined;let hasWrite=false;
 fetch.mockImplementation(async(path:any,options:RequestInit={})=>{const result=await original(path,options);if(options.method==='PUT')hasWrite=true;else if(hasWrite && !held){held=result;return new Promise<Response>(r=>{finish=r;});}return result;});
 const pending=sync.clientPreferenceSync.useLocalAppearance();await vi.advanceTimersByTimeAsync(0);await settle();expect(held).toBeDefined();
 if(boundary==='owner'){remote={...defaultClientPreferences(),revision:14};Object.assign(auth,{me:{id:'bob'},sessionGeneration:2});}
 if(boundary==='epoch')auth.requestEpoch++;
 if(boundary==='sibling')homeSettings.siteTitle='请求期间新标题';
 if(boundary==='color')s.setPaletteColor('accent','#667788');
 await settle();finish(held!);await pending;await settle();
 if(boundary==='owner'){expect(s.appearance.value).toBe('A');expect(s.customAppearance.value).toBeNull();}
 if(boundary==='sibling'){expect(homeSettings.siteTitle).toBe('请求期间新标题');expect(sync.clientPreferenceSync.state.phase).toBe('conflict');}
 if(boundary==='color'){expect(s.resolvedPalette.value.accent).toBe('#667788');await vi.advanceTimersByTimeAsync(600);await sync.clientPreferenceSync.ensureConfirmed();expect(remote.customAppearance?.overrides.accent).toBe('#667788');}
 const count=calls.filter(c=>c.method==='PUT').length;await vi.advanceTimersByTimeAsync(60000);expect(calls.filter(c=>c.method==='PUT')).toHaveLength(count);
});
it('allows a new owner’s own later appearance edit to rebase after old-owner input was discarded',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 remote={...defaultClientPreferences(),revision:14};auth.me={id:'bob'} as typeof auth.me;await settle();await sync.clientPreferenceSync.ensureConfirmed();
 const fetch=vi.mocked(globalThis.fetch),original=fetch.getMockImplementation()!;let reject=true;fetch.mockImplementation(async(path:any,options:RequestInit={})=>{if(options.method==='PUT'&&reject){reject=false;remote={...remote,revision:remote.revision+1};return new Response('{}',{status:409,headers:{'Content-Type':'application/json'}});}return original(path,options);});
 s.setPaletteColor('accent','#456789');await vi.advanceTimersByTimeAsync(600);await settle();expect(sync.clientPreferenceSync.state.phase).toBe('synced');expect(remote.customAppearance?.overrides.accent).toBe('#456789');expect(localStorage.getItem(sync.CLIENT_PREFERENCE_OWNER_KEY)).toBe('bob');
});
it('does not treat reauthentication as permission to discard unsent sibling input in a narrow color conflict action',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 homeSettings.siteTitle='重新认证前的本机输入';s.setPaletteColor('accent','#456789');auth.requestEpoch++;await settle();expect(sync.clientPreferenceSync.state.phase).toBe('conflict');const writes=calls.filter(c=>c.method==='PUT').length;
 await sync.clientPreferenceSync.useLocalAppearance();expect(homeSettings.siteTitle).toBe('重新认证前的本机输入');expect(calls.filter(c=>c.method==='PUT')).toHaveLength(writes);expect(sync.clientPreferenceSync.state.phase).toBe('conflict');expect(sync.clientPreferenceSync.state.message).toContain('其他设置');
});
it('uploads valid custom edits while editor is open, coalesces a color drag, and preserves custom through presets',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 const s=await import('../../stores/appearance');const before=calls.filter(c=>c.method==='PUT').length;
 s.beginAppearanceEdit();for(const color of ['#112233','#445566','#ABCDEF']){s.setPaletteColor('accent',color,true);await vi.advanceTimersByTimeAsync(100);}
 expect(calls.filter(c=>c.method==='PUT')).toHaveLength(before);
 await vi.advanceTimersByTimeAsync(600);await sync.clientPreferenceSync.ensureConfirmed();expect(calls.filter(c=>c.method==='PUT')).toHaveLength(before+1);expect(s.appearanceEditing.value).toBe(true);s.finishAppearanceEdit();
 expect(remote.appearance).toBe('custom');expect(remote.customAppearance).toEqual({version:1,base:'B',overrides:{accent:'#ABCDEF'}});
 s.setAppearance('A');await vi.advanceTimersByTimeAsync(600);await sync.clientPreferenceSync.ensureConfirmed();expect(remote.customAppearance?.overrides.accent).toBe('#ABCDEF');
 auth.requestEpoch++;await settle();expect(s.customAppearance.value?.overrides.accent).toBe('#ABCDEF');expect(calls.filter(c=>c.method==='PUT')).toHaveLength(3);
});
it('does not let a legacy cloud A/B erase this owner’s retained custom palette',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
 const s=await import('../../stores/appearance');
 s.hydrateAppearance('custom',{version:1,base:'B',overrides:{accent:'#ABCDEF'}});
 localStorage.setItem(sync.CLIENT_PREFERENCE_OWNER_KEY,'alice');remote={...defaultClientPreferences(),revision:12};
 stop=sync.startClientPreferenceSync();await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('conflict');expect(s.customAppearance.value?.overrides.accent).toBe('#ABCDEF');expect(calls.map(c=>c.method)).toEqual(['GET']);
});
it('cancels old-owner preview before hydrating a new owner, without replaying its custom edits',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
 s.beginAppearanceEdit();s.setPaletteColor('accent','#ABCDEF',true);
 remote={...defaultClientPreferences(),revision:14};Object.assign(auth,{me:{id:'bob'},sessionGeneration:2});await settle();
 expect(s.appearanceEditing.value).toBe(false);expect(s.appearance.value).toBe('A');expect(s.customAppearance.value).toBeNull();
 expect(calls.filter(c=>c.method==='PUT')).toHaveLength(1);
});
it('retains a color preview on a same-owner remote update as an explicit conflict, never an automatic write',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');
 stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const before=calls.filter(c=>c.method==='PUT').length;
 s.beginAppearanceEdit();s.setPaletteColor('accent','#ABCDEF',true);remote={...remote,revision:remote.revision+1,appearance:'A'};auth.requestEpoch++;await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('conflict');expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');expect(calls.filter(c=>c.method==='PUT')).toHaveLength(before);
 s.cancelAppearanceEdit();sync.clientPreferenceSync.useServer();expect(s.appearance.value).toBe('A');
});
it('does not upload a redundant click on the currently selected preset',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const before=calls.length;
 setAppearance('B');await vi.advanceTimersByTimeAsync(600);expect(calls).toHaveLength(before);
});
it('retains an unconfirmed custom change across sync restart even if the cloud has an older custom record',async()=>{
 const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');const s=await import('../../stores/appearance');
 const custom={version:1 as const,base:'B' as const,overrides:{accent:'#AABBCC'}};
 s.hydrateAppearance('custom',custom);s.setPaletteColor('accent','#ABCDEF');remote={...defaultClientPreferences(),revision:12,appearance:'custom',customAppearance:custom};
 stop=sync.startClientPreferenceSync();await settle();
 expect(sync.clientPreferenceSync.state.phase).toBe('conflict');expect(s.resolvedPalette.value.accent).toBe('#ABCDEF');expect(localStorage.getItem('stella_appearance_unconfirmed')).toBe('1');
 await sync.clientPreferenceSync.useLocal();expect(remote.customAppearance?.overrides.accent).toBe('#ABCDEF');expect(localStorage.getItem('stella_appearance_unconfirmed')).toBeNull();
});
it('starts on an anonymous cold browser without an owner conflict, then hydrates only after login',async()=>{
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
  Object.assign(auth,{me:null});
  expect(()=>{stop=sync.startClientPreferenceSync();}).not.toThrow();
  await settle();expect(calls).toEqual([]);
  Object.assign(auth,{me:{id:'alice'},sessionGeneration:2});await settle();
  await sync.clientPreferenceSync.ensureConfirmed();expect(calls.length).toBeGreaterThan(0);
  expect(localStorage.getItem(sync.CLIENT_PREFERENCE_OWNER_KEY)).toBe('alice');
});
it('connects real home/appearance/quality stores to owner HTTP in normal use without creating a backup or reading private storage',async()=>{
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');expect(sync,'live store HTTP sync adapter missing').toBeDefined();
  localStorage.setItem('stella_token','never-transfer');localStorage.setItem('stella_note_draft_private','private-body');
  const enumerate=vi.spyOn(Storage.prototype,'key');stop=sync.startClientPreferenceSync();await settle();await sync.clientPreferenceSync.ensureConfirmed();
  expect(remote.home.siteTitle).toBe('内存中的真实设置');expect(remote.home.signature).toBe('实际签名');expect(remote.appearance).toBe('B');expect(enumerate).not.toHaveBeenCalled();
  homeSettings.siteTitle='平时主页更新';homeSettings.bgCrop={cx:.3,cy:.4,w:.7,h:.8};setAppearance('A');setBackgroundQuality('original');await vi.advanceTimersByTimeAsync(600);await settle();
  await sync.clientPreferenceSync.ensureConfirmed();expect(remote.home.siteTitle).toBe('平时主页更新');expect(remote.home.bgCrop.cx).toBe(.3);expect(remote.appearance).toBe('A');expect(remote.ui.backgroundQuality).toBe('original');
  expect(JSON.stringify(calls)).not.toMatch(/never-transfer|private-body|stella_token|stella_note_draft_private/);expect(calls.every(c=>c.path.endsWith('/client-preferences'))).toBe(true);expect(appearance.value).toBe('A');
});
it('does not mistake absent default layout keys for a layout change',async()=>{
  remote={...defaultClientPreferences(),revision:12};
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
  localStorage.setItem('stella_note_draft_private','retained body');
  stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
  expect(sync.clientPreferenceSync.state.reloadRequired).toBe(false);
  expect(calls.map(c=>c.method)).toEqual(['GET']);
  expect(localStorage.getItem('stella_note_draft_private')).toBe('retained body');
});
it('keeps a genuine deferred-layout notice and dismissal across same-owner session fences, but not a new owner',async()=>{
  remote={...defaultClientPreferences(),revision:12};remote.ui.noteEditMode='markdown';
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');
  stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
  expect(sync.clientPreferenceSync.state.reloadRequired).toBe(true);
  sync.clientPreferenceSync.dismissReload();expect(sync.clientPreferenceSync.state.reloadDismissed).toBe(true);
  auth.requestEpoch++;await settle();await sync.clientPreferenceSync.ensureConfirmed();
  expect(sync.clientPreferenceSync.state.reloadRequired).toBe(true);expect(sync.clientPreferenceSync.state.reloadDismissed).toBe(true);
  Object.assign(auth,{me:{id:'bob'},sessionGeneration:2});await settle();
  expect(sync.clientPreferenceSync.state.reloadDismissed).toBe(false);
});
it('captures all audited layout signals without observing arbitrary storage writes',async()=>{
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await settle();await sync.clientPreferenceSync.ensureConfirmed();
  const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');expect(events,'layout preference signals missing').toBeDefined();
  for(const [key,value] of Object.entries({stella_sidebar_fold:'1',stella_servers_fold:'1',stella_tools_open:'1',stella_server_world_map_collapsed:'1',stella_mon_mode:'simple',stella_note_edit_mode:'markdown',stella_list_fold:'1',stella_drive_bg_mode:'image'})){
    localStorage.setItem(key,value);events.notifyClientPreferenceChange(key as never);
  }
  await vi.advanceTimersByTimeAsync(600);await settle();expect(remote.ui).toMatchObject({sidebarFold:true,serversFold:true,toolsOpen:true,worldMapCollapsed:true,monitorMode:'simple',noteEditMode:'markdown',listFold:true,driveBackground:'image'});
  const before=calls.length;localStorage.setItem('private-draft','not-observed');await vi.advanceTimersByTimeAsync(60000);expect(calls).toHaveLength(before);
});
it('uses an explicit layout choice even if that control’s old device persistence could not change',async()=>{
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
  const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');
  localStorage.setItem('stella_server_world_map_collapsed','0');events.notifyClientPreferenceChange('stella_server_world_map_collapsed','1');
  await vi.advanceTimersByTimeAsync(600);await sync.clientPreferenceSync.ensureConfirmed();expect(remote.ui.worldMapCollapsed).toBe(true);
});
it('does not re-hydrate or poll preferences when the auth watchdog refreshes the same owner profile',async()=>{
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const before=calls.length;
  auth.me={...auth.me!};await settle();expect(calls).toHaveLength(before);
});
it('retains a live layout choice through same-owner reauthentication without replaying the old write',async()=>{
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');
  events.notifyClientPreferenceChange('stella_server_world_map_collapsed','1');auth.requestEpoch++;await settle();expect(sync.clientPreferenceSync.state.phase).toBe('conflict');
  await sync.clientPreferenceSync.useLocal();expect(remote.ui.worldMapCollapsed).toBe(true);
});
it('marks layout reload required when restored values differ from a live choice whose device write failed',async()=>{
  const contract=await import('./clientPreferenceContract');for(const [key,value] of Object.entries(contract.clientPreferencesToLocal(defaultClientPreferences()).values))localStorage.setItem(key,value!);
  const sync=modules['./clientPreferenceSync.ts'] as typeof import('./clientPreferenceSync');stop=sync.startClientPreferenceSync();await sync.clientPreferenceSync.ensureConfirmed();
  const events=eventModules['./clientPreferenceEvents.ts'] as typeof import('./clientPreferenceEvents');events.notifyClientPreferenceChange('stella_server_world_map_collapsed','1');await vi.advanceTimersByTimeAsync(600);await sync.clientPreferenceSync.ensureConfirmed();
  sync.clientPreferenceSync.beginRestore();remote={...defaultClientPreferences(),revision:8};await sync.clientPreferenceSync.refreshAfterRestore();expect(sync.clientPreferenceSync.state.reloadRequired).toBe(true);
});
