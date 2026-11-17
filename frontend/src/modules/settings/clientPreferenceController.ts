import {reactive,watch} from 'vue';
import {preferenceContent,preferenceFingerprint,validateClientPreferences,type ClientPreferenceContent,type ClientPreferences,type ClientPreferencesWrite} from './clientPreferenceContract';

export interface PreferenceSession {owner:string|undefined;generation:number;epoch:number;blocked:boolean}
export interface PreferenceDependencies {
  session:()=>PreferenceSession;
  capture:()=>ClientPreferenceContent;
  apply:(value:ClientPreferenceContent)=>{reloadRequired:boolean;reloadKey?:string};
  read:(signal:AbortSignal)=>Promise<ClientPreferences>;
  write:(value:ClientPreferencesWrite,signal:AbortSignal)=>Promise<ClientPreferences>;
  canSeed:(owner:string)=>boolean;
  bindOwner:(owner:string)=>void;
  isEditing?:()=>boolean;
  applyNonAppearance?:(value:ClientPreferenceContent)=>{reloadRequired:boolean;reloadKey?:string};
  hasUnconfirmed?:()=>boolean;
  onConfirmed?:(value:ClientPreferences)=>void;
}
export type PreferencePhase='idle'|'loading'|'pending'|'saving'|'synced'|'conflict'|'error'|'blocked'|'restoring';
export function createClientPreferenceController(deps:PreferenceDependencies){
  const state=reactive({phase:'idle' as PreferencePhase,message:'',revision:null as number|null,reloadRequired:false,reloadDismissed:false,
    restoreWaiting:false,restoreJobId:null as string|null,restorePreviousJobId:null as string|null});
  let confirmed:ClientPreferences|null=null, generation=0, dead=false, applying=false;
  let abort=new AbortController(), timer:ReturnType<typeof setTimeout>|undefined;
  let inFlight:Promise<void>|null=null;
  let lastOwner:string|undefined, seedAllowed=false;
  let localEdits=false;
  let reloadKey:string|undefined;
  const siblings=(value:ClientPreferenceContent)=>JSON.stringify({home:value.home,ui:value.ui});
  let siblingBase:string|undefined;
  function applyRemote(value:ClientPreferenceContent,appearanceOnly=false){
    const result=appearanceOnly && deps.applyNonAppearance?deps.applyNonAppearance(value):deps.apply(value);
    if(result.reloadKey!==reloadKey || !result.reloadRequired)state.reloadDismissed=false;
    state.reloadRequired=result.reloadRequired;reloadKey=result.reloadKey;
  }
  function dismissReload(){if(state.reloadRequired)state.reloadDismissed=true;}
  let restoreSource:string|null=null,restoreOwner:string|undefined,restoreReady=false;
  function clearRestore(){restoreSource=null;restoreOwner=undefined;restoreReady=false;state.restoreWaiting=false;state.restoreJobId=null;state.restorePreviousJobId=null;}
  const local=()=>deps.capture();
  const same=(value:ClientPreferenceContent)=>preferenceFingerprint(local())===preferenceFingerprint(value);
  const allowed=()=>!dead && !!deps.session().owner && !deps.session().blocked;
  const current=(token:number)=>allowed() && token===generation && !abort.signal.aborted;
  function invalidate(){generation++;abort.abort();abort=new AbortController();clearTimeout(timer);inFlight=null;}
  function failure(reason:unknown){state.phase='error';state.message=reason instanceof Error?reason.message:'账号偏好同步失败，本机输入已保留';}
  function conflict(){state.phase='conflict';state.message='服务器偏好已改变，本机输入已保留；请选择使用服务器或保留本机输入';}
  function markSynced(value:ClientPreferences){confirmed=validateClientPreferences(value);state.revision=confirmed.revision;deps.bindOwner(deps.session().owner!);deps.onConfirmed?.(confirmed);siblingBase=siblings(confirmed);localEdits=false;state.phase='synced';state.message='此设备可移植偏好已由服务器确认';}
  async function save(token:number){
    if(!confirmed || !current(token) || restoreSource!==null)return;
    const source=local(),base=confirmed;state.phase='saving';
    try{await deps.write({...source,expected_revision:confirmed.revision},abort.signal);}
    catch(reason){
      if(!current(token))return;
      if(reason && typeof reason==='object' && 'status' in reason && reason.status===409){
        const remote=validateClientPreferences(await deps.read(abort.signal));
        if(current(token)){
          confirmed=remote;state.revision=remote.revision;
          if(deps.hasUnconfirmed?.() && deps.applyNonAppearance && siblings(source)===siblings(base) && siblings(local())===siblings(base)){await saveAppearance(token,remote);return;}
          conflict();
        }return;
      }
      throw reason;
    }
    if(!current(token))return;
    const read=validateClientPreferences(await deps.read(abort.signal));
    if(!current(token))return;
    if(preferenceFingerprint(read)!==preferenceFingerprint(source))throw Error('服务器偏好回读不一致，本机输入已保留');
    markSynced(read);
    if(!same(read))changed();
  }
  // A color edit is explicit intent for appearance, never for stale home/ui.
  // One bounded CAS rebase; a second collision stays visible for a later retry.
  async function saveAppearance(token:number,remote:ClientPreferences){
    if(!current(token) || restoreSource!==null)return;
    if(!deps.canSeed(deps.session().owner!)){conflict();return;}
    const source=local(),before=siblings(source);
    if(before!==siblingBase){conflict();state.message='其他设置也有本机修改，请在备份与恢复页处理偏好冲突；当前输入已保留。';return;}
    const merged=preferenceContent({...remote,appearance:source.appearance,customAppearance:source.customAppearance??remote.customAppearance});
    state.phase='saving';
    try{await deps.write({...merged,expected_revision:remote.revision},abort.signal);}
    catch(reason){if(!current(token))return;if(reason && typeof reason==='object' && 'status' in reason && reason.status===409){conflict();return;}throw reason;}
    if(!current(token))return;
    const read=validateClientPreferences(await deps.read(abort.signal));
    if(!current(token))return;
    if(preferenceFingerprint(read)!==preferenceFingerprint(merged))throw Error('服务器配色回读不一致，本机配色已保留');
    confirmed=read;state.revision=read.revision;
    // A sibling edited during the held request is not permission to overwrite it.
    if(siblings(local())!==before){conflict();return;}
    applying=true;
    try{applyRemote(preferenceContent(read),true);}finally{applying=false;}
    markSynced(read);if(!same(read))changed();
  }
  function useLocalAppearance(){
    if(state.phase!=='conflict' || restoreSource!==null || !deps.applyNonAppearance)return Promise.resolve();
    return run(async token=>{const remote=validateClientPreferences(await deps.read(abort.signal));if(current(token))await saveAppearance(token,remote);});
  }
  function run(work:(token:number)=>Promise<void>){
    if(inFlight || !allowed())return inFlight ?? Promise.resolve();
    const token=generation;
    const task=work(token).catch(reason=>{if(current(token))failure(reason);}).finally(()=>{if(current(token) && inFlight===task)inFlight=null;});
    inFlight=task;return task;
  }
  async function initialize(token:number){
    state.phase='loading';
    const source=preferenceFingerprint(local());siblingBase??=siblings(local());
    const remote=validateClientPreferences(await deps.read(abort.signal));
    if(!current(token))return;
    confirmed=remote;state.revision=remote.revision;
    if(remote.revision===0 && seedAllowed && deps.canSeed(deps.session().owner!)){await save(token);return;}
    if(deps.isEditing?.()){if(same(remote))markSynced(remote);else conflict();return;}
    if(deps.canSeed(deps.session().owner!) && deps.hasUnconfirmed?.() && !same(remote)){conflict();return;}
    // Old A/B records predate custom palettes. Require an explicit choice rather
    // than silently destroying this same owner's one retained custom record.
    if(deps.canSeed(deps.session().owner!) && local().customAppearance && !remote.customAppearance){conflict();return;}
    if((localEdits || source!==preferenceFingerprint(local())) && !same(remote)){conflict();return;}
    applying=true;
    try{applyRemote(preferenceContent(remote));}
    finally{applying=false;}
    markSynced(remote);
  }
  function changed(){
    if(applying || !allowed())return;
    if(confirmed && state.phase==='synced' && same(confirmed))return;
    localEdits=true;
    if(restoreSource!==null || !confirmed || ['loading','saving','error','conflict','restoring'].includes(state.phase))return;
    clearTimeout(timer);state.phase='pending';state.message='本机偏好待同步';
    timer=setTimeout(()=>{void run(save);},400);
  }
  // Profile-object refreshes are not new sessions and must never become a preference poll.
  const unwatch=watch(()=>{const s=deps.session();return JSON.stringify([s.owner,s.generation,s.epoch,s.blocked]);},()=>{
    const owner=deps.session().owner;
    if(owner && lastOwner && owner!==lastOwner){localEdits=false;siblingBase=undefined;state.reloadDismissed=false;reloadKey=undefined;}
    // Invalidate requests, not the same owner's already admitted restore.
    // A view may unmount or management elevation may expire before the job ends.
    const resumeRestore=restoreSource!==null && !!owner && restoreOwner===owner;
    invalidate();confirmed=null;state.revision=null;state.reloadRequired=false;
    if(!resumeRestore)clearRestore();
    if(!allowed()){state.phase='blocked';state.message='登录后继续同步账号偏好';return;}
    seedAllowed=lastOwner===undefined || lastOwner===owner;lastOwner=owner;
    if(resumeRestore){state.phase='restoring';state.message='等待已受理恢复任务的新会话状态确认，暂不上传偏好';return;}
    void run(initialize);
  },{immediate:true,flush:'sync'});
  async function ensureConfirmed(){
    clearTimeout(timer);await inFlight;
    if(state.phase==='pending')await run(save);
    if(state.phase!=='synced' || !confirmed || !same(confirmed))throw Error('本机偏好尚未由服务器确认，请先处理偏好同步状态');
  }
  function useLocal(){if(state.phase!=='conflict')return Promise.resolve();return run(save);}
  function useServer(){
    if(state.phase!=='conflict' || !confirmed || !allowed() || inFlight)return;
    applying=true;
    try{applyRemote(preferenceContent(confirmed));markSynced(confirmed);}
    catch(reason){failure(reason);}
    finally{applying=false;}
  }
  function retry(){
    if(!['error','conflict'].includes(state.phase))return Promise.resolve();
    if(restoreSource!==null){
      if(restoreReady)return refreshAfterRestore();
      state.phase='restoring';state.message='恢复任务尚未确认结束，请在备份与恢复页重新读取状态';return Promise.resolve();
    }
    const mustChoose=state.phase==='conflict', previous=confirmed?.revision;
    return run(async token=>{
      state.phase='loading';
      const remote=validateClientPreferences(await deps.read(abort.signal));
      if(!current(token))return;
      confirmed=remote;state.revision=remote.revision;
      if(same(remote)){markSynced(remote);return;}
      if(mustChoose || previous===undefined || remote.revision!==previous){conflict();return;}
      await save(token);
    });
  }
  function beginRestore(jobId:string|null=null,previousJobId:string|null=null){
    if(!allowed())throw Error('请登录后恢复账号偏好');
    if(restoreSource!==null && restoreOwner===deps.session().owner){
      if(jobId && !state.restoreJobId)state.restoreJobId=jobId;
      return; // Preserve input fingerprint and admitted identity on ACK/re-entry.
    }
    invalidate();restoreSource=preferenceFingerprint(local());restoreOwner=deps.session().owner;restoreReady=false;
    state.restoreWaiting=true;state.restoreJobId=jobId;state.restorePreviousJobId=previousJobId;
    state.phase='restoring';state.message='设置恢复期间暂停本机偏好上传，完成后重新读取';
  }
  function refreshAfterRestore(){
    if(restoreSource===null)return Promise.resolve();
    // Caller has reconciled this admitted job's terminal state (or a definite
    // rejected submission); retry may repeat only this read, never the restore.
    restoreReady=true;
    return run(async token=>{
      state.phase='loading';
      const remote=validateClientPreferences(await deps.read(abort.signal));
      if(!current(token))return;
      confirmed=remote;state.revision=remote.revision;
      if(restoreSource!==preferenceFingerprint(local()) && !same(remote)){clearRestore();conflict();return;}
      applying=true;
      try{applyRemote(preferenceContent(remote));}
      finally{applying=false;}
      markSynced(remote);clearRestore();
    });
  }
  function stop(){dead=true;invalidate();unwatch();}
  return {state,changed,ensureConfirmed,useLocal,useLocalAppearance,useServer,retry,beginRestore,refreshAfterRestore,dismissReload,stop};
}
