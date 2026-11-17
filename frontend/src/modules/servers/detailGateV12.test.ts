import {afterEach,beforeEach,expect,test,vi} from 'vitest';
import {createApp,h,nextTick} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import Detail from './NodeDetailView.vue';
import * as api from '../../api/servers';
vi.mock('./chartRuntime',()=>({init:vi.fn(),getInstanceByDom:()=>undefined}));
vi.mock('../../api/servers',async original=>({...await original<typeof import('../../api/servers')>(),getNodeDetail:vi.fn(),listMonitors:vi.fn(async()=>[]),getNodeMetrics:vi.fn(async()=>[]),getNodeSysMetrics:vi.fn(async()=>[]),getTrafficStats:vi.fn(),latestNetTask:vi.fn()}));
vi.mock('../../composables/useToast',()=>({toast:vi.fn()}));
let app:ReturnType<typeof createApp>|undefined,el:HTMLElement;
async function settle(){for(let i=0;i<60;i++)await Promise.resolve();await nextTick();}
beforeEach(()=>{vi.resetAllMocks();Object.defineProperty(document,'hidden',{configurable:true,value:false});vi.mocked(api.listMonitors).mockResolvedValue([]);});
afterEach(()=>{app?.unmount();app=undefined;el?.remove();});
test('backend non-online rejection clears detail and returns to node inventory without charts',async()=>{vi.mocked(api.getNodeDetail).mockRejectedValue({status:409,detail:{code:'node_not_online',message:'节点尚未正常在线'}});el=document.createElement('div');document.body.append(el);const router=createRouter({history:createMemoryHistory(),routes:[{path:'/status/:id',component:{render:()=>null}},{path:'/status',component:{render:()=>null}}]});await router.push('/status/7');app=createApp({render:()=>h(Detail,{nodeId:7})});app.use(router);app.mount(el);await settle();expect(router.currentRoute.value.path).toBe('/status');expect(api.getNodeMetrics).not.toHaveBeenCalled();expect(api.latestNetTask).not.toHaveBeenCalled();});
