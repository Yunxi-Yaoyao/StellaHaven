import {clientPreferencesToLocal,defaultClientPreferences,localToClientPreferences,validateClientPreferences,type ClientPreferences} from '../../src/modules/settings/clientPreferenceContract';
import {readBackupClientPreferences} from '../../src/modules/settings/backupClientPreferences';

const ENDPOINT='/operations/backups/client-preferences';
type Options={storage?:Record<string,string>;allowWrite?:boolean;revision?:number};
/** One fixed authenticated owner's pre-existing preferences, isolated per context.
 * Match the real device defaults, not an empty DTO that would enable Live2D or
 * overwrite an explicit quality/background choice. Never dump arbitrary storage.
 */
export function createClientPreferencesFixture({storage={},allowWrite=false,revision=1}:Options={}){
 const defaults=defaultClientPreferences();
 defaults.home.bgImage='/assets/homebg/default-bg-kimono-1920.webp';
 defaults.home.signature='夜有星辰，晨有曦光。';
 const {preferences}=readBackupClientPreferences({getItem:key=>storage[key]??null});
 const values={...clientPreferencesToLocal(defaults).values,...preferences.values};
 // A server seed may retain a valid legacy device choice; leave the raw invalid
 // or absent current key untouched in the browser compatibility regression.
 if(!['solid','image'].includes(storage.stella_drive_bg_mode??'') && ['solid','image'].includes(storage.__stella_drive_bg_mode__??''))values.stella_drive_bg_mode=storage.__stella_drive_bg_mode__;
 let saved:ClientPreferences=validateClientPreferences(localToClientPreferences({version:1,values},revision));
 const response=(status:number,json:unknown)=>({status,json:structuredClone(json)});
 return {respond(method:string,path:string,body?:unknown):{status:number;json:any}|null{
  if(path!==ENDPOINT)return null;
  if(method==='GET')return response(200,saved);
  if(method!=='PUT'||!allowWrite)return null;
  try{
   if(!body||typeof body!=='object'||Array.isArray(body)||Object.keys(body).sort().join(',')!==(Object.hasOwn(body,'customAppearance')?'appearance,customAppearance,expected_revision,home,ui':'appearance,expected_revision,home,ui'))throw Error('exact write DTO required');
   const {expected_revision,...content}=body as Record<string,unknown>;
   if(typeof expected_revision!=='number'||!Number.isSafeInteger(expected_revision)||expected_revision<0)throw Error('invalid revision');
   const candidate=validateClientPreferences({...content,...(!Object.hasOwn(body,'customAppearance') && saved.customAppearance?{customAppearance:saved.customAppearance}:{}),revision:saved.revision+1});
   if(expected_revision!==saved.revision)return response(409,{detail:'client preference revision changed'});
   saved=candidate;return response(200,saved);
  }catch{return response(422,{detail:'Invalid client preference fixture DTO'});}
 }};
}
