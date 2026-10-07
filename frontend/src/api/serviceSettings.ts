import {api} from './client';
import type {BuiltinSite, BuiltinVersion} from './builtinInjection';
export type ServiceSite = BuiltinSite;
export interface CustomCode {enabled:boolean;css:string;js:string;timing:'dom_ready'|'document_start';csp_policy:'reject'}
export interface DriveConnection {service_url:string;auth_mode:'manual'|'token';has_token:boolean}
export interface GalleryConnection {browser_url:string;upstream_url:string;alternate_browser_url:string;auth_mode:'manual'|'oidc'}
export interface ServiceSettings {
 site:ServiceSite;name:string;icon:string;visible:boolean;
 connection:DriveConnection|GalleryConnection;
 appearance:{theme?:'stella'|'original';simplified?:boolean;logo?:'stella'|'original'};
 injection:{draft:CustomCode|null;active:BuiltinVersion;previous:BuiltinVersion|null};
 capabilities:{background:boolean;oidc:boolean};
 scopes:{appearance:'embedded'|'domain';background:'device'|null};
 oidc:null|{client_registered:boolean;issuer:string;client_id:string;redirect_uris:string[]};
 compatibility:string[];
}
export interface ServicePayload {
 name:string;icon:string;visible:boolean;
 connection:(Omit<DriveConnection,'has_token'> & {token:string|null;clear_token:boolean})|GalleryConnection;
 appearance:ServiceSettings['appearance'];custom?:CustomCode;
}
export const putServiceSettings=(site:ServiceSite,payload:ServicePayload)=>api<ServiceSettings>(`/service-settings/${site}`,{method:'PUT',body:JSON.stringify(payload)});
export function matchesService(read:ServiceSettings,payload:ServicePayload) {
 if(read.name!==payload.name||read.icon!==payload.icon||read.visible!==payload.visible)return false;
 if(Object.entries(payload.appearance).some(([k,v])=>(read.appearance as Record<string,unknown>)[k]!==v))return false;
 for(const [k,v] of Object.entries(payload.connection)){
  if(k==='token'||k==='clear_token')continue;
  const actual=(read.connection as unknown as Record<string,unknown>)[k];
  // The backend accepts URLs with trailing slashes and persists rstrip('/').
  // Match only that documented canonicalization, never a different target.
  if(['service_url','browser_url','upstream_url','alternate_browser_url'].includes(k)&&typeof v==='string'&&typeof actual==='string'){
   if(actual!==v.replace(/\/+$/,''))return false;
  }else if(actual!==v)return false;
 }
 if('clear_token' in payload.connection){
  const stored=(read.connection as DriveConnection).has_token;
  if(payload.connection.clear_token&&stored)return false;
  if(payload.connection.token&&!stored)return false;
 }
 if(payload.custom&&Object.entries(payload.custom).some(([k,v])=>(read.injection.active as unknown as Record<string,unknown>)[k]!==v))return false;
 return true;
}
export const checkServiceSettings=(site:ServiceSite,connection:ServicePayload['connection'])=>api<{ok:boolean;message?:string;warning?:string}>(`/service-settings/${site}/check`,{method:'POST',body:JSON.stringify({connection})});
export const getServiceSettings=(site:ServiceSite)=>api<ServiceSettings>(`/service-settings/${site}`);
