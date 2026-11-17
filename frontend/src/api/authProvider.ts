import {api} from './client';
export interface AuthClient {
  client_id:string; name:string; enabled:boolean; redirect_uris:string[]; has_secret:boolean; scopes:string[];
}
export interface AuthProviderConfig {
  issuer:string; discovery_url:string; authorization_endpoint:string; token_endpoint:string; userinfo_endpoint:string; jwks_uri:string;
  clients:AuthClient[]; capabilities:Record<string,unknown>;
}
export type CreateAuthClient = Pick<AuthClient,'client_id'|'name'|'redirect_uris'|'scopes'>;
export type UpdateAuthClient = Partial<Pick<AuthClient,'name'|'redirect_uris'|'enabled'|'scopes'>>;
export interface AuthClientSecret { client_id:string; client_secret:string }
const clientPath=(id:string)=>`/auth/provider/clients/${encodeURIComponent(id)}`;
export const getAuthProvider=async()=>{
  const value=await api<AuthProviderConfig>('/auth/provider/config');
  const strings=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(item=>typeof item==='string');
  if(!value||!['issuer','discovery_url','authorization_endpoint','token_endpoint','userinfo_endpoint','jwks_uri'].every(key=>typeof value[key as keyof AuthProviderConfig]==='string')||!Array.isArray(value.clients)||!value.clients.every(client=>client&&typeof client.client_id==='string'&&typeof client.name==='string'&&typeof client.enabled==='boolean'&&typeof client.has_secret==='boolean'&&strings(client.redirect_uris)&&strings(client.scopes))){
    throw new Error('认证配置不完整，请重试读取；已有草稿未更改');
  }
  return value;
};
export const createAuthClient=(payload:CreateAuthClient)=>api<AuthClientSecret>('/auth/provider/clients',{method:'POST',body:JSON.stringify(payload)});
export const updateAuthClient=(id:string,payload:UpdateAuthClient)=>api<AuthClient>(clientPath(id),{method:'PATCH',body:JSON.stringify(payload)});
export const deleteAuthClient=(id:string)=>api<void>(clientPath(id),{method:'DELETE'});
export const revealAuthClientSecret=(id:string)=>api<AuthClientSecret>(`${clientPath(id)}/reveal-secret`,{method:'POST',cache:'no-store'});
export const rotateAuthClientSecret=(id:string)=>api<AuthClientSecret>(`${clientPath(id)}/rotate-secret`,{method:'POST'});
