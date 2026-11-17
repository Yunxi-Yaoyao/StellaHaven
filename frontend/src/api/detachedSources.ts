import {api} from './client';
export interface DetachedSource {id:string;workspace_id:string;title:string;kind:'detached-source';mime:string;updated_at:string}
export type DetachedSourceBody=DetachedSource&{content:string};
export const listDetachedSources=(workspace:string)=>api<DetachedSource[]>(`/detached-sources?workspace_id=${encodeURIComponent(workspace)}`);
export const getDetachedSource=(id:string)=>api<DetachedSourceBody>(`/detached-sources/${id}`);
export const saveDetachedSource=(id:string,updated_at:string,content:string)=>api<DetachedSourceBody>(`/detached-sources/${id}`,{method:'PUT',body:JSON.stringify({updated_at,content})});
