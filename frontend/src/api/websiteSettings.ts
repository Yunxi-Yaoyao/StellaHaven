import {api} from './client';
import type {Website,WebsiteConnection,RequestPolicy,NavigationSnapshot} from '../stores/navigation';
export interface WebsiteCheck {
 compatibility?:{enabled:boolean;css:string;js:string;timing:'document_start'|'dom_ready'}|null;
 software?:{type:'unknown'|'openlist'|'immich';source:string|null};
 normalized_url:string; name_suggestion:string;
 alternate_normalized_url?:string|null;
 access:{status:'reachable'|'login_required'|'blocked'|'unknown';http_status:number|null};
 embedding:{status:'allowed'|'blocked'|'unknown';reason_code:string;reason:string};
 injection:{status:'supported'|'unsupported'|'unknown'|'loader_required';reason:string};
 help:{title:string;location:string|null;instructions:string[];external_url:string|null}|null;
 can_save:boolean; recommended_behavior:'embedded'|'external'; issues:string[]; check_id?:string;
}
export type ConnectionDraft=Omit<WebsiteConnection,'has_token'> & {token?:string|null;clear_token?:boolean};
export type TemplateId='openlist'|'immich'|`user_${string}`;
export interface WebsiteTemplate {id:TemplateId;provenance?:'builtin'|'user';name:string;description:string;draft:Partial<WebsiteDraft> & {custom:NonNullable<WebsiteDraft['custom']>}}
export const getWebsiteTemplates=()=>api<WebsiteTemplate[]>('/website-templates');
export const saveWebsiteTemplate=(name:string,draft:WebsiteDraft,idempotency_key?:string)=>{
 const c=draft.connection;
 // Compare before the portable whitelist removes the current comparison secret.
 if(c?.token&&[draft.custom?.css,draft.custom?.js].some(code=>code?.includes(c.token!)))throw {status:422,detail:'代码包含凭据，请移除后再存为模板'};
 const portable={name:draft.name,icon:draft.icon,open_behavior:draft.open_behavior,background:draft.background,custom:draft.custom,request_policy:draft.request_policy,connection:c?{transport:c.transport,auth_mode:c.auth_mode,header_name:c.header_name,injection_delivery:c.injection_delivery}:undefined};
 return api<WebsiteTemplate>('/website-templates',{method:'POST',body:JSON.stringify({name,draft:portable,idempotency_key})});
};
export const deleteWebsiteTemplate=(id:string)=>api<void>(`/website-templates/${encodeURIComponent(id)}`,{method:'DELETE'});
export interface WebsiteDraft {
 expected_revision?:number;
 address_mode?:'ip'|'domain'|null;alternate_address?:string|null;
 private_address?:string|null;entry_policy?:'follow'|'public';access_adapter?:'auto'|'generic'|'openlist'|'immich';
 template_id?:TemplateId|null;connection?:ConnectionDraft;background?:'solid'|'home';request_policy?:RequestPolicy;
 // Legacy API compatibility only; embedded-page retention is automatic at runtime.
 address:string;name?:string;icon:string;visible:boolean;keep_alive?:boolean;
 open_behavior:'embedded'|'external';
 custom?:{enabled:boolean;css:string;js:string;timing:'dom_ready'|'document_start'};
 preserve_saved_draft?:boolean;
}
export const checkWebsiteDraft=(input:Pick<WebsiteDraft,'address'|'open_behavior'|'address_mode'|'alternate_address'> & {custom_enabled:boolean;website_type?:'openlist'|'immich';connection?:ConnectionDraft;module_id?:string},signal?:AbortSignal)=>api<WebsiteCheck>('/website-settings/check',{method:'POST',body:JSON.stringify(input),signal});
export interface WebsiteSaveResult extends Website {check:WebsiteCheck;navigation:NavigationSnapshot;idempotency_key:string}
export const saveWebsiteDraft=(id:string|undefined,input:WebsiteDraft & {idempotency_key:string})=>api<WebsiteSaveResult>(id?`/website-settings/${encodeURIComponent(id)}`:'/website-settings',{method:id?'PATCH':'POST',body:JSON.stringify(input)});
export const getWebsiteSaveReceipt=(id:string,key:string)=>api<WebsiteSaveResult>(`/website-settings/${encodeURIComponent(id)}/receipt?idempotency_key=${encodeURIComponent(key)}`);
