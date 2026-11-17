// Pure portability boundary; clientPreferenceSync owns HTTP and live-store application.
import {validateCustomAppearance} from '../../stores/appearancePalette';
export const CLIENT_PREFERENCE_KEYS = Object.freeze([
  'stella_appearance', 'stella_custom_appearance', 'stella_home_theme', 'stella_home_particles', 'stella_home_bg',
  'stella_home_bgcrop', 'stella_site_title', 'stella_signature', 'stella_meet_date',
  'stella_live2d', 'stella_avatar', 'stella_home_bg_quality', 'stella_sidebar_fold',
  'stella_servers_fold', 'stella_tools_open', 'stella_server_world_map_collapsed',
  'stella_mon_mode', 'stella_note_edit_mode', 'stella_list_fold', 'stella_drive_bg_mode',
] as const);
export type ClientPreferenceKey = typeof CLIENT_PREFERENCE_KEYS[number];
export interface BackupClientPreferences {version:1; values:Partial<Record<ClientPreferenceKey,string>>}
export type PreferenceStorage = Pick<Storage,'getItem'|'setItem'|'removeItem'>;
const oneOf = (...values:string[]) => (value:string) => values.includes(value);
const text = (limit:number) => (value:string) => [...value].length<=limit && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
function crop(value:string){
  if(value.length>256)return false;
  try{
    const data:unknown=JSON.parse(value);
    if(!data || typeof data!=='object' || Array.isArray(data))return false;
    const fields=data as Record<string,unknown>;
    return Object.keys(fields).length===4 && ['cx','cy','w','h'].every(key=>typeof fields[key]==='number' && Number.isFinite(fields[key]) && (fields[key] as number)>=0 && (fields[key] as number)<=1) && (fields.w as number)>0 && (fields.h as number)>0;
  }catch{return false;}
}
function localBackground(value:string){return value==='' || value.length<=220 && /^\/assets\/homebg\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value) && !value.includes('..');}
function localAvatar(value:string){return value==='' || value==='/avatar.png' || value.length<=220 && /^\/assets\/avatars\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value) && !value.includes('..');}
function date(value:string){return /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith('0000-') && Number.isFinite(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}
const validators:Record<ClientPreferenceKey,(value:string)=>boolean> = {
  stella_appearance:oneOf('A','B','custom'),
  stella_custom_appearance:value=>{try{if(value.length>4096)return false;const parsed=JSON.parse(value);if(parsed!==null)validateCustomAppearance(parsed);return true;}catch{return false;}},
  stella_home_theme:oneOf('daybreak','nightfall','classic'),
  stella_home_particles:oneOf('stars','motes','sakura','off'), stella_home_bg:localBackground,
  stella_home_bgcrop:crop, stella_site_title:text(120), stella_signature:text(512), stella_meet_date:date,
  stella_live2d:oneOf('on','off'), stella_avatar:localAvatar,
  stella_home_bg_quality:oneOf('original','compressed1','compressed2'), stella_sidebar_fold:oneOf('0','1'),
  stella_servers_fold:oneOf('0','1'), stella_tools_open:oneOf('0','1'), stella_server_world_map_collapsed:oneOf('0','1'),
  stella_mon_mode:oneOf('chart','simple'), stella_note_edit_mode:oneOf('rich','markdown'),
  stella_list_fold:oneOf('0','1'), stella_drive_bg_mode:oneOf('solid','image'),
};
export function readBackupClientPreferences(storage:Pick<PreferenceStorage,'getItem'>):{preferences:BackupClientPreferences;warnings:ClientPreferenceKey[]} {
  const values:BackupClientPreferences['values']={},warnings:ClientPreferenceKey[]=[];
  for(const key of CLIENT_PREFERENCE_KEYS){
    try{const value=storage.getItem(key);if(value===null)continue;if(validators[key](value))values[key]=value;else warnings.push(key);}
    catch{warnings.push(key);}
  }
  return {preferences:{version:1,values},warnings};
}
function plain(value:unknown):value is Record<string,unknown>{return !!value && typeof value==='object' && !Array.isArray(value) && [Object.prototype,null].includes(Object.getPrototypeOf(value));}
export function validateBackupClientPreferences(input:unknown):BackupClientPreferences {
  if(!plain(input) || Object.keys(input).sort().join(',')!=='values,version' || input.version!==1 || !plain(input.values))throw Error('本机偏好格式或版本不受支持');
  const values:BackupClientPreferences['values']={};let total=0;
  for(const [raw,value] of Object.entries(input.values)){
    if(!Object.prototype.hasOwnProperty.call(validators,raw) || typeof value!=='string' || !validators[raw as ClientPreferenceKey](value))throw Error('本机偏好含未允许的字段或无效值');
    total+=raw.length+value.length;if(total>8192)throw Error('本机偏好超过长度上限');values[raw as ClientPreferenceKey]=value;
  }
  if(values.stella_appearance==='custom' && (!values.stella_custom_appearance || values.stella_custom_appearance==='null'))throw Error('本机偏好自定义配色缺少基底');
  return {version:1,values};
}
export class ClientPreferenceApplyError extends Error {
  readonly rollbackComplete:boolean;
  constructor(rollbackComplete:boolean){super(rollbackComplete?'本机偏好应用失败，已回滚；请检查浏览器存储后重试。':'本机偏好应用失败，部分回滚未能确认；请检查浏览器存储，不要宣称恢复完成。');this.rollbackComplete=rollbackComplete;}
}
/** Apply only a validated owner-scoped server readback (hydration or confirmed restore).
 * The controller must fence sessions/newer edits and suppress upload echoes.
 * Absent keys are unchanged; secrets, notes and dynamic record IDs are never touched.
 */
export function applyBackupClientPreferences(input:unknown,storage:PreferenceStorage):{applied:ClientPreferenceKey[];reloadRequired:true} {
  const validated=validateBackupClientPreferences(input), keys=CLIENT_PREFERENCE_KEYS.filter(key=>Object.hasOwn(validated.values,key));
  const old=new Map<ClientPreferenceKey,string|null>();
  // All reads must succeed before any write; never clear the complete origin.
  for(const key of keys)old.set(key,storage.getItem(key));
  try{
    for(const key of keys){const value=validated.values[key]!;storage.setItem(key,value);if(storage.getItem(key)!==value)throw Error('readback mismatch');}
  }catch{
    let rollbackComplete=true;
    for(const key of keys){try{const value=old.get(key)!;if(value===null)storage.removeItem(key);else storage.setItem(key,value);if(storage.getItem(key)!==value)rollbackComplete=false;}catch{rollbackComplete=false;}}
    throw new ClientPreferenceApplyError(rollbackComplete);
  }
  return {applied:[...keys],reloadRequired:true};
}
