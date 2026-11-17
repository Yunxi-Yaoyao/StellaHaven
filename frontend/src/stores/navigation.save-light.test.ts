import {beforeEach,expect,it,vi} from 'vitest';
vi.mock('../api/client',()=>({api:vi.fn()}));
import {api} from '../api/client';
import {loadNavigation,navigation,navigationRows,resetNavigation,saveNavigation} from './navigation';
const request=vi.mocked(api);
const config=(revision=0,mutation_id:string|null=null)=>({entries:[{id:'home',title:'Server title',icon:'home',visible:true}],modules:[],legacy_routes:{},revision,mutation_id});
beforeEach(()=>{resetNavigation();request.mockReset();request.mockImplementation(async(url)=>url==='/external-modules'?[]:config());});
it('loads only the light projection and reuses confirmed session data',async()=>{
 request.mockResolvedValue(config());
 expect(await loadNavigation()).toBe(true);expect(await loadNavigation()).toBe(true);
 expect(request.mock.calls.map(x=>x[0])).toEqual(['/navigation']);
});
it('merges only real mutation ACK without a follow-up GET',async()=>{
 request.mockResolvedValueOnce(config());await loadNavigation();
 request.mockImplementationOnce(async(_url,options)=>{const body=JSON.parse(options!.body as string);return config(1,body.mutation_id);});
 await saveNavigation(navigationRows.value);
 expect(navigation.entries[0]?.title).toBe('Server title');
 expect(request.mock.calls.map(x=>x[0])).toEqual(['/navigation','/navigation']);
 expect(request.mock.calls[1]?.[1]?.method).toBe('PUT');
});
it('rejects unknown ACK and does not replay a write',async()=>{
 request.mockResolvedValueOnce(config());await loadNavigation();request.mockResolvedValueOnce({});
 await expect(saveNavigation(navigationRows.value)).rejects.toThrow();
 expect(request.mock.calls.filter(x=>x[1]?.method==='PUT')).toHaveLength(1);
});
it('does not merge a response from an expired session',async()=>{
 request.mockResolvedValueOnce(config());await loadNavigation();
 let release!:(x:unknown)=>void;request.mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
 const saving=saveNavigation(navigationRows.value);resetNavigation();release(config(1,'late-response'));
 await expect(saving).rejects.toThrow();expect(navigation.loaded).toBe(false);expect(navigation.entries).toEqual([]);
});
