import { computed, reactive } from 'vue';
import { api } from '../api/client';
export interface WebsiteConnection {transport:'auto'|'proxy'|'direct';auth_mode:'original'|'header'|'oidc';header_name:string;injection_delivery:'proxy'|'loader';has_token?:boolean}
export interface RequestPolicy {management_prefixes:string[];read_post_paths:string[];protect_other_writes:boolean}
export interface Website { /** Client-only token from this detail response, never a guessed global revision. */ read_revision?:number; address_mode?:'ip'|'domain'|null;alternate_address?:string|null;mapping_configured?:boolean; access_adapter?:'auto'|'generic'|'openlist'|'immich'; private_address?:string|null;entry_policy?:'follow'|'public'; template_id?:'openlist'|'immich'|`user_${string}`|null;connection?:WebsiteConnection;background?:'solid'|'home';request_policy?:RequestPolicy; id:string; name:string; icon:string; mode:'iframe'|'link'|'openlist'|'isolated_proxy'; adapter:'generic'|'openlist'|'immich'; browser_url:string; enabled:boolean; keep_alive?:boolean; target_id?:string|null; initial_path?:string; origin?:string; capabilities?:{injection:boolean}; injection?:{draft:Injection|null;active:Injection|null;previous:Injection|null} }
export interface Injection { enabled:boolean; css:string; js:string; timing:'dom_ready'|'document_start'; csp_policy:'reject'|'controlled'; version?:string }
// First-read DTO: never represents injection, credentials or editor policy.
export type WebsiteSummary = Pick<Website,'id'|'name'|'icon'|'mode'|'adapter'|'browser_url'|'enabled'|'keep_alive'|'template_id'|'background'> & {route?:string;runtime_revision?:string};
export interface NavigationSnapshot {entries:NavEntry[];modules:WebsiteSummary[];legacy_routes:Record<string,string>;revision:number;mutation_id:string|null}
export interface NavEntry { id:string; title?:string; icon?:string; visible?:boolean }
export interface NavRow { id:string;label:string;icon:string;visible:boolean;to:string;builtin:boolean;kind?:'page'|'website' }
export const builtinNavigation:NavRow[] = [
  {id:'home',label:'个人主页',icon:'home',to:'/',visible:true,builtin:true},
  {id:'nav',label:'导航',icon:'compass',to:'/nav',visible:true,builtin:true},
  {id:'notes',label:'笔记',icon:'note',to:'/notes',visible:true,builtin:true},
  {id:'status',label:'服务器',icon:'server',to:'/status',visible:true,builtin:true},
  {id:'settings',label:'设置',icon:'settings',to:'/settings',visible:true,builtin:true},
];
export { navigationIcons, legacyNavigationIcons } from '../icons/navigationIcons';
export function resolveNavigation(config:{entries:NavEntry[]}, modules:WebsiteSummary[]):NavRow[] {
  const defaults = [...builtinNavigation, ...modules.map(m=>({id:m.id,label:m.name,icon:m.icon,to:`/apps/${m.id}`,visible:m.enabled !== false,builtin:false}))];
  const result:NavRow[] = []; const seen = new Set<string>();
  for (const entry of [...config.entries, ...defaults]) {
    if (seen.has(entry.id)) continue;
    const original = defaults.find(row=>row.id===entry.id); if (!original) continue;
    seen.add(entry.id);
    result.push({...original,kind:original.builtin?'page':'website',label:('title' in entry && entry.title) || original.label, icon:entry.icon || original.icon,visible:entry.visible ?? original.visible});
  }
  return result;
}
export const navigation = reactive({entries:[] as NavEntry[], modules:[] as WebsiteSummary[],legacy_routes:{} as Record<string,string>,revision:0,loaded:false,error:''});
export const navigationRows = computed(()=>resolveNavigation({entries:navigation.entries},navigation.modules));
export function isNavigationActive(path:string,to:string) { return path===to || to!=='/' && path.startsWith(to+'/'); }
let generation = 0, sessionEpoch = 0;
let saving=false,unknown=false;
export function navigationEpoch(){return sessionEpoch;}
function validSnapshot(value:NavigationSnapshot){return !!value&&Number.isSafeInteger(value.revision)&&value.revision>=0&&Array.isArray(value.entries)&&Array.isArray(value.modules)&&value.entries.every(e=>typeof e.id==='string'&&typeof e.title==='string'&&typeof e.icon==='string'&&typeof e.visible==='boolean')&&value.modules.every(m=>typeof m.id==='string'&&typeof m.name==='string'&&typeof m.icon==='string'&&typeof m.enabled==='boolean')&&!!value.legacy_routes;}
function assignSnapshot(value:NavigationSnapshot){navigation.entries=value.entries;navigation.modules=value.modules;navigation.legacy_routes=value.legacy_routes;navigation.revision=value.revision;navigation.loaded=true;navigation.error='';}
export function mergeNavigationSnapshot(value:NavigationSnapshot,epoch:number){
  if(epoch!==sessionEpoch||!validSnapshot(value)||value.revision<navigation.revision)throw new Error('Navigation ACK not current');
  generation++;request?.abort();request=undefined;pending=undefined;assignSnapshot(value);
}
let pending:Promise<boolean>|undefined, request:AbortController|undefined;
export function resetNavigation() { sessionEpoch++; generation++;saving=false;unknown=false; request?.abort(); request=undefined; pending=undefined; navigation.entries=[]; navigation.modules=[]; navigation.legacy_routes={};navigation.revision=0; navigation.loaded=false; navigation.error=''; }
// Startup callers share a flight. Writes explicitly invalidate it; reset owns session isolation.
export function loadNavigation({force=false}:{force?:boolean}={}):Promise<boolean> {
  if(pending&&!force)return pending;
  if(navigation.loaded&&!force)return Promise.resolve(true);
  const current = ++generation;
  request?.abort();const controller=request=new AbortController();
  navigation.error='';
  const timeout=setTimeout(()=>controller.abort(),15000);
  const cancelled=new Promise<never>((_resolve,reject)=>controller.signal.addEventListener('abort',()=>reject(new Error('Navigation cancelled or timed out')),{once:true}));
  const task=(async()=>{
    try {
      const config = await Promise.race([cancelled,api<NavigationSnapshot>('/navigation',{signal:controller.signal})]);
      if (current !== generation) return false;
      if(!validSnapshot(config)||config.revision<navigation.revision)throw new Error('Invalid navigation snapshot');
      assignSnapshot(config);unknown=false;return true;
    } catch(e) { if (current===generation){if([401,403].includes((e as {status:number}).status))resetNavigation();else navigation.error='导航配置加载失败，请重试';} return false; }
    finally { clearTimeout(timeout);if(current===generation){pending=undefined;request=undefined;} }
  })();
  pending=task;return task;
}
export async function saveNavigation(rows:NavRow[],reset=false) {
  if(saving||unknown||!navigation.loaded)throw new Error('Navigation requires confirmed read before saving');
  const session=sessionEpoch;
  const mutation_id=crypto.randomUUID(),expected_revision=navigation.revision;
  saving=true;
  try{
  const ack=await api<NavigationSnapshot>('/navigation',{method:'PUT',body:JSON.stringify({expected_revision,mutation_id,entries:rows.map(row=>{
    if(row.builtin)return {id:row.id,title:row.label,icon:row.icon,visible:row.visible};
    // Keep effective legacy overrides until a full website save migrates both sources.
    const module=navigation.modules.find(item=>item.id===row.id);
    return {id:row.id,visible:row.visible,...(module&&row.label!==module.name?{title:row.label}:{}),...(module&&row.icon!==module.icon?{icon:row.icon}:{})};
  }),reset})});
  if(ack.mutation_id!==mutation_id||ack.revision<expected_revision)throw new Error('Navigation mutation ACK missing');
  mergeNavigationSnapshot(ack,session);
  }catch(e){if(session===sessionEpoch){const status=(e as {status?:number}).status;if(status===401||status===403)resetNavigation();else{unknown=!status||status>=500||status===408;navigation.error=unknown?'保存结果未知，请重新读取导航确认':'导航保存失败，请保留修改后重试';}}throw e;}
  finally{if(session===sessionEpoch)saving=false;}
}

export function resolveLegacyModule(alias:string){const id=navigation.legacy_routes[alias];return id&&navigation.modules.some(item=>item.id===id)?id:null;}
