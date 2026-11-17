import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {effectScope,reactive,ref} from 'vue';
const mocks=vi.hoisted(()=>({identities:vi.fn(),manifest:vi.fn(),legacy:vi.fn()}));
vi.mock('../../api/webProjects',()=>({listProjects:mocks.legacy,listProjectIdentities:mocks.identities,getProject:mocks.manifest}));
vi.mock('../../api/detachedSources',()=>({listDetachedSources:vi.fn(async()=>[])}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
import {auth} from '../home/auth';
import {useWebProjectCatalog} from './useWebProjectCatalog';
let scope:ReturnType<typeof effectScope>;
beforeEach(()=>{vi.clearAllMocks();Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});scope=effectScope();mocks.identities.mockResolvedValue([{id:'broken',workspace_id:'ws',members:['broken','raw']}]);mocks.legacy.mockRejectedValue(Error('invalid path'));mocks.manifest.mockRejectedValue(Error('invalid path'));});
afterEach(()=>scope.stop());
const catalog=()=>scope.run(()=>useWebProjectCatalog(reactive({workspaceId:'ws',userId:'alice'}),ref(true)))!;
it('classifies ordinary notes without loading any full manifest, and errors only for the broken selected project',async()=>{
 const c=catalog();expect(await c.load()).toBe(true);expect(c.identityFor('ordinary')).toBeNull();expect(c.identityFor('raw')?.id).toBe('broken');expect(mocks.manifest).not.toHaveBeenCalled();expect(mocks.legacy).not.toHaveBeenCalled();
 expect(await c.loadProject('raw')).toBeNull();expect(c.projectError.value).toContain('invalid path');expect(c.status.value).toBe('ready');expect(c.identityFor('raw')?.id).toBe('broken');
});
it.each(['owner','workspace','session','epoch','suspended'])('rejects delayed manifest after %s invalidation',async boundary=>{
 const store=reactive({workspaceId:'ws',userId:'alice'});const c=scope.run(()=>useWebProjectCatalog(store,ref(true)))!;await c.load();let release!:(v:any)=>void;mocks.manifest.mockReturnValue(new Promise(r=>release=r));const flight=c.loadProject('raw');
 if(boundary==='owner')auth.me={id:'bob'} as any;if(boundary==='workspace')store.workspaceId='other';if(boundary==='session')auth.sessionGeneration++;if(boundary==='epoch')auth.requestEpoch++;if(boundary==='suspended')auth.suspended=true;
 release({id:'broken',workspace_id:'ws',files:[]});expect(await flight).toBeNull();expect(c.projectFor('raw')).toBeNull();
});
it('supplies tree image drag identity without fetching any full manifest',async()=>{
 const asset={root:'broken',file:'raw',path:'images/cat.png',mime:'image/png'};mocks.identities.mockResolvedValue([{id:'broken',workspace_id:'ws',members:['broken','raw'],assets:[asset]}]);const c=catalog();await c.load();expect(c.assetFor('raw')).toEqual(asset);expect(mocks.manifest).not.toHaveBeenCalled();
});
it('rejects ambiguous or wrong-workspace identity responses instead of interpreting them as ordinary notes',async()=>{
 mocks.identities.mockResolvedValue([{id:'broken',workspace_id:'other',members:['broken','raw']}]);const c=catalog();expect(await c.load()).toBe(false);expect(c.status.value).toBe('error');
});
