import {api} from './client';
import type {Injection} from '../stores/navigation';
export type BuiltinSite='drive'|'gallery';
export type BuiltinVersion=Injection & {version:string;status:'active'|'revoked'};
export interface BuiltinState {site:BuiltinSite;source:'postgres'|'preset';draft:Injection|null;active:BuiltinVersion;previous:BuiltinVersion|null;preset?:{css:string;js:string};base_required?:boolean}
const path=(site:BuiltinSite)=>`/builtin-injections/${site}`;
export const getBuiltin=(site:BuiltinSite,signal?:AbortSignal)=>api<BuiltinState>(path(site),{signal});
export const validateBuiltin=(site:BuiltinSite,draft:Injection)=>api<{valid:boolean;errors:string[];draft:Injection}>(path(site)+'/validate',{method:'POST',body:JSON.stringify({enabled:draft.enabled,css:draft.css,js:draft.js,timing:draft.timing,csp_policy:draft.csp_policy})});
export const applyBuiltin=(site:BuiltinSite)=>api<BuiltinState>(path(site)+'/apply',{method:'POST'});
export const rollbackBuiltin=(site:BuiltinSite)=>api<BuiltinState>(path(site)+'/rollback',{method:'POST'});
