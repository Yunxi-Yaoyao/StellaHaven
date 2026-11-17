import {beforeEach,expect,it,vi} from 'vitest';
import {api} from '../../api/client';
import {saveWebsiteTemplate,type WebsiteDraft} from '../../api/websiteSettings';
vi.mock('../../api/client',()=>({api:vi.fn()}));
beforeEach(()=>vi.clearAllMocks());
const draft=():WebsiteDraft=>({address:'https://private.invalid/',icon:'globe',visible:true,keep_alive:false,open_behavior:'embedded',connection:{transport:'proxy',auth_mode:'header',header_name:'Authorization',token:'synthetic-current-token',injection_delivery:'proxy'},custom:{enabled:false,css:'',js:'',timing:'dom_ready'}});
for(const field of ['css','js'] as const)it(`rejects known current Token in ${field} before serialization, without a POST or draft loss`,async()=>{
 const input=draft();input.custom![field]='/* '+input.connection!.token+' */';
 const before=JSON.stringify(input);
 await expect(Promise.resolve().then(()=>saveWebsiteTemplate('Safe name',input))).rejects.toMatchObject({detail:'代码包含凭据，请移除后再存为模板'});
 expect(api).not.toHaveBeenCalled();expect(JSON.stringify(input)).toBe(before);
});
it('passes the preserved optional template operation key to the backend',async()=>{
 await saveWebsiteTemplate('Safe name',draft(),'template-operation-1');
 expect(JSON.parse(vi.mocked(api).mock.calls[0]![1]!.body as string).idempotency_key).toBe('template-operation-1');
});
it('saves ordinary code without address or credentials',async()=>{
 const input=draft();input.custom!.js='window.example=1';
 await saveWebsiteTemplate('Safe name',input);
 const [path,options]=vi.mocked(api).mock.calls[0]!;
 expect(path).toBe('/website-templates');expect(options?.method).toBe('POST');
 const body=JSON.parse(options!.body as string);
 expect(body.draft.custom.js).toBe('window.example=1');expect(body.draft).not.toHaveProperty('address');expect(body.draft.connection).not.toHaveProperty('token');expect(body.draft).not.toHaveProperty('keep_alive');
});
