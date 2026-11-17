import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {effectScope,ref,reactive} from 'vue';
const mocks=vi.hoisted(()=>({projects:vi.fn(),detached:vi.fn()}));
vi.mock('../../api/webProjects',()=>({listProjectIdentities:mocks.projects}));
vi.mock('../../api/detachedSources',()=>({listDetachedSources:mocks.detached}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false})}));
import {useWebProjectCatalog} from './useWebProjectCatalog';
const source={id:'source',workspace_id:'ws',kind:'detached-source',title:'renamed',mime:'text/html',updated_at:'v1'};
let scope:ReturnType<typeof effectScope>;
beforeEach(()=>{vi.clearAllMocks();mocks.projects.mockResolvedValue([]);mocks.detached.mockResolvedValue([source]);scope=effectScope();});
afterEach(()=>scope.stop());
it('keeps a navigation waiter attached to a superseding same-scope catalog refresh',async()=>{
 let release!:(value:unknown[])=>void;
 mocks.projects.mockReturnValueOnce(new Promise(r=>release=r));
 const catalog=scope.run(()=>useWebProjectCatalog(reactive({workspaceId:'ws',userId:'alice'}),ref(true)))!;
 const first=catalog.load();
 const refresh=catalog.load(true);expect(await refresh).toBe(true);
 release([]);expect(await first).toBe(true);
 expect(catalog.detachedFor('source')).toEqual(source);
});
it('authoritatively classifies extensionless detached text',async()=>{
 const catalog:any=scope.run(()=>useWebProjectCatalog(reactive({workspaceId:'ws',userId:'alice'}),ref(true)));
 expect(await catalog.load()).toBe(true);expect(typeof catalog.detachedFor).toBe('function');expect(catalog.detachedFor('source')).toEqual(source);expect(catalog.projectFor('source')).toBeNull();
});
it('fails closed instead of permitting ordinary Markdown after identity lookup failure',async()=>{
 mocks.detached.mockRejectedValue(Error('offline'));
 const catalog=scope.run(()=>useWebProjectCatalog(reactive({workspaceId:'ws',userId:'alice'}),ref(true)))!;
 expect(await catalog.load()).toBe(false);expect(catalog.status.value).toBe('error');
});
