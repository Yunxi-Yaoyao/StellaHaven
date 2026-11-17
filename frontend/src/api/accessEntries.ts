import {api} from './client';
export interface AccessSettings {revision:number;enabled:boolean;public_origin:string;private_origin:string|null}
export interface AccessWebsite {id:string;name:string;mode:string;public_address:string;private_address:string|null;entry_policy:'follow'|'public';template_id:string|null;access_adapter:'auto'|'generic'|'openlist'|'immich'}
export interface AccessSummary {settings:AccessSettings;issuer:string|null;deployed:{public:string;private?:string};websites:AccessWebsite[]}
export interface AccessCheck {can_apply:boolean;digest:string;checks:{name:string;status:'configured'|'pending'|'unused';reason:string}[];network:{dns:string;tls:string;browser:string};behavior:string}
export const getAccessEntries=()=>api<AccessSummary>('/config/access-entries');
export const checkAccessEntries=(draft:AccessSettings)=>api<AccessCheck>('/config/access-entries/check',{method:'POST',body:JSON.stringify(draft)});
export const applyAccessEntries=(draft:AccessSettings,checked_digest:string)=>api<AccessSummary>('/config/access-entries',{method:'PUT',body:JSON.stringify({...draft,checked_digest})});
