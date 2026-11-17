import {reactive,watch} from 'vue';
import {auth} from '../home/auth';
import {homeSettings} from '../home/settings';
import {appearancePreference,hydrateAppearance,appearanceEditing,appearanceError,cancelAppearanceEdit,appearanceUnconfirmed,confirmAppearance,retainAccountCustom} from '../../stores/appearance';
import {quality} from '../home/backgroundMedia';
import {getClientPreferences,putClientPreferences} from '../../api/backups';
import {applyBackupClientPreferences,type BackupClientPreferences,type ClientPreferenceKey} from './backupClientPreferences';
import {HOME_LOCAL_KEYS,UI_LOCAL_KEYS,clientPreferencesToLocal,localToClientPreferences,preferenceContent,validateClientPreferences,type ClientPreferenceContent} from './clientPreferenceContract';
import {createClientPreferenceController,type PreferencePhase} from './clientPreferenceController';
import {onClientPreferenceChange} from './clientPreferenceEvents';

// This one metadata key binds device preferences to an owner; it is NEVER sent or backed up.
export const CLIENT_PREFERENCE_OWNER_KEY='stella_client_preferences_owner';
let boundOwner:string|undefined;
let activeLayout:ClientPreferenceContent['ui']|undefined;
const liveLayout=new Map<ClientPreferenceKey,{owner:string|undefined;generation:number;epoch:number;value:string}>();
function layoutValue(key:ClientPreferenceKey){
  const choice=liveLayout.get(key);
  return choice && choice.owner===auth.me?.id && choice.generation===auth.sessionGeneration && choice.epoch===auth.requestEpoch ? choice.value : localStorage.getItem(key);
}
function captureUi():ClientPreferenceContent['ui'] {
  const values:BackupClientPreferences['values']={};
  for(const key of Object.values(UI_LOCAL_KEYS)){const value=layoutValue(key);if(value!==null)values[key]=value;}
  return localToClientPreferences({version:1,values}).ui;
}
function capture():ClientPreferenceContent {
  const owner=auth.me?.id;
  // Even before binding, unreadable ownership must never become seed permission
  // on a later retry. Keep this read in strict capture, not the layout snapshot.
  const savedOwner=owner?localStorage.getItem(CLIENT_PREFERENCE_OWNER_KEY):null;
  if(owner && boundOwner===owner && savedOwner!==owner)throw Error('此浏览器偏好已由另一账号改变，请重新登录后读取；未上传本机输入');
  // Snapshot real, already-migrated in-memory home choices, not stale/missing persistence.
  const home=Object.fromEntries(Object.keys(HOME_LOCAL_KEYS).map(field=>[field,JSON.parse(JSON.stringify(homeSettings[field as keyof typeof homeSettings]))]));
  const ui=captureUi();ui.backgroundQuality=quality.value;
  const saved=appearancePreference.value;
  return preferenceContent(validateClientPreferences({revision:0,appearance:saved.appearance,...(saved.customAppearance?{customAppearance:saved.customAppearance}:{}),home,ui}));
}
function apply(content:ClientPreferenceContent,nonAppearance=false){
  if(!nonAppearance && appearanceEditing.value)throw Error('正在调色，本机草稿已保留；请完成或取消后重试同步');
  const incoming=clientPreferencesToLocal({...content,revision:0});
  if(nonAppearance){delete incoming.values.stella_appearance;delete incoming.values.stella_custom_appearance;}
  // Compare semantic defaults against the retained view choices, not missing
  // localStorage strings against serialized defaults. Persisting a server value
  // does not mean an already mounted editor/sidebar has applied that layout.
  const deferred=Object.fromEntries(Object.entries(content.ui).filter(([field,value])=>field!=='backgroundQuality' && activeLayout?.[field as keyof typeof content.ui]!==value));
  const layoutChanged=Object.keys(deferred).length>0;
  applyBackupClientPreferences(incoming,localStorage);
  liveLayout.clear();
  Object.assign(homeSettings,content.home);if(!nonAppearance)hydrateAppearance(content.appearance,content.customAppearance??null);quality.value=content.ui.backgroundQuality;
  if(nonAppearance)retainAccountCustom(content.customAppearance);
  if(appearanceError.value)throw Error(appearanceError.value);
  return {reloadRequired:layoutChanged,reloadKey:JSON.stringify(deferred)};
}
const state=reactive({phase:'idle' as PreferencePhase,message:'',revision:null as number|null,reloadRequired:false,reloadDismissed:false,
  restoreWaiting:false,restoreJobId:null as string|null,restorePreviousJobId:null as string|null});
type Controller=ReturnType<typeof createClientPreferenceController>;
let controller:Controller|undefined, subscribers=0;
function active(){if(!controller)throw Error('账号偏好同步尚未启动，请重新登录后重试');return controller;}
export const clientPreferenceSync={
  state,
  ensureConfirmed:()=>active().ensureConfirmed(),
  retry:()=>active().retry(),
  useLocal:()=>active().useLocal(),
  useLocalAppearance:()=>active().useLocalAppearance(),
  useServer:()=>active().useServer(),
  dismissReload:()=>active().dismissReload(),
  beginRestore:(jobId:string|null=null,previousJobId:string|null=null)=>active().beginRestore(jobId,previousJobId),
  refreshAfterRestore:()=>active().refreshAfterRestore(),
};
/** Called once from App; no page polling, no backup creation and no storage monkeypatch. */
export function startClientPreferenceSync(){
  subscribers++;
  let released=false;
  const unsubscribe=()=>{if(!released){released=true;release();}};
  if(controller)return unsubscribe;
  // This is only the mounted layout comparison, never a seed/write fallback.
  // An unreadable/invalid snapshot stays unknown; strict capture below still
  // reports it through the controller's error state and refuses confirmation.
  try{activeLayout={...captureUi()};}catch{activeLayout=undefined;}
  let previousOwner=auth.me?.id;
  // These are unsent local inputs, not old request results. Preserve only the same
  // owner's choices across reauthentication; a different owner discards the map.
  const stopChoiceSession=watch(()=>JSON.stringify([auth.me?.id,auth.sessionGeneration,auth.requestEpoch]),()=>{
    const owner=auth.me?.id;
    if(owner!==previousOwner){liveLayout.clear();cancelAppearanceEdit();}
    else for(const choice of liveLayout.values())if(choice.owner===owner){choice.generation=auth.sessionGeneration;choice.epoch=auth.requestEpoch;}
    previousOwner=owner;
  },{flush:'sync'});
  controller=createClientPreferenceController({
    session:()=>({owner:auth.me?.id,generation:auth.sessionGeneration,epoch:auth.requestEpoch,blocked:auth.suspended || auth.sessionClosing}),
    capture,apply,applyNonAppearance:content=>apply(content,true),read:getClientPreferences,write:putClientPreferences,isEditing:()=>appearanceEditing.value,
    hasUnconfirmed:()=>appearanceUnconfirmed.value,
    onConfirmed:content=>confirmAppearance(content.appearance,content.customAppearance??null),
    canSeed:owner=>{const previous=localStorage.getItem(CLIENT_PREFERENCE_OWNER_KEY);return previous===null || previous===owner;},
    bindOwner:owner=>{localStorage.setItem(CLIENT_PREFERENCE_OWNER_KEY,owner);if(localStorage.getItem(CLIENT_PREFERENCE_OWNER_KEY)!==owner)throw Error('无法确认本机偏好的账号归属，请检查浏览器存储后重试');boundOwner=owner;},
  });
  const stopState=watch(controller.state,value=>Object.assign(state,value),{immediate:true,flush:'sync'});
  // Synchronous controls/watchers must not leak capture errors into Vue/App.
  // Retain strict capture and the original input; no fallback can reach write.
  const changed=(updateLayout?:()=>void)=>{
    try{updateLayout?.();controller?.changed();}
    catch(reason){if(controller){controller.state.phase='error';controller.state.message=reason instanceof Error?reason.message:'账号偏好同步失败，本机输入已保留';}}
  };
  const stopSettings=watch(()=>[homeSettings,appearancePreference.value,quality.value],()=>changed(),{deep:true,flush:'sync'});
  const stopSignals=onClientPreferenceChange((key,value)=>changed(()=>{
    if(Object.values(UI_LOCAL_KEYS).includes(key as never)){
      if(value!==undefined)liveLayout.set(key,{owner:auth.me?.id,generation:auth.sessionGeneration,epoch:auth.requestEpoch,value});
      const field=Object.entries(UI_LOCAL_KEYS).find(([,localKey])=>localKey===key)?.[0] as keyof ClientPreferenceContent['ui'];
      if(activeLayout)Object.assign(activeLayout,{[field]:capture().ui[field]});
    }
  }));
  dispose=()=>{stopState();stopSettings();stopSignals();stopChoiceSession();controller?.stop();controller=undefined;boundOwner=undefined;activeLayout=undefined;liveLayout.clear();Object.assign(state,{phase:'idle',message:'',revision:null,reloadRequired:false,reloadDismissed:false,restoreWaiting:false,restoreJobId:null,restorePreviousJobId:null});};
  return unsubscribe;
}
let dispose=()=>{};
function release(){if(subscribers>0 && --subscribers===0)dispose();}
