import {it,expect,vi,afterEach} from 'vitest';
import * as notes from '../../api/notes';
import {setElevationHandler} from '../../api/client';
vi.mock('../home/auth',()=>({auth:{me:{id:'alice'},sessionGeneration:1,requestEpoch:1},refreshAccess:vi.fn(async()=>false)}));
afterEach(()=>{vi.unstubAllGlobals();setElevationHandler(undefined);});
it('workspace deletion never elevates or replays a legacy 403',async()=>{const elevate=vi.fn(async()=>true);setElevationHandler(elevate);const fetcher=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:{code:'admin_elevation_required'}}),{status:403})).mockResolvedValueOnce(new Response(null,{status:204}));vi.stubGlobal('fetch',fetcher);await expect(notes.deleteWorkspace('ws',true)).rejects.toMatchObject({status:403});expect(elevate).not.toHaveBeenCalled();expect(fetcher).toHaveBeenCalledTimes(1);});
it('explicit permanent DELETE preserves 204 and never opens admin elevation on legacy 403',async()=>{
 const elevate=vi.fn(async()=>true);setElevationHandler(elevate);
 const fetcher=vi.fn().mockResolvedValueOnce(new Response(null,{status:204})).mockResolvedValueOnce(new Response(JSON.stringify({detail:{code:'admin_elevation_required'}}),{status:403}));vi.stubGlobal('fetch',fetcher);
 expect((notes as any).permanentDeleteDoc).toBeTypeOf('function');
 await (notes as any).permanentDeleteDoc('one',false);expect(fetcher.mock.calls[0]![0]).toBe('/documents/one/permanent?cascade=false');
 await expect(notes.emptyTrash('ws')).rejects.toMatchObject({status:403});expect(elevate).not.toHaveBeenCalled();
});
it('preview JSON and all deletion endpoints carry the exact frozen token',async()=>{
 const request={workspace_id:'ws',doc_id:'one',mode:'trash' as const,cascade:false};const response={...request,scope_token:'signed +/?token',target_ids:['one'],descendant_count:0};
 const fetcher=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(response),{status:200})).mockResolvedValueOnce(new Response(null,{status:204})).mockResolvedValueOnce(new Response(null,{status:204})).mockResolvedValueOnce(new Response(JSON.stringify({purged:1}),{status:200}));vi.stubGlobal('fetch',fetcher);
 expect(await notes.previewDelete(request)).toEqual(response);expect(fetcher.mock.calls[0]![0]).toBe('/documents/delete-preview');expect(JSON.parse(fetcher.mock.calls[0]![1].body)).toEqual(request);
 await notes.deleteDoc('one',false,response.scope_token);await notes.permanentDeleteDoc('one',false,response.scope_token);await notes.emptyTrash('ws',response.scope_token);
 for(const call of fetcher.mock.calls.slice(1))expect(new URL(call[0],'http://fixture').searchParams.get('scope_token')).toBe(response.scope_token);
 expect(fetcher.mock.calls.map(call=>call[1].method)).toEqual(['POST','DELETE','DELETE','POST']);
});
