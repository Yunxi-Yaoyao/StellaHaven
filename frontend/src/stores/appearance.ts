// Stella colors only. Home composition/media and external sites are independent.
import {computed,ref,shallowRef} from 'vue';
import {resolvePalette,validateCustomAppearance,presetPalettes,type Appearance,type CustomAppearance,type PaletteToken} from './appearancePalette';
export type {Appearance} from './appearancePalette';
export const appearanceError=ref('');
function loadUnconfirmed(){try{return localStorage.getItem('stella_appearance_unconfirmed')==='1';}catch{return false;}}
// Device-only unsent marker: never part of account DTO or backup keys.
export const appearanceUnconfirmed=ref(loadUnconfirmed());
function load(){
 try{const raw=localStorage.getItem('stella_custom_appearance');const custom=raw && raw!=='null'?validateCustomAppearance(JSON.parse(raw)):null;
 const value=localStorage.getItem('stella_appearance');return {appearance:(value==='B'?'B':value==='custom' && custom?'custom':'A') as Appearance,custom};
 }catch{appearanceError.value='无法读取本机外观设置，已使用默认 A。';return {appearance:'A' as Appearance,custom:null};}
}
const initial=load();
export const appearance=ref<Appearance>(initial.appearance);
export const customAppearance=ref<CustomAppearance|null>(initial.custom);
export const appearanceEditing=ref(false);
export const appearancePreference=shallowRef({appearance:initial.appearance,customAppearance:initial.custom});
export const resolvedPalette=computed(()=>resolvePalette(appearance.value,customAppearance.value));
export const hasAppearancePreview=computed(()=>JSON.stringify({appearance:appearance.value,customAppearance:customAppearance.value})!==JSON.stringify(appearancePreference.value));
// Legacy chart interface remains real hex, not CSS var() passed to canvas.
function legacy(p:ReturnType<typeof resolvePalette>){return {accent:p.accent,select:p['selected-bg'],border:p['selected-border'],top:p['button-top'],bottom:p['button-bottom'],buttonBorder:p['button-border'],warm:p.warm,cpu:p['metric-cpu'],memory:p['metric-memory'],disk:p['metric-disk'],cpuStart:p['metric-cpu-start'],memoryStart:p['metric-memory-start'],diskStart:p['metric-disk-start']};}
export const palettes={A:legacy(presetPalettes.A),B:legacy(presetPalettes.B)};
export const metricColors=computed(()=>legacy(resolvedPalette.value));
type Snapshot={appearance:Appearance;custom:CustomAppearance|null};
const snapshot=():Snapshot=>({appearance:appearance.value,custom:customAppearance.value?validateCustomAppearance(customAppearance.value):null});
let editing:Snapshot|null=null,undo:Snapshot[]=[];
function apply(){
 if(typeof document==='undefined')return;
 document.documentElement.dataset.appearance=appearance.value;
 for(const [key,value] of Object.entries(resolvedPalette.value))document.documentElement.style.setProperty(`--${key}`,value);
}
function persist(markDirty=true){
 const current=snapshot();
 if(markDirty && JSON.stringify({appearance:current.appearance,customAppearance:current.custom})!==JSON.stringify(appearancePreference.value))appearanceUnconfirmed.value=true;
 try{
  if(appearanceUnconfirmed.value)localStorage.setItem('stella_appearance_unconfirmed','1');
  const serialized=JSON.stringify(current.custom);
  localStorage.setItem('stella_custom_appearance',serialized);localStorage.setItem('stella_appearance',current.appearance);
  if(localStorage.getItem('stella_appearance')!==current.appearance || localStorage.getItem('stella_custom_appearance')!==serialized)throw Error('readback mismatch');
  appearanceError.value='';
 }catch{appearanceError.value='外观未保存到当前设备，当前选择仍有效；请检查浏览器存储后重试。';}
 appearancePreference.value={appearance:current.appearance,customAppearance:current.custom};
}
function restore(s:Snapshot){appearance.value=s.appearance;customAppearance.value=s.custom;apply();}
export function setAppearance(value:Appearance){
 if(!['A','B','custom'].includes(value) || value==='custom' && !customAppearance.value)return;
 cancelAppearanceEdit();appearance.value=value;apply();persist();
}
export function hydrateAppearance(value:Appearance,custom:CustomAppearance|null){
 if(appearanceEditing.value)throw Error('正在调色，本机草稿已保留，请完成或取消后重试同步');
 const validated=custom?validateCustomAppearance(custom):null;
 if(value==='custom' && !validated)throw Error('自定义配色缺少基底');
 undo=[];restore({appearance:value,custom:validated});persist(false);confirmAppearance(value,validated);
}
/** Preserve an account's retained custom slot without changing the active preset. */
export function retainAccountCustom(custom:CustomAppearance|undefined){
 if(customAppearance.value || !custom)return;
 customAppearance.value=validateCustomAppearance(custom);persist(false);
}
export function confirmAppearance(value:Appearance,custom:CustomAppearance|null){
 const local=appearancePreference.value;
 if(value!==local.appearance || JSON.stringify(custom)!==JSON.stringify(local.customAppearance))return;
 appearanceUnconfirmed.value=false;
 try{localStorage.removeItem('stella_appearance_unconfirmed');}catch{appearanceError.value='账号已确认，但无法清除本机待同步标记；配色仍保留。';}
}
export function beginAppearanceEdit(){if(!editing){editing=snapshot();appearanceEditing.value=true;}}
export function setPaletteColor(token:PaletteToken,color:string,preview=false){
 const validated=validateCustomAppearance({version:1,base:'A',overrides:{[token]:color}});const normalized=validated.overrides[token]!;
 if(resolvedPalette.value[token]===normalized)return;
 const old=snapshot();
 const base=appearance.value==='custom'?customAppearance.value!.base:appearance.value;
 const overrides=appearance.value==='custom'?{...customAppearance.value!.overrides}:{};
 if(normalized===presetPalettes[base][token])delete overrides[token];else overrides[token]=normalized;
 customAppearance.value=validateCustomAppearance({version:1,base,overrides});appearance.value='custom';apply();
 // Every valid edit is durable immediately. The optional group flag only
 // coalesces undo history; it never gates storage or account synchronization.
 if(!preview || !editing)undo.push(old);
 persist();
}
export function finishAppearanceEdit(){
 if(!editing)return;const previous=editing;editing=null;appearanceEditing.value=false;
 if(JSON.stringify(previous)!==JSON.stringify(snapshot()))undo.push(previous);
}
// Closing/changing object is not an implicit rollback of already saved colors.
export function cancelAppearanceEdit(){finishAppearanceEdit();}
export function undoAppearance(){cancelAppearanceEdit();const previous=undo.pop();if(previous){restore(previous);persist();}}
export const canUndoAppearance=computed(()=>appearancePreference.value && undo.length>0);
export function resetPaletteToken(token:PaletteToken,preview=false){const base=appearance.value==='custom'?customAppearance.value!.base:appearance.value;setPaletteColor(token,presetPalettes[base][token],preview);}
export function restorePaletteBase(){cancelAppearanceEdit();const base=appearance.value==='custom'?customAppearance.value!.base:appearance.value;undo.push(snapshot());restore({appearance:base,custom:customAppearance.value?{version:1,base,overrides:{}}:null});persist();}
export function retryAppearancePersistence(){persist();}
window.addEventListener('storage',event=>{
 if(!['stella_appearance','stella_custom_appearance',null].includes(event.key))return;
 if(appearanceEditing.value){appearanceError.value='其他页面已更改外观，正在调色的本机草稿已保留。';return;}
 const next=load();restore({appearance:next.appearance,custom:next.custom});appearanceUnconfirmed.value=loadUnconfirmed();appearancePreference.value={appearance:next.appearance,customAppearance:next.custom};
});
apply();
