import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {createTarget,resolveTarget,splitProxyUrl} from './integrations';
import {setElevationHandler,ApiError} from './client';
vi.mock('../modules/home/auth',()=>({auth:{me:{id:'fixture'},sessionGeneration:0,sessionClosing:false,suspended:false},refreshAccess:vi.fn(async()=>false)}));
beforeEach(()=>{vi.restoreAllMocks();setElevationHandler(undefined);});
afterEach(()=>{vi.unstubAllGlobals();setElevationHandler(undefined);});
it('splits HTTP private URL with port and preserves initial path query and fragment',()=>{
 expect(splitProxyUrl('http://10.66.0.2:12020/photos?q=1#grid')).toEqual({origin:'http://10.66.0.2:12020',initial_path:'/photos?q=1#grid'});
});
it.each(['javascript:alert(1)','https://user:secret@example.test','https://@example.test','https://example.test/ bad','https://exa\\mple.test'])('rejects unsafe URL %s before any approval',value=>{
 expect(()=>splitProxyUrl(value)).toThrow();
});
it('DNS preview serializes private consent explicitly and does not send headers or credentials',async()=>{
 const fetchMock=vi.fn(async()=>new Response(JSON.stringify({status:'resolved',normalized_origin:'https://example.test',resolved_ips:['93.184.216.34']})));vi.stubGlobal('fetch',fetchMock);
 await resolveTarget('https://example.test');
 expect(fetchMock.mock.calls[0]).toEqual(['/integration-targets/resolve',expect.objectContaining({method:'POST',body:JSON.stringify({upstream_url:'https://example.test',allow_private:false})})]);
});
it('target creation preserves frozen IPs and does not assume controlled',async()=>{
 const fetchMock=vi.fn(async()=>new Response(JSON.stringify({id:'target'})));vi.stubGlobal('fetch',fetchMock);
 const body={name:'site',upstream_url:'http://10.66.0.2:12020',allowed_ips:['10.66.0.2'],controlled:false,headers:{}};
 await createTarget(body);expect(fetchMock.mock.calls[0]).toEqual(['/integration-targets',expect.objectContaining({method:'POST',body:JSON.stringify(body)})]);
});
it('admin 403 waits for explicit global modal confirmation and retries resolver only once',async()=>{
 const fetchMock=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:{code:'admin_elevation_required'}}),{status:403})).mockResolvedValue(new Response(JSON.stringify({status:'resolved'})));vi.stubGlobal('fetch',fetchMock);
 const confirm=vi.fn(async()=>true);setElevationHandler(confirm);await resolveTarget('https://example.test');
 expect(confirm).toHaveBeenCalledWith('admin_elevation_required','/integration-targets/resolve');expect(fetchMock).toHaveBeenCalledTimes(2);
});
it('declined elevation never retries or creates anything',async()=>{
 const fetchMock=vi.fn(async()=>new Response(JSON.stringify({detail:{code:'admin_elevation_required'}}),{status:403}));vi.stubGlobal('fetch',fetchMock);setElevationHandler(async()=>false);
 await expect(resolveTarget('https://example.test')).rejects.toBeInstanceOf(ApiError);expect(fetchMock).toHaveBeenCalledTimes(1);
});
