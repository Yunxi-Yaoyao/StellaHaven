import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {deleteDoc,permanentDeleteDoc} from '../../api/notes';
const m=vi.hoisted(()=>({refresh:vi.fn()}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:m.refresh}));
let release:(v:boolean)=>void;
beforeEach(()=>{m.refresh.mockImplementation(()=>new Promise<boolean>(r=>release=r));vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(null,{status:401})).mockResolvedValue(new Response(null,{status:204})));});
afterEach(()=>vi.unstubAllGlobals());
it.each([deleteDoc,permanentDeleteDoc])('batch component admission fences 401 retry in %s',async(remove)=>{
 let alive=true;const pending=remove('id',false,'scope',()=>alive);await vi.waitFor(()=>expect(m.refresh).toHaveBeenCalled());alive=false;release(true);await expect(pending).rejects.toMatchObject({name:'AbortError'});expect(fetch).toHaveBeenCalledTimes(1);
});
it('still-admitted batch preserves normal 401 refresh retry',async()=>{const pending=deleteDoc('id',false,'scope',()=>true);await vi.waitFor(()=>expect(m.refresh).toHaveBeenCalled());release(true);await pending;expect(fetch).toHaveBeenCalledTimes(2);});
