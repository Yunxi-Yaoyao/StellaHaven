import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, nextTick, h, type Component } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import NodeDetail from './NodeDetailView.vue';
import Overview from './OverviewView.vue';
import Nodes from './NodesView.vue';
import Records from './RecordsView.vue';
import Tools from './ToolsView.vue';
import * as api from '../../api/servers';

vi.mock('./NodeComponents.vue', () => ({ __esModule: true, default: {render:()=>null} }));
vi.mock('./ServerWorldMap.vue', () => ({ __esModule: true, default: { render: () => null } }));
vi.mock('echarts', () => ({ init: () => ({ setOption() {}, resize() {}, dispose() {} }), getInstanceByDom: () => undefined }));
vi.mock('echarts/core', () => ({ use() {}, init: () => ({ setOption() {}, resize() {}, dispose() {} }), getInstanceByDom: () => undefined }));
vi.mock('../../api/servers', async importOriginal => {
  const original = await importOriginal<typeof import('../../api/servers')>();
  return { ...original, listNodes: vi.fn(async () => []), createIperfTask: vi.fn(async()=>({id:9,status:"pending",mode:"iperf3",duration:10})), getIperfTask: vi.fn(), listIperfTasks: vi.fn(async () => []), listMtrTasks: vi.fn(async () => []), listCommands: vi.fn(async () => []), getNodeDetail: vi.fn(), listMonitors: vi.fn(async () => []),
    getNodeMetrics: vi.fn(), getNodeSysMetrics: vi.fn(async () => []), getTrafficStats: vi.fn(async () => ({sample_count: 0, rx_total: 0, tx_total: 0, rx_95: 0, tx_95: 0, rx_max: 0, tx_max: 0, rx_min: 0, tx_min: 0})),
    latestNetTask: vi.fn(async () => null), scanFirewall: vi.fn(async () => ({ id: 1 })), scanPbr: vi.fn(async () => ({ id: 2 })),
    getNetTask: vi.fn(async () => ({status: 'done', result_json: {}})), updateNodeIfaces: vi.fn(),
  };
});
let app: ReturnType<typeof createApp> | undefined;
let host: HTMLElement;
async function settle() { for (let i=0;i<30;i++) await Promise.resolve(); await nextTick(); }
async function mount(component: Component = NodeDetail) {
  host = document.createElement('div'); document.body.append(host);
  const router = createRouter({ history: createMemoryHistory(), routes: [{path:'/', component: {render:()=>null}}] });
  await router.push('/'); await router.isReady();
  app = createApp({ render: () => h(component, {nodeId: 7, tool: "iperf"}) }); app.use(router); app.mount(host); await settle();
}
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.mocked(api.getNodeDetail).mockResolvedValue({ id: 7, status: 'online', net_type: 'internal', interfaces: {eth0:{is_default:true,up:true}}, latest_metrics:[], storage:[], sys_info:null } as any);
  vi.mocked(api.getNodeMetrics).mockResolvedValue([]);
  vi.mocked(api.listNodes).mockResolvedValue([]);
});
afterEach(() => { app?.unmount(); host?.remove(); vi.useRealTimers(); });

test('overview status is singleflight and aborts when page becomes hidden', async () => {
  const signals: (AbortSignal|undefined)[]=[];
  vi.mocked(api.listNodes).mockImplementation(async signal => {
    signals.push(signal); await new Promise(resolve=>setTimeout(resolve,8000)); return [];
  });
  await mount(Overview);
  await vi.advanceTimersByTimeAsync(6000); await settle();
  expect(signals).toHaveLength(1);
  Object.defineProperty(document,'hidden',{configurable:true,value:true});
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(signals[0]?.aborted).toBe(true);
  Object.defineProperty(document,'hidden',{configurable:true,value:false});
});

test.each([['nodes',Nodes],['records',Records],['tools',Tools]])('%s list polling is singleflight and abortable', async (_name, component) => {
  const signals: (AbortSignal|undefined)[]=[];
  vi.mocked(api.listNodes).mockImplementation(async signal=> {
    signals.push(signal); await new Promise(resolve=>setTimeout(resolve,8000)); return [];
  });
  await mount(component);
  await vi.advanceTimersByTimeAsync(6000); await settle();
  expect(signals).toHaveLength(1);
  app?.unmount(); app=undefined;
  expect(signals[0]?.aborted).toBe(true);
  await vi.advanceTimersByTimeAsync(15000); await settle();
  expect(signals).toHaveLength(1);
});

test('iperf progress preserves singleflight cursor and aborts in flight on leave', async () => {
  vi.mocked(api.listNodes).mockResolvedValue([{id:1,status:'online',name:'server',net_type:'public'},{id:2,status:'online',name:'client',net_type:'internal'}] as any);
  const signals:(AbortSignal|undefined)[]=[];
  vi.mocked(api.getIperfTask).mockImplementation(async (_id, opts)=>{
    signals.push(opts?.signal); await new Promise(resolve=>setTimeout(resolve,5000));
    return {id:9,status:'running',progress_json:[]} as any;
  });
  await mount(Tools);
  (host.querySelector('.go-btn') as HTMLElement).click(); await settle();
  await vi.advanceTimersByTimeAsync(4000); await settle();
  expect(signals).toHaveLength(1);
  app?.unmount(); app=undefined;
  expect(signals[0]?.aborted).toBe(true);
  await vi.advanceTimersByTimeAsync(15000); await settle();
  expect(signals).toHaveLength(1);
});

test('raw traffic percentile keeps 5-second units when chart is downsampled', async () => {
  vi.mocked(api.getTrafficStats).mockResolvedValue({sample_count:100,rx_95:625000,tx_95:0,rx_total:0,tx_total:0,rx_max:625000,rx_min:625000,tx_max:0,tx_min:0});
  await mount();
  (host.querySelector('.preset-btn') as HTMLElement).click(); await nextTick();
  ([...host.querySelectorAll('.pop-item')].find(e=>e.textContent==='24小时') as HTMLElement).click(); await settle();
  expect(host.querySelector('.stats-bar .stat-item b')?.textContent).toBe('1.00 Mbps');
});

test('turning live off during a slow window load never restarts polling', async () => {
  await mount();
  const signals:AbortSignal[]=[];
  vi.mocked(api.getNodeMetrics).mockImplementation(async (_id,opts)=>{
    signals.push(opts!.signal!); await new Promise(resolve=>setTimeout(resolve,5000)); return [];
  });
  (host.querySelector('.live-btn') as HTMLElement).click(); await settle();
  (host.querySelector('.live-btn') as HTMLElement).click(); await settle();
  expect(signals[0]?.aborted).toBe(true);
  await vi.advanceTimersByTimeAsync(15000); await settle();
  expect(signals).toHaveLength(1);
});

test('one preset selection sends one query group', async () => {
  await mount(); vi.mocked(api.getNodeMetrics).mockClear();
  (host.querySelector('.preset-btn') as HTMLElement).click(); await nextTick();
  const button = [...host.querySelectorAll('.pop-item')].find(e => e.textContent === '6小时') as HTMLElement;
  button.click(); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test('slow live fetch keeps at most one request and unmount aborts it', async () => {
  await mount();
  const signals: (AbortSignal|undefined)[] = [];
  vi.mocked(api.getNodeMetrics).mockImplementation(async (_id, opts) => {
    signals.push(opts?.signal);
    await new Promise(resolve => setTimeout(resolve, 5000)); return [];
  });
  (host.querySelector('.live-btn') as HTMLElement).click(); await settle();
  await vi.advanceTimersByTimeAsync(4000); await settle();
  expect(signals).toHaveLength(1);
  app?.unmount(); app=undefined;
  expect(signals[0]?.aborted).toBe(true);
  const before=signals.length;
  await vi.advanceTimersByTimeAsync(15000); await settle();
  expect(signals).toHaveLength(before);
});
