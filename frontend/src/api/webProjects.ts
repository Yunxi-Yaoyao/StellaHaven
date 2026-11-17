import {api} from './client';
export interface ProjectFile {id:string;path:string;kind:'text'|'binary';mime:string;updated_at:string}
export interface WebProject {id:string;workspace_id:string;title:string;entry:string|null;files:ProjectFile[]}
export interface RuntimeState {revision:number;epoch:number;data:Record<string,string>}
export interface RuntimeLaunch {url:string;capability:string;source_origin:string;target_origin:string;state:RuntimeState;expires_in:number}
export interface ProjectIdentity {id:string;workspace_id:string;members:string[];assets?:{root:string;file:string;path:string;mime:string}[]}
export const listProjectIdentities=(workspace:string)=>api<ProjectIdentity[]>(`/web-projects/workspace/${workspace}/identities`);
export const getProject=(root:string)=>api<import('./projectFiles').FileProject>(`/web-projects/${root}`);
export const listProjects=(workspace:string)=>api<WebProject[]>('/web-projects/workspace/'+workspace);
export const getProjectSource=(root:string,file:string)=>api<ProjectFile&{content:string|null;url:string|null}>(`/web-projects/${root}/files/${file}`);
export const saveProjectSource=(root:string,file:string,updated_at:string,content:string)=>api<{id:string;updated_at:string;content:string}>(`/web-projects/${root}/files/${file}`,{method:'PATCH',body:JSON.stringify({updated_at,content})});
export const launchProject=(root:string)=>api<RuntimeLaunch>(`/web-projects/${root}/launch`,{method:'POST'});
export interface RuntimeRenewal {capability:string;epoch:number;expires_in:number;renew_after:number}
export const renewProject=(root:string,capability:string,epoch:number)=>api<RuntimeRenewal>(`/web-projects/${root}/renew`,{method:'POST',body:JSON.stringify({capability,epoch})});
export const getProjectState=(root:string)=>api<RuntimeState>(`/web-projects/${root}/state`);
export const resetProjectState=(root:string)=>api<RuntimeState>(`/web-projects/${root}/state`,{method:'DELETE'});
export const saveProjectState=(root:string,grant:RuntimeLaunch,write_id:string,data:Record<string,string>)=>api<RuntimeState>(`/web-projects/${root}/state`,{method:'PUT',body:JSON.stringify({revision:grant.state.revision,epoch:grant.state.epoch,capability:grant.capability,write_id,data})});
