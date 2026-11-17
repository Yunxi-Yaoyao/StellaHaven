import {it,expect,vi,beforeEach} from 'vitest';
import {api} from './client';
vi.mock('./client',()=>({api:vi.fn().mockResolvedValue({})}));
const modules=import.meta.glob('./authProvider.ts',{eager:true});
const valid={issuer:'https://stella.test',discovery_url:'https://stella.test/.well-known/openid-configuration',authorization_endpoint:'https://stella.test/authorize',token_endpoint:'https://stella.test/token',userinfo_endpoint:'https://stella.test/userinfo',jwks_uri:'https://stella.test/jwks',clients:[],capabilities:{}};
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockResolvedValue(valid);});
for(const invalid of [null,{}, {...valid,clients:null},{...valid,clients:[{client_id:'partial'}]}]){
 it('rejects incomplete provider state rather than inventing an empty client list',async()=>{
  vi.mocked(api).mockResolvedValueOnce(invalid);const a=modules['./authProvider.ts'] as any;await expect(a.getAuthProvider()).rejects.toThrow('认证配置不完整');
 });
}
it('uses standard admin-aware API and exact encoded client endpoints with explicit payloads',async()=>{
 const a=modules['./authProvider.ts'] as any;expect(a,'native provider API exists').toBeDefined();
 const payload={client_id:'new-app',name:'新应用',redirect_uris:['https://app.test/callback'],scopes:['openid','profile','email']};
 await a.getAuthProvider();await a.createAuthClient(payload);await a.updateAuthClient('a/b',{name:'改名',redirect_uris:payload.redirect_uris,enabled:false,scopes:['openid']});await a.rotateAuthClientSecret('a/b');await a.deleteAuthClient('a/b');
 expect(vi.mocked(api).mock.calls).toEqual([
 ['/auth/provider/config'],['/auth/provider/clients',{method:'POST',body:JSON.stringify(payload)}],
 ['/auth/provider/clients/a%2Fb',{method:'PATCH',body:JSON.stringify({name:'改名',redirect_uris:payload.redirect_uris,enabled:false,scopes:['openid']})}],
 ['/auth/provider/clients/a%2Fb/rotate-secret',{method:'POST'}],['/auth/provider/clients/a%2Fb',{method:'DELETE'}],
 ]);
});
