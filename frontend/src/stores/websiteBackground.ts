import { navigation, type Website } from './navigation';
import { ref } from 'vue';
import { auth } from '../modules/home/auth';
export type WebsiteBackground='solid'|'home';
const legacyKeys=['stella_drive_bg_mode','__stella_drive_bg_mode__'];
const preferenceVersion=ref(0),memoryExplicit=new Set<string>();
const explicitKey=(id:string)=>`stella_website_background_explicit:${auth.me?.id||'guest'}:${id}`;
// Compatibility is a local read, never a server migration or template-specific host.
export function effectiveWebsiteBackground(item:Website|null):{mode:WebsiteBackground;legacy:boolean} {
 void preferenceVersion.value;
 if(item&&navigation.legacy_routes.drive===item.id){
  const key=explicitKey(item.id);
  try { if(!memoryExplicit.has(key)&&localStorage.getItem(key)!=='1')for(const legacy of legacyKeys){const value=localStorage.getItem(legacy);if(value==='image'||value==='solid')return {mode:value==='image'?'home':'solid',legacy:true};} } catch { /* Storage can be unavailable; use the record. */ }
 }
 return {mode:item?.background==='home'?'home':'solid',legacy:false};
}
// Only call after a deliberate website-level selection has been saved and read back.
// No background field is published by merely opening the editor or editing metadata.
export function confirmWebsiteBackground(item:Website){
 if(navigation.legacy_routes.drive!==item.id)return;
 const key=explicitKey(item.id);
 try { localStorage.setItem(key,'1'); } catch { memoryExplicit.add(key); }
 for(const legacy of legacyKeys)try { localStorage.removeItem(legacy); } catch { /* The explicit marker still wins. */ }
 preferenceVersion.value++;
}
