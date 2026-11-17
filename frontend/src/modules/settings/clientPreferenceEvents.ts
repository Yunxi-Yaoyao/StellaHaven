// Narrow signals at original preference controls, never a Storage monkeypatch/dump.
import {CLIENT_PREFERENCE_KEYS,type ClientPreferenceKey} from './backupClientPreferences';
type Listener=(key:ClientPreferenceKey,value?:string)=>void;
const listeners=new Set<Listener>();
export function notifyClientPreferenceChange(key:ClientPreferenceKey,value?:string){
  if(CLIENT_PREFERENCE_KEYS.includes(key))for(const listener of listeners)listener(key,value);
}
export function onClientPreferenceChange(listener:Listener){listeners.add(listener);return ()=>listeners.delete(listener);}
