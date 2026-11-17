import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {deleteMonitorGroup,getMonitorGroupDeletionState,removeMonitor,createMonitorBatch,createMonitorGroup} from '../../api/servers';
import {refreshAccess} from '../home/auth';
vi.mock('../home/auth',()=>({auth:{me:{id:'owner'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:0},refreshAccess:vi.fn()}));
const uuid='11111111-1111-4111-8111-111111111111';
const batch={items:[{name:'TCP',type:'tcp',target:'example.com:80',node_id:7}],request_key:uuid,group_id:null,expected_group_uuid:null};
test.each(['item-delete','batch-create','group-create'])('%s never automatically resends its write after 401 refresh',async kind=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response('{}',{status:200}));vi.stubGlobal('fetch',fetch);
 const operation=kind==='item-delete'?removeMonitor(7):kind==='batch-create'?createMonitorBatch(batch):createMonitorGroup({name:'group',items:batch.items,request_key:uuid,failure_policy:'any',rotation_seconds:0});
 await expect(operation).rejects.toThrow();expect(fetch).toHaveBeenCalledTimes(1);
});
test('all new writes honor final caller admission before fetch',async()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 await expect(removeMonitor(7,()=>false)).rejects.toThrow();await expect(createMonitorBatch(batch,()=>false)).rejects.toThrow();await expect(createMonitorGroup({name:'group',items:batch.items,request_key:uuid,failure_policy:'any',rotation_seconds:0},()=>false)).rejects.toThrow();expect(fetch).not.toHaveBeenCalled();
});
beforeEach(()=>{vi.mocked(refreshAccess).mockResolvedValue(true);});
afterEach(()=>{vi.unstubAllGlobals();vi.resetAllMocks();});
test('atomic delete uses explicit contract and never resends POST even after a 401 refresh',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(null,{status:204}));vi.stubGlobal('fetch',fetch);
 await expect(deleteMonitorGroup(2,[7,8],uuid)).rejects.toThrow();expect(fetch).toHaveBeenCalledTimes(1);expect(fetch.mock.calls[0]![0]).toBe('/monitors/groups/2/delete');const options=fetch.mock.calls[0]![1];expect(options.method).toBe('POST');expect(JSON.parse(options.body)).toEqual({expected_child_ids:[7,8],expected_stable_uuid:uuid});
});
test('readback sends only exact confirmed IDs with abort support',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({group_exists:false,children:[],remaining_child_ids:[],protected:false,name:null}),{status:200}));vi.stubGlobal('fetch',fetch);const controller=new AbortController();await getMonitorGroupDeletionState(2,[7,8],controller.signal,uuid);expect(fetch.mock.calls[0]![0]).toBe('/monitors/groups/2/deletion-state?expected_child_ids=7&expected_child_ids=8&expected_stable_uuid='+uuid);expect(fetch.mock.calls[0]![1].signal).toBe(controller.signal);
});

test('401 readback refresh retry keeps the confirmed UUID, IDs and signal on every GET',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response('{}',{status:401})).mockResolvedValueOnce(new Response(JSON.stringify({stable_uuid:null,identity_matches:false,group_exists:false,children:[],remaining_child_ids:[],protected:false,name:null}),{status:200}));vi.stubGlobal('fetch',fetch);
 const controller=new AbortController();await getMonitorGroupDeletionState(2,[7,8],controller.signal,uuid);expect(fetch).toHaveBeenCalledTimes(2);
 for(const [url,options] of fetch.mock.calls){expect(url).toBe('/monitors/groups/2/deletion-state?expected_child_ids=7&expected_child_ids=8&expected_stable_uuid='+uuid);expect(options.signal).toBe(controller.signal);expect(options.method).toBeUndefined();}
});
