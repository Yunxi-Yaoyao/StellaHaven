import {CLIENT_PREFERENCE_KEYS,validateBackupClientPreferences,type BackupClientPreferences,type ClientPreferenceKey} from './backupClientPreferences';
import {validateCustomAppearance,type Appearance,type CustomAppearance} from '../../stores/appearancePalette';

export interface ClientPreferenceContent {
  appearance:Appearance;
  customAppearance?:CustomAppearance;
  home:{theme:'daybreak'|'nightfall'|'classic';particles:'stars'|'motes'|'sakura'|'off';bgImage:string;bgCrop:{cx:number;cy:number;w:number;h:number};siteTitle:string;signature:string;meetDate:string;live2d:boolean;avatar:string};
  ui:{backgroundQuality:'original'|'compressed1'|'compressed2';sidebarFold:boolean;serversFold:boolean;toolsOpen:boolean;worldMapCollapsed:boolean;monitorMode:'chart'|'simple';noteEditMode:'rich'|'markdown';listFold:boolean;driveBackground:'solid'|'image'};
}
export interface ClientPreferences extends ClientPreferenceContent {revision:number}
export type ClientPreferencesWrite = ClientPreferenceContent & {expected_revision:number};
export const HOME_LOCAL_KEYS={theme:'stella_home_theme',particles:'stella_home_particles',bgImage:'stella_home_bg',bgCrop:'stella_home_bgcrop',siteTitle:'stella_site_title',signature:'stella_signature',meetDate:'stella_meet_date',live2d:'stella_live2d',avatar:'stella_avatar'} as const;
export const UI_LOCAL_KEYS={backgroundQuality:'stella_home_bg_quality',sidebarFold:'stella_sidebar_fold',serversFold:'stella_servers_fold',toolsOpen:'stella_tools_open',worldMapCollapsed:'stella_server_world_map_collapsed',monitorMode:'stella_mon_mode',noteEditMode:'stella_note_edit_mode',listFold:'stella_list_fold',driveBackground:'stella_drive_bg_mode'} as const;
export function defaultClientPreferences():ClientPreferences {
  return {revision:0,appearance:'A',home:{theme:'daybreak',particles:'stars',bgImage:'',bgCrop:{cx:.5,cy:.5,w:1,h:1},siteTitle:'StellaHaven',signature:'',meetDate:'2026-05-31',live2d:true,avatar:'/avatar.png'},ui:{backgroundQuality:'compressed1',sidebarFold:false,serversFold:false,toolsOpen:false,worldMapCollapsed:false,monitorMode:'chart',noteEditMode:'rich',listFold:false,driveBackground:'solid'}};
}
const fail=():never=>{throw Error('账号偏好含未允许的字段或无效值');};
function object(input:unknown,keys:string[]):Record<string,unknown>{
  if(!input || typeof input!=='object' || Array.isArray(input) || ![Object.prototype,null].includes(Object.getPrototypeOf(input)) || Object.keys(input).sort().join(',')!==[...keys].sort().join(','))return fail();
  return input as Record<string,unknown>;
}
export function clientPreferencesToLocal(input:unknown):BackupClientPreferences {
  const hasCustom=!!input && typeof input==='object' && Object.hasOwn(input,'customAppearance');
  const root=object(input,['revision','appearance','home','ui',...(hasCustom?['customAppearance']:[])]);
  const custom=root.customAppearance===undefined || root.customAppearance===null?null:validateCustomAppearance(root.customAppearance);
  if(root.appearance==='custom' && !custom)return fail();
  if(typeof root.revision!=='number' || !Number.isSafeInteger(root.revision) || root.revision<0)return fail();
  const home=object(root.home,Object.keys(HOME_LOCAL_KEYS)),ui=object(root.ui,Object.keys(UI_LOCAL_KEYS));
  const values:Partial<Record<ClientPreferenceKey,unknown>>={stella_appearance:root.appearance,stella_custom_appearance:JSON.stringify(custom)};
  for(const [field,key] of Object.entries(HOME_LOCAL_KEYS)){
    const value=home[field];
    if(field==='live2d'){if(typeof value!=='boolean')return fail();values[key]=value?'on':'off';}
    else if(field==='bgCrop')values[key]=JSON.stringify(value);
    else values[key]=value;
  }
  for(const [field,key] of Object.entries(UI_LOCAL_KEYS)){
    const value=ui[field];
    if(['sidebarFold','serversFold','toolsOpen','worldMapCollapsed','listFold'].includes(field)){
      if(typeof value!=='boolean')return fail();values[key]=value?'1':'0';
    }else values[key]=value;
  }
  // Preserve one canonical local key order as well as field validators.
  return validateBackupClientPreferences({version:1,values:Object.fromEntries(CLIENT_PREFERENCE_KEYS.map(key=>[key,values[key]]))});
}
export function localToClientPreferences(input:unknown,revision=0):ClientPreferences {
  const portable=validateBackupClientPreferences(input), base=defaultClientPreferences();
  const values={...clientPreferencesToLocal(base).values,...portable.values};
  const home=Object.fromEntries(Object.entries(HOME_LOCAL_KEYS).map(([field,key])=>[field,field==='bgCrop'?JSON.parse(values[key]!):field==='live2d'?values[key]==='on':values[key]]));
  const ui=Object.fromEntries(Object.entries(UI_LOCAL_KEYS).map(([field,key])=>[field,['sidebarFold','serversFold','toolsOpen','worldMapCollapsed','listFold'].includes(field)?values[key]==='1':values[key]]));
  const custom=JSON.parse(values.stella_custom_appearance || 'null');
  const result={revision,appearance:values.stella_appearance,...(custom?{customAppearance:validateCustomAppearance(custom)}:{}),home,ui};
  clientPreferencesToLocal(result);
  return result as ClientPreferences;
}
export function validateClientPreferences(input:unknown):ClientPreferences {
  const portable=clientPreferencesToLocal(input);
  return localToClientPreferences(portable,(input as ClientPreferences).revision);
}
export function preferenceContent(input:ClientPreferences):ClientPreferenceContent {const {revision:_,...content}=validateClientPreferences(input);return content;}
export const preferenceFingerprint=(value:ClientPreferenceContent)=>JSON.stringify(clientPreferencesToLocal({...value,revision:0}));
