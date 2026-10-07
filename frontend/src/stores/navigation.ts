import { computed, reactive } from 'vue';
import { api } from '../api/client';
export interface WebsiteConnection {transport:'auto'|'proxy'|'direct';auth_mode:'original'|'header'|'oidc';header_name:string;injection_delivery:'proxy'|'loader';has_token?:boolean}
export interface RequestPolicy {management_prefixes:string[];read_post_paths:string[];protect_other_writes:boolean}
export interface Website { template_id?:'openlist'|'immich'|null;connection?:WebsiteConnection;background?:'solid'|'home';request_policy?:RequestPolicy; id:string; name:string; icon:string; mode:'iframe'|'link'|'openlist'|'isolated_proxy'; adapter:'generic'|'openlist'|'immich'; browser_url:string; enabled:boolean; keep_alive?:boolean; target_id?:string|null; initial_path?:string; origin?:string; capabilities?:{injection:boolean}; injection?:{draft:Injection|null;active:Injection|null;previous:Injection|null} }
export interface Injection { enabled:boolean; css:string; js:string; timing:'dom_ready'|'document_start'; csp_policy:'reject'|'controlled'; version?:string }
export interface NavEntry { id:string; title?:string; icon?:string; visible?:boolean }
export interface NavRow { id:string;label:string;icon:string;visible:boolean;to:string;builtin:boolean;kind?:'page'|'website' }
export const builtinNavigation:NavRow[] = [
  {id:'home',label:'个人主页',icon:'home',to:'/',visible:true,builtin:true},
  {id:'notes',label:'笔记',icon:'note',to:'/notes',visible:true,builtin:true},
  {id:'status',label:'服务器',icon:'server',to:'/status',visible:true,builtin:true},
  {id:'settings',label:'设置',icon:'settings',to:'/settings',visible:true,builtin:true},
];
export const navigationIcons = ['home','note','image','drive','server','settings','globe','link','book','folder','terminal','star','activity','box'];
// Display-only compatibility keys; do not expand the new-website picker allowlist.
export const legacyNavigationIcons = ['file-text','hard-drive','cloud','code','external-link','monitor','music','video','database','grid','heart','calendar','bookmark','layers','cpu','search'];
export function resolveNavigation(config:{entries:NavEntry[]}, modules:Website[]):NavRow[] {
  const defaults = [...builtinNavigation, ...modules.map(m=>({id:m.id,label:m.name,icon:m.icon,to:`/apps/${m.id}`,visible:m.enabled !== false,builtin:false}))];
  const result:NavRow[] = []; const seen = new Set<string>();
  for (const entry of [...config.entries, ...defaults]) {
    if (seen.has(entry.id)) continue;
    const original = defaults.find(row=>row.id===entry.id); if (!original) continue;
    seen.add(entry.id);
    result.push({...original,kind:original.builtin?'page':'website',label:('title' in entry && entry.title) || original.label, icon:entry.icon && [...navigationIcons,...legacyNavigationIcons].includes(entry.icon) ? entry.icon : original.icon,visible:entry.visible ?? original.visible});
  }
  return result;
}
export const navigation = reactive({entries:[] as NavEntry[], modules:[] as Website[],legacy_routes:{} as Record<string,string>,loaded:false,error:''});
export const navigationRows = computed(()=>resolveNavigation({entries:navigation.entries},navigation.modules));
export function isNavigationActive(path:string,to:string) { return path===to || to!=='/' && path.startsWith(to+'/'); }
let generation = 0;
export function resetNavigation() { generation++; navigation.entries=[]; navigation.modules=[]; navigation.legacy_routes={}; navigation.loaded=false; navigation.error=''; }
export async function loadNavigation() {
  const current = ++generation;
  try {
    const [config, modules] = await Promise.all([api<{entries:NavEntry[];legacy_routes?:Record<string,string>}>('/navigation'), api<Website[]>('/external-modules')]);
    if (current !== generation) return false;
    navigation.legacy_routes=config.legacy_routes||{}; navigation.entries=config.entries; navigation.modules=modules; navigation.loaded=true; navigation.error=''; return true;
  } catch { if (current===generation) navigation.error='导航配置加载失败，请重试'; return false; }
}
export async function saveNavigation(rows:NavRow[],reset=false) {
  await api('/navigation',{method:'PUT',body:JSON.stringify({entries:rows.map(row=>{
    if(row.builtin)return {id:row.id,title:row.label,icon:row.icon,visible:row.visible};
    // Keep effective legacy overrides until a full website save migrates both sources.
    const module=navigation.modules.find(item=>item.id===row.id);
    return {id:row.id,visible:row.visible,...(module&&row.label!==module.name?{title:row.label}:{}),...(module&&row.icon!==module.icon?{icon:row.icon}:{})};
  }),reset})});
  if (!await loadNavigation()) throw new Error('Navigation readback failed');
}

export function resolveLegacyModule(alias:string){const id=navigation.legacy_routes[alias];return id&&navigation.modules.some(item=>item.id===id)?id:null;}
