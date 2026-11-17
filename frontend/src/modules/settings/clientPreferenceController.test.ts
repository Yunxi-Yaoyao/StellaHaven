import {afterEach,expect,it,vi} from 'vitest';
import {reactive} from 'vue';
import {defaultClientPreferences,preferenceContent,type ClientPreferences,type ClientPreferenceContent,type ClientPreferencesWrite} from './clientPreferenceContract';
const modules=import.meta.glob('./clientPreferenceController.ts',{eager:true});
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
let stop:undefined|(()=>void);
afterEach(()=>{stop?.();stop=undefined;vi.useRealTimers();});
function setup(remote=defaultClientPreferences()){
  const factory=modules['./clientPreferenceController.ts'] as typeof import('./clientPreferenceController');expect(factory,'account preference controller missing').toBeDefined();
  const session=reactive({owner:'alice',generation:1,epoch:1,blocked:false});
  let local:ClientPreferenceContent=preferenceContent(defaultClientPreferences());local.home.siteTitle='本机真实主页';local.appearance='B';
  const read=vi.fn(async(_signal:AbortSignal)=>structuredClone(remote));
  const write=vi.fn(async(data:ClientPreferencesWrite,_signal:AbortSignal)=>{remote={revision:remote.revision+1,appearance:data.appearance,home:structuredClone(data.home),ui:structuredClone(data.ui)};return remote;});
  const apply=vi.fn((value:ClientPreferenceContent)=>{local=structuredClone(value);return {reloadRequired:false};});
  const controller=factory.createClientPreferenceController({session:()=>({...session}),capture:()=>structuredClone(local),apply,read,write,canSeed:()=>true,bindOwner:()=>{}});
  stop=controller.stop;
  return {controller,session,read,write,apply,get local(){return local;},set local(value){local=value;},get remote(){return remote;}};
}
it('seeds an empty owner slot with actual local choices, confirms via GET and debounces ordinary setting changes',async()=>{
  vi.useFakeTimers();const s=setup();await settle();
  expect(s.write).toHaveBeenCalledTimes(1);expect(s.write.mock.calls[0]![0]).toMatchObject({expected_revision:0,appearance:'B',home:{siteTitle:'本机真实主页'}});
  expect(s.read).toHaveBeenCalledTimes(2);expect(s.controller.state.phase).toBe('synced');
  s.local.home.siteTitle='日常修改无需进入备份页';s.controller.changed();
  s.local.home.particles='off';s.controller.changed();await vi.advanceTimersByTimeAsync(600);await settle();
  expect(s.write).toHaveBeenCalledTimes(2);expect(s.remote.home.siteTitle).toBe('日常修改无需进入备份页');expect(s.remote.home.particles).toBe('off');expect(s.controller.state.revision).toBe(2);
  await vi.advanceTimersByTimeAsync(60000);expect(s.read).toHaveBeenCalledTimes(3); // no browser polling for scheduled backups
});
it('preserves edits made while existing server preferences load and requires an explicit conflict choice',async()=>{
  const remote=defaultClientPreferences();remote.revision=4;remote.home.siteTitle='另一设备';
  const s=setup(remote);s.local.home.siteTitle='加载期间的新输入';s.controller.changed();await settle();
  expect(s.apply).not.toHaveBeenCalled();expect(s.local.home.siteTitle).toBe('加载期间的新输入');expect(s.controller.state.phase).toBe('conflict');expect(s.write).not.toHaveBeenCalled();
  await s.controller.useLocal();await settle();expect(s.write).toHaveBeenCalledTimes(1);expect(s.write.mock.calls[0]![0].expected_revision).toBe(4);expect(s.remote.home.siteTitle).toBe('加载期间的新输入');expect(s.controller.state.phase).toBe('synced');
});
it('handles a CAS rejection with one read and no write replay, preserving local input until server choice',async()=>{
  vi.useFakeTimers();const s=setup();await settle();
  const remote=defaultClientPreferences();remote.revision=7;remote.home.siteTitle='远端并发修改';
  s.write.mockRejectedValueOnce(Object.assign(new Error('conflict'),{status:409}));s.read.mockResolvedValueOnce(remote);
  s.local.home.siteTitle='不丢本机';s.controller.changed();await vi.advanceTimersByTimeAsync(600);await settle();
  expect(s.controller.state.phase).toBe('conflict');expect(s.controller.state.revision).toBe(7);expect(s.local.home.siteTitle).toBe('不丢本机');
  await vi.advanceTimersByTimeAsync(60000);expect(s.write).toHaveBeenCalledTimes(2);
  await s.controller.useServer();expect(s.local.home.siteTitle).toBe('远端并发修改');expect(s.write).toHaveBeenCalledTimes(2);expect(s.controller.state.phase).toBe('synced');
});
it('stops on network failure, keeps later input, and reconciles an uncertain save before explicit retry',async()=>{
  vi.useFakeTimers();const s=setup();await settle();
  s.write.mockRejectedValueOnce(new Error('network down'));s.local.home.signature='失败输入';s.controller.changed();await vi.advanceTimersByTimeAsync(600);await settle();
  expect(s.controller.state.phase).toBe('error');s.local.home.signature='失败后的新输入';s.controller.changed();await vi.advanceTimersByTimeAsync(60000);expect(s.write).toHaveBeenCalledTimes(2);
  await expect(s.controller.ensureConfirmed()).rejects.toThrow(/偏好/);
  await s.controller.retry();await settle();expect(s.remote.home.signature).toBe('失败后的新输入');expect(s.controller.state.phase).toBe('synced');
  // PUT may have committed even if its following GET was lost. Retry must read, not replay.
  s.read.mockRejectedValueOnce(new Error('readback lost'));s.local.home.signature='已提交待回读';s.controller.changed();await vi.advanceTimersByTimeAsync(600);await settle();
  expect(s.controller.state.phase).toBe('error');const writes=s.write.mock.calls.length;await s.controller.retry();expect(s.write).toHaveBeenCalledTimes(writes);expect(s.controller.state.phase).toBe('synced');
});
it('never seeds an empty second account with the previous account’s local preferences',async()=>{
  const s=setup();await settle();s.read.mockResolvedValueOnce(defaultClientPreferences());s.session.owner='bob';await settle();
  expect(s.write).toHaveBeenCalledTimes(1);expect(s.local).toEqual(preferenceContent(defaultClientPreferences()));expect(s.controller.state.revision).toBe(0);
});
it.each(['owner','generation','epoch','blocked','stop'] as const)('fences a held response on %s and aborts its request',async boundary=>{
  const s=setup();await settle();let finish!:(r:ClientPreferences)=>void;
  s.read.mockImplementationOnce(()=>new Promise(r=>{finish=r;}));
  s.local.home.siteTitle='held';s.controller.changed();const pending=s.controller.ensureConfirmed();await settle();
  const signal=s.read.mock.calls.at(-1)![0];
  if(boundary==='owner')s.session.owner='bob';if(boundary==='generation')s.session.generation++;if(boundary==='epoch')s.session.epoch++;if(boundary==='blocked')s.session.blocked=true;if(boundary==='stop')s.controller.stop();
  await settle();expect(signal.aborted).toBe(true);const phase=s.controller.state.phase,local=structuredClone(s.local),revision=s.controller.state.revision;
  const late=defaultClientPreferences();late.revision=99;late.home.siteTitle='late-other-owner';finish(late);await pending.catch(()=>{});await settle();
  expect(s.local).toEqual(local);expect(s.controller.state.phase).toBe(phase);expect(s.controller.state.revision).toBe(revision);
});
it.each(['blocked','generation','epoch'] as const)('retains unsynced same-owner input across %s instead of re-hydrating over it',async boundary=>{
  vi.useFakeTimers();const s=setup();await settle();s.local.home.siteTitle='先输入后过期';s.controller.changed();
  if(boundary==='blocked'){s.session.blocked=true;await settle();s.session.blocked=false;}
  if(boundary==='generation')s.session.generation++;
  if(boundary==='epoch')s.session.epoch++;
  await settle();expect(s.local.home.siteTitle).toBe('先输入后过期');expect(s.controller.state.phase).toBe('conflict');expect(s.write).toHaveBeenCalledTimes(1);
  await s.controller.useLocal();expect(s.remote.home.siteTitle).toBe('先输入后过期');expect(s.controller.state.phase).toBe('synced');
});
it('pauses pending local writes throughout restore then reads and applies the confirmed server preferences without re-upload',async()=>{
  vi.useFakeTimers();const s=setup();await settle();s.local.home.siteTitle='准备被恢复替换';s.controller.changed();s.controller.beginRestore();
  await vi.advanceTimersByTimeAsync(600);expect(s.write).toHaveBeenCalledTimes(1);
  const restored=defaultClientPreferences();restored.revision=8;restored.appearance='B';restored.home.siteTitle='恢复标题';s.read.mockResolvedValueOnce(restored);
  await s.controller.refreshAfterRestore();expect(s.local.home.siteTitle).toBe('恢复标题');expect(s.local.appearance).toBe('B');expect(s.controller.state.revision).toBe(8);
  await vi.advanceTimersByTimeAsync(60000);expect(s.write).toHaveBeenCalledTimes(1);expect(s.controller.state.phase).toBe('synced');
});
it('does not overwrite edits made during restore/readback and leaves a manual conflict choice',async()=>{
  const s=setup();await settle();s.controller.beginRestore();s.local.home.siteTitle='恢复等待期间输入';s.controller.changed();
  const restored=defaultClientPreferences();restored.revision=9;s.read.mockResolvedValueOnce(restored);
  await s.controller.refreshAfterRestore();expect(s.local.home.siteTitle).toBe('恢复等待期间输入');expect(s.controller.state.phase).toBe('conflict');expect(s.write).toHaveBeenCalledTimes(1);
});
