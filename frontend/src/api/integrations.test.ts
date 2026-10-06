import {expect,it,vi} from 'vitest';
import {api} from './client';
import {validateInjection} from './integrations';
vi.mock('./client',()=>({api:vi.fn(async()=>({valid:true,errors:[]}))}));
it('serializes only five injection draft fields and never resends the opaque active version',async()=>{
 await validateInjection('module-id',{enabled:true,css:'body{}',js:'',timing:'dom_ready',csp_policy:'reject',version:'opaque-active-version'} as any);
 const [,options]=vi.mocked(api).mock.calls[0]!;
 expect(JSON.parse(String(options?.body))).toEqual({enabled:true,css:'body{}',js:'',timing:'dom_ready',csp_policy:'reject'});
});
