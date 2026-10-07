import {api} from './client';
import type {Website,WebsiteConnection,RequestPolicy} from '../stores/navigation';
export interface WebsiteCheck {
 normalized_url:string; name_suggestion:string;
 access:{status:'reachable'|'login_required'|'blocked'|'unknown';http_status:number|null};
 embedding:{status:'allowed'|'blocked'|'unknown';reason_code:string;reason:string};
 injection:{status:'supported'|'unsupported'|'unknown';reason:string};
 help:{title:string;location:string|null;instructions:string[];external_url:string|null}|null;
 can_save:boolean; recommended_behavior:'embedded'|'external'; issues:string[]; check_id?:string;
}
export type ConnectionDraft=Omit<WebsiteConnection,'has_token'> & {token?:string|null;clear_token?:boolean};
export interface WebsiteTemplate {id:'openlist'|'immich';name:string;description:string;draft:Partial<WebsiteDraft> & {custom:NonNullable<WebsiteDraft['custom']>}}
export const getWebsiteTemplates=()=>api<WebsiteTemplate[]>('/website-templates');
export interface WebsiteDraft {
 template_id?:'openlist'|'immich'|null;connection?:ConnectionDraft;background?:'solid'|'home';request_policy?:RequestPolicy;
 address:string;name?:string;icon:string;visible:boolean;keep_alive:boolean;
 open_behavior:'embedded'|'external';
 custom?:{enabled:boolean;css:string;js:string;timing:'dom_ready'|'document_start'};
}
export const checkWebsiteDraft=(input:Pick<WebsiteDraft,'address'|'open_behavior'> & {custom_enabled:boolean;connection?:ConnectionDraft;module_id?:string},signal?:AbortSignal)=>api<WebsiteCheck>('/website-settings/check',{method:'POST',body:JSON.stringify(input),signal});
export const saveWebsiteDraft=(id:string|undefined,input:WebsiteDraft & {idempotency_key:string})=>api<Website & {check:WebsiteCheck}>(id?`/website-settings/${encodeURIComponent(id)}`:'/website-settings',{method:id?'PATCH':'POST',body:JSON.stringify(input)});
