import {api} from './client';
import type {Website,Injection} from '../stores/navigation';
export type {Website,Injection};
export interface WebsiteInput {name:string;icon:string;mode:Website['mode'];adapter:Website['adapter'];browser_url:string;target_id:string|null;initial_path:string;enabled:boolean;keep_alive?:boolean}
export interface Launch {mode:Website['mode'];url:string;method:'GET'|'POST';fields?:Record<string,string>;expires_in?:number}
export interface Target {id:string;name:string;upstream_url:string;controlled:boolean;allowed_ips?:string[]}
const endpoint=(id:string)=>`/external-modules/${encodeURIComponent(id)}`;
export const getWebsite=(id:string,signal?:AbortSignal)=>api<Website>(endpoint(id),{signal});
export const createWebsite=(input:WebsiteInput)=>api<Website>('/external-modules',{method:'POST',body:JSON.stringify(input)});
export const updateWebsite=(id:string,input:WebsiteInput)=>api<Website>(endpoint(id),{method:'PATCH',body:JSON.stringify(input)});
export const deleteWebsite=(id:string)=>api<void>(endpoint(id),{method:'DELETE'});
export const launchWebsite=(id:string,signal?:AbortSignal)=>api<Launch>(endpoint(id)+'/launch',{method:'POST',signal});
export const checkWebsite=(id:string)=>api<{reason:string;browser_status:string;ready:boolean}>(endpoint(id)+'/check',{method:'POST'});
export const validateInjection=(id:string,input:Injection)=>api<{valid:boolean;errors:string[];draft:Injection}>(endpoint(id)+'/injection/validate',{method:'POST',body:JSON.stringify({enabled:input.enabled,css:input.css,js:input.js,timing:input.timing,csp_policy:input.csp_policy})});
export const applyInjection=(id:string)=>api(endpoint(id)+'/injection/apply',{method:'POST'});
export const rollbackInjection=(id:string)=>api(endpoint(id)+'/injection/rollback',{method:'POST'});
export const getPresets=()=>api<Record<string,{css:string;js:string;readonly:boolean;status:string}>>('/integration-presets');
export const getTargets=()=>api<Target[]>('/integration-targets');
export interface TargetInput {name:string;upstream_url:string;allowed_ips:string[];controlled:boolean;headers:Record<string,string>}
export interface ResolvedTarget {normalized_origin:string;resolved_ips:string[];status:'resolved';private_addresses:boolean}
export const resolveTarget=(upstream_url:string,allow_private=false)=>api<ResolvedTarget>('/integration-targets/resolve',{method:'POST',body:JSON.stringify({upstream_url,allow_private})});
export const createTarget=(input:TargetInput)=>api<Target>('/integration-targets',{method:'POST',body:JSON.stringify(input)});
export function splitProxyUrl(value:string) {
 if(/[\s\\\\\u0000-\u001f\u007f]/.test(value))throw new Error('不合法的网站 URL');
 let parsed:URL;try{parsed=new URL(value);}catch{throw new Error('请填写完整 http/https URL');}
 if(!['http:','https:'].includes(parsed.protocol)||parsed.username||parsed.password||/^[^:]+:\/\/[^/?#]*@/.test(value))throw new Error('仅支持无账号密码的 http/https URL');
 return {origin:parsed.origin,initial_path:parsed.pathname+parsed.search+parsed.hash};
}
export function websiteError(error:unknown) { const e=error as {status?:number;detail?:unknown}; return e.status===403?'管理操作未获授权':e.status===404?'网站入口不存在或已删除':typeof e.detail==='string'?e.detail:'请求未完成，请检查配置后重试'; }
