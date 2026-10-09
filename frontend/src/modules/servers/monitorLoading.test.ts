import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, nextTick, h, ref, type Component } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Nodes from './NodesView.vue';
import Detail from './NodeDetailView.vue';
import * as api from '../../api/servers';

const charts = vi.hoisted(() => [] as { el: HTMLElement; setOption: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn> }[]);
vi.mock('./NodeComponents.vue', () => ({ default: { render: () => null } }));
vi.mock('./chartRuntime', () => ({
  init: (el: HTMLElement) => { const chart = { el, setOption: vi.fn(), dispose: vi.fn(), resize: vi.fn() }; charts.push(chart); return chart; },
  getInstanceByDom: () => undefined,
}));
vi.mock('../../api/servers', async original => ({
  ...await original<typeof import('../../api/servers')>(),
  listNodes: vi.fn(), getNodeDetail: vi.fn(), listMonitors: vi.fn(),
  getNodeMetrics: vi.fn(), getNodeSysMetrics: vi.fn(), getTrafficStats: vi.fn(), updateNodeIfaces: vi.fn(),
  getHost: vi.fn(async () => null), getPublicHost: vi.fn(async () => ({ value: '' })),
  latestNetTask: vi.fn(async () => ({ created_at: new Date().toISOString(), result_json: { ufw: {}, rules: [], marks: [], tables: {} } })),
}));
const node = { id: 7, name: 'Test server', status: 'online', platform: 'linux', net_type: 'internal',
  interfaces: { eth0: { is_default: true, up: true }, eth1: { is_default: false, up: true } }, storage: [], latest_metrics: [] };
const stats = { sample_count: 10, rx_95: 625000, tx_95: 0, rx_total: 100, tx_total: 0, rx_max: 625000, rx_min: 0, tx_max: 0, tx_min: 0 };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
let app: ReturnType<typeof createApp> | undefined;
let host: HTMLElement;
const id = ref(7);
async function settle() { for (let i = 0; i < 50; i++) await Promise.resolve(); await nextTick(); }
async function mount(component: Component = Detail) {
  host = document.createElement('div'); document.body.append(host);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
  await router.push('/'); await router.isReady();
  app = createApp({ render: () => h(component, { nodeId: id.value }) }); app.use(router); app.mount(host); await settle();
}
async function click(selector: string) { const el = host.querySelector(selector) as HTMLElement; expect(el, selector).not.toBeNull(); el.click(); await settle(); }
async function button(text: string, selector = 'button') { const el = [...host.querySelectorAll(selector)].find(e => e.textContent?.trim() === text) as HTMLElement; expect(el, text).toBeTruthy(); el.click(); await settle(); }
async function preset(text: string) { await click('.preset-btn'); await button(text, '.pop-item'); }
function trafficChart() { return charts.find(c => c.el === host.querySelectorAll('.chart')[0])!; }
function option() { return trafficChart().setOption.mock.calls.at(-1)![0]; }
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-10T08:00:00Z')); vi.resetAllMocks(); charts.length = 0; id.value = 7;
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  vi.mocked(api.listNodes).mockResolvedValue([]);
  vi.mocked(api.getNodeDetail).mockResolvedValue(node as any);
  vi.mocked(api.listMonitors).mockResolvedValue([]);
  vi.mocked(api.getNodeMetrics).mockResolvedValue([{ ts: '2026-10-10T07:59:55Z', rx_delta: 625000, tx_delta: 0 }] as any);
  vi.mocked(api.getNodeSysMetrics).mockResolvedValue([{ ts: '2026-10-10T07:59:55Z', cpu_pct: 20, mem_pct: 40, disk_pct: 30 }] as any);
  vi.mocked(api.getTrafficStats).mockResolvedValue(stats);
  vi.mocked(api.getHost).mockResolvedValue(null as any);
  vi.mocked(api.getPublicHost).mockResolvedValue({ value: '' } as any);
  vi.mocked(api.latestNetTask).mockResolvedValue({ created_at: new Date().toISOString(), result_json: { ufw: {}, rules: [], marks: [], tables: {} } } as any);
});
afterEach(() => { app?.unmount(); app = undefined; host?.remove(); vi.useRealTimers(); });

test('optional network scans wait for detail readiness and do not run on hidden mount', async () => {
  const pending = deferred<any>(); vi.mocked(api.getNodeDetail).mockReturnValueOnce(pending.promise);
  await mount(); expect(api.latestNetTask).not.toHaveBeenCalled();
  pending.resolve(node); await settle(); expect(api.latestNetTask).toHaveBeenCalledTimes(2);
  app?.unmount(); app = undefined; host.remove(); vi.mocked(api.latestNetTask).mockClear();
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  await mount(); expect(api.latestNetTask).not.toHaveBeenCalled();
});

test('late detail and monitor replies cannot mount charts or restart polling after leave', async () => {
  const detail = deferred<any>(), monitors = deferred<any[]>();
  vi.mocked(api.getNodeDetail).mockReturnValueOnce(detail.promise);
  vi.mocked(api.listMonitors).mockReturnValueOnce(monitors.promise);
  await mount();
  const detailSignal = vi.mocked(api.getNodeDetail).mock.calls[0]![1]!;
  const monitorSignal = vi.mocked(api.listMonitors).mock.calls[0]![0]!;
  app?.unmount(); app = undefined;
  expect(detailSignal.aborted).toBe(true); expect(monitorSignal.aborted).toBe(true);
  detail.resolve(node); monitors.resolve([]); await settle();
  await vi.advanceTimersByTimeAsync(30000); await settle();
  expect(api.getNodeDetail).toHaveBeenCalledTimes(1);
  expect(api.listMonitors).toHaveBeenCalledTimes(1);
  expect(api.getNodeMetrics).not.toHaveBeenCalled(); expect(charts).toHaveLength(0);
});

test('late failed live request never restarts after live off or unmount', async () => {
  await mount();
  const slow = deferred<any[]>(); vi.mocked(api.getNodeMetrics).mockReturnValueOnce(slow.promise);
  await click('.live-btn');
  const signal = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.signal!;
  await click('.live-btn'); expect(signal.aborted).toBe(true);
  slow.reject(new Error('timeout')); await settle();
  await vi.advanceTimersByTimeAsync(30000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(host.textContent).not.toContain('历史数据加载失败');
  const next = deferred<any[]>(); vi.mocked(api.getNodeMetrics).mockReturnValueOnce(next.promise);
  await click('.live-btn'); app?.unmount(); app = undefined;
  next.reject(new Error('timeout')); await settle();
  await vi.advanceTimersByTimeAsync(30000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(3);
});

test('cross-day tooltip keeps MM/DD HH:mm and rolling timezone redraw does not query', async () => {
  vi.mocked(api.getNodeMetrics).mockResolvedValue([
    { ts: '2026-10-10T00:01:00Z', rx_delta: 1, tx_delta: 0 },
    { ts: '2026-10-09T23:59:00Z', rx_delta: 1, tx_delta: 0 },
  ] as any);
  await mount(); await preset('24小时');
  const count = vi.mocked(api.getNodeMetrics).mock.calls.length;
  await button('UTC+8 ▾'); await button('UTC+0', '.tz-menu button');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(count);
  expect(option().xAxis.data).toEqual(['10/09 23:59', '10/10 00:01']);
  expect(option().tooltip.formatter([{ axisValue: option().xAxis.data[0], marker: '', seriesName: 'eth0 ↓', value: 1 }])).toContain('10/09 23:59');
  expect(charts.find(c => c.el === host.querySelectorAll('.chart')[1])!.setOption.mock.calls.at(-1)![0].tooltip.formatter([{ axisValue: '10/09 23:59', marker: '', seriesName: 'CPU', value: 1 }])).toContain('10/09 23:59');
});

test('bounded interface concurrency keeps one captured end despite clock moving mid-group', async () => {
  const ifaces = Object.fromEntries(['a','b','c','d','e'].map(name => [name, { is_default: true, up: true }]));
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, interfaces: ifaces, monitored_ifaces: ifaces } as any);
  let active = 0, maximum = 0;
  const pending: ReturnType<typeof deferred<any[]>>[] = [];
  vi.mocked(api.getNodeMetrics).mockImplementation(async () => {
    active++; maximum = Math.max(maximum, active); vi.setSystemTime(Date.now() + 1000);
    const gate = deferred<any[]>(); pending.push(gate); const result = await gate.promise; active--; return result;
  });
  await mount(); expect(pending).toHaveLength(3);
  pending[0]!.resolve([]); await settle(); pending[1]!.resolve([]); await settle();
  expect(pending).toHaveLength(5); pending.forEach(gate => gate.resolve([])); await settle();
  expect(maximum).toBe(3);
  const ends = vi.mocked(api.getNodeMetrics).mock.calls.map(([, opts]) => opts!.end);
  expect(new Set(ends).size).toBe(1);
  expect(ends[0]).toBe('2026-10-10T08:00:00.000Z');
  expect(vi.mocked(api.getTrafficStats).mock.calls[0]![1]!.end).toBe(ends[0]);
  expect(vi.mocked(api.getNodeSysMetrics).mock.calls[0]![1]!.end).toBe(ends[0]);
});

test('interface changes remain persisted and status polls do not replace selection or range', async () => {
  await mount(); await preset('6小时');
  await button('网卡（1）▾');
  const boxes = [...host.querySelectorAll<HTMLInputElement>('.iface-menu input')];
  boxes[1]!.click(); await settle(); boxes[0]!.click(); await settle();
  expect(api.updateNodeIfaces).toHaveBeenLastCalledWith(7, { eth1: node.interfaces.eth1 });
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.textContent).toContain('网卡（1）');
  expect(host.querySelector('.preset-btn')?.textContent).toContain('6小时');
  expect(vi.mocked(api.getTrafficStats).mock.calls.at(-1)![1]!.ifaces).toEqual(['eth1']);
});

test('fresh sample timestamps do not produce stale or unknown warnings', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node,
    latest_metrics: [{ iface: 'eth0', ts: '2026-10-10T07:59:55Z' }], latest_sys_metric: { ts: '2026-10-10T07:59:00Z' } } as any);
  await mount(); expect(host.querySelector('.sampling-hint')).toBeNull();
});

test('custom edits issue no request until confirmation, then one shared group', async () => {
  await mount();
  await click('.range-btn');
  const inputs = [...host.querySelectorAll<HTMLInputElement>('.custom-range input')];
  inputs[0]!.value = '2026-10-09T00:00'; inputs[0]!.dispatchEvent(new Event('input', { bubbles: true })); inputs[0]!.dispatchEvent(new Event('change', { bubbles: true })); await settle();
  inputs[1]!.value = '2026-10-10T00:00'; inputs[1]!.dispatchEvent(new Event('input', { bubbles: true })); inputs[1]!.dispatchEvent(new Event('change', { bubbles: true })); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  await button('确定', '.custom-range button');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(host.querySelector('.preset-btn')?.textContent).toContain('自定义');
});

test('node change aborts old history and paints the new mounted chart without stale replies', async () => {
  await mount();
  const oldChart = trafficChart();
  const oldHistory = deferred<any[]>(); vi.mocked(api.getNodeMetrics).mockReturnValueOnce(oldHistory.promise);
  await preset('6小时');
  const oldSignal = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.signal!;
  const newDetail = deferred<any>(); vi.mocked(api.getNodeDetail).mockReturnValueOnce(newDetail.promise);
  id.value = 8; await settle();
  expect(oldSignal.aborted).toBe(true);
  newDetail.resolve({ ...node, id: 8, name: 'New server' }); await settle();
  expect(host.querySelector('.d-head .name')?.textContent).toBe('New server');
  expect(oldChart.dispose).toHaveBeenCalledTimes(1);
  expect(trafficChart()).toBeTruthy();
  expect(trafficChart()).not.toBe(oldChart);
  const current = option();
  oldHistory.resolve([{ ts: '2026-10-10T07:59:55Z', rx_delta: 99999, tx_delta: 0 }]); await settle();
  expect(option()).toBe(current);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(3);
});

test('live history failure also exhausts a bounded recovery budget without a restart loop', async () => {
  await mount();
  vi.mocked(api.getNodeMetrics).mockRejectedValue(new Error('timeout'));
  await click('.live-btn');
  await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(5);
  expect(host.textContent).toContain('自动重试已暂停');
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(5);
  vi.mocked(api.getNodeMetrics).mockResolvedValue([]);
  await button('重试历史');
  expect(host.textContent).not.toContain('历史数据加载失败');
  const count = vi.mocked(api.getNodeMetrics).mock.calls.length;
  await vi.advanceTimersByTimeAsync(3000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(count + 1);
});

test('hidden page aborts slow history and resumes one group without reviving after unmount', async () => {
  const pending = deferred<any[]>(); vi.mocked(api.getNodeMetrics).mockReturnValueOnce(pending.promise);
  await mount();
  const signal = vi.mocked(api.getNodeMetrics).mock.calls[0]![1]!.signal!;
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(signal.aborted).toBe(true);
  pending.resolve([]); await settle();
  await vi.advanceTimersByTimeAsync(30000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(option().series[0].data).toEqual([1]);
  app?.unmount(); app = undefined;
  await vi.advanceTimersByTimeAsync(30000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
});

test('online heartbeat never hides stale or unknown traffic and system sampling', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, last_seen_at: '2026-10-10T08:00:00Z',
    latest_metrics: [{ iface: 'eth0', ts: '2026-10-07T19:54:00Z' }], latest_sys_metric: { ts: '2026-10-07T19:54:00Z' } } as any);
  await mount();
  expect(host.querySelector('.badge')?.textContent).toBe('在线');
  expect(host.querySelector('.sampling-hint')?.textContent || '').toContain('流量采样已过期');
  expect(host.querySelector('.sampling-hint')?.textContent || '').toContain('系统采样已过期');
  expect(host.querySelector('.sampling-hint')?.textContent || '').toContain('10/08 03:54');
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, latest_sys_metric: null } as any);
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.querySelector('.sampling-hint')?.textContent || '').toContain('流量采样状态未知');
  expect(host.querySelector('.sampling-hint')?.textContent || '').toContain('系统采样状态未知');
});

test('monitor list distinguishes pending, failure and confirmed empty with independent retry', async () => {
  const pending = deferred<any[]>(); vi.mocked(api.listMonitors).mockReturnValueOnce(pending.promise);
  await mount();
  expect(host.querySelector('.mon-list')?.textContent).toContain('正在加载监控项');
  expect(host.querySelector('.mon-list')?.textContent).not.toContain('还没有监控项');
  pending.reject(new Error('timeout')); await settle();
  expect(host.querySelector('.mon-list')?.textContent).toContain('监控项加载失败');
  await button('重试监控项');
  expect(host.querySelector('.mon-list')?.textContent).toContain('还没有监控项');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test('failed wider-window traffic keeps original plot units and raw P95', async () => {
  await mount();
  expect(option().series[0].data).toEqual([1]);
  vi.mocked(api.getNodeMetrics).mockRejectedValueOnce(new Error('timeout'));
  await preset('24小时');
  expect(vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.step).toBe(30);
  expect(option().series[0].data).toEqual([1]);
  expect(host.querySelector('.stats-bar .stat-item b')?.textContent).toBe('1.00 Mbps');
});

test('history retries are bounded to three attempts and manual retry starts a new budget', async () => {
  vi.mocked(api.getNodeMetrics).mockRejectedValue(new Error('timeout'));
  await mount();
  await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(4);
  expect(host.textContent).toContain('自动重试已暂停');
  vi.mocked(api.getNodeMetrics).mockResolvedValue([]);
  await button('重试历史');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(5);
  expect(host.textContent).not.toContain('历史数据加载失败');
});

test.each([
  ['本月', '2026-10-01T00:00:00.000Z', '2026-10-10T08:00:00.000Z'],
  ['上月', '2026-09-01T00:00:00.000Z', '2026-10-01T00:00:00.000Z'],
])('%s timezone changes requery the calendar boundaries without changing range', async (text, start, end) => {
  await mount(); await preset(text);
  const count = vi.mocked(api.getNodeMetrics).mock.calls.length;
  await button('UTC+8 ▾'); await button('UTC+0', '.tz-menu button');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(count + 1);
  const traffic = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!;
  expect([traffic.start, traffic.end]).toEqual([start, end]);
  const sys = vi.mocked(api.getNodeSysMetrics).mock.calls.at(-1)![1]!;
  const exact = vi.mocked(api.getTrafficStats).mock.calls.at(-1)![1]!;
  expect([sys.start, sys.end]).toEqual([start, end]);
  expect([exact.start, exact.end]).toEqual([start, end]);
  expect(host.querySelector('.preset-btn')?.textContent).toContain(text);
});

test.each(['1小时', '本月'])('%s refresh advances one shared window for traffic, system and exact stats', async text => {
  await mount(); await preset(text);
  const before = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.end;
  vi.setSystemTime(new Date('2026-10-11T00:01:00Z'));
  await preset(text);
  const traffic = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!;
  const sys = vi.mocked(api.getNodeSysMetrics).mock.calls.at(-1)![1]!;
  const exact = vi.mocked(api.getTrafficStats).mock.calls.at(-1)![1]!;
  expect(traffic.end).not.toBe(before);
  expect(traffic.end).toBe('2026-10-11T00:01:00.000Z');
  expect([sys.start, sys.end]).toEqual([traffic.start, traffic.end]);
  expect([exact.start, exact.end]).toEqual([traffic.start, traffic.end]);
});

test('failed initial history retries after completion and retains valid plots on later failure', async () => {
  vi.mocked(api.getNodeMetrics).mockRejectedValueOnce(new Error('timeout'));
  vi.mocked(api.getNodeSysMetrics).mockRejectedValueOnce(new Error('timeout'));
  vi.mocked(api.getTrafficStats).mockRejectedValueOnce(new Error('timeout'));
  await mount();
  expect(host.textContent).toContain('历史数据加载失败');
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(api.getNodeSysMetrics).toHaveBeenCalledTimes(2);
  expect(api.getTrafficStats).toHaveBeenCalledTimes(2);
  expect(option().series[0].data).toEqual([1]);
  expect(host.textContent).not.toContain('历史数据加载失败');
  const previous = option();
  vi.mocked(api.getNodeMetrics).mockRejectedValueOnce(new Error('timeout'));
  vi.mocked(api.getNodeSysMetrics).mockRejectedValueOnce(new Error('timeout'));
  vi.mocked(api.getTrafficStats).mockRejectedValueOnce(new Error('timeout'));
  await preset('1小时');
  expect(option().series[0].data).toEqual(previous.series[0].data);
  expect(host.querySelector('.stats-bar .stat-item b')?.textContent).toBe('1.00 Mbps');
  expect(host.textContent).toContain('历史数据加载失败');
  const pending = deferred<any[]>(); vi.mocked(api.getNodeMetrics).mockReturnValueOnce(pending.promise);
  await button('重试历史'); await button('重试历史');
  await vi.advanceTimersByTimeAsync(6000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(4);
  pending.resolve([]); await settle();
  expect(host.textContent).not.toContain('历史数据加载失败');
});

test('detail pending and failure are explicit; retry recovers history once', async () => {
  const first = deferred<any>(); vi.mocked(api.getNodeDetail).mockReturnValueOnce(first.promise);
  await mount();
  expect(host.textContent).toContain('正在加载服务器详情');
  expect(host.textContent).not.toContain('等待 agent 上报系统信息');
  first.reject(new Error('timeout')); await settle();
  expect(host.textContent).toContain('服务器详情加载失败');
  const retry = deferred<any>(); vi.mocked(api.getNodeDetail).mockReturnValueOnce(retry.promise);
  await button('重试详情'); await button('重试详情');
  expect(api.getNodeDetail).toHaveBeenCalledTimes(2);
  retry.resolve(node); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain('服务器详情加载失败');
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test('detail starts history immediately without waiting for slow monitor list', async () => {
  const slow = deferred<any[]>(); vi.mocked(api.listMonitors).mockReturnValueOnce(slow.promise);
  await mount();
  expect(host.querySelector('.d-head .name')?.textContent).toBe('Test server');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(api.getNodeSysMetrics).toHaveBeenCalledTimes(1);
  expect(api.getTrafficStats).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain('网卡（1）');
  expect(option().series[0].data).toEqual([1]);
  expect(host.querySelector('.stats-bar .stat-item b')?.textContent).toBe('1.00 Mbps');
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(api.getNodeDetail).toHaveBeenCalledTimes(2);
  expect(api.listMonitors).toHaveBeenCalledTimes(1);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  slow.resolve([]); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test('nodes distinguish initial pending from confirmed empty', async () => {
  const pending = deferred<any[]>(); vi.mocked(api.listNodes).mockReturnValueOnce(pending.promise);
  await mount(Nodes);
  expect(host.textContent).toContain('正在加载服务器');
  expect(host.textContent).not.toContain('添加第一台');
  expect(host.querySelector('.sub')?.textContent || '').not.toContain('0 台纳管');
  pending.resolve([]); await settle();
  expect(host.textContent).toContain('添加第一台');
  expect(host.textContent).not.toContain('正在加载服务器');
});

test('nodes show actionable failure and coalesce retry while preserving last rows', async () => {
  vi.mocked(api.listNodes).mockRejectedValueOnce(new Error('timeout'));
  await mount(Nodes);
  expect(host.textContent).toContain('服务器加载失败');
  expect(host.textContent).not.toContain('添加第一台');
  const pending = deferred<any[]>(); vi.mocked(api.listNodes).mockReturnValueOnce(pending.promise);
  await button('重试'); await button('重试');
  expect(api.listNodes).toHaveBeenCalledTimes(2);
  pending.resolve([node]); await settle();
  expect(host.querySelector('.card .name')?.textContent).toBe('Test server');
  vi.mocked(api.listNodes).mockRejectedValueOnce(new Error('timeout'));
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.textContent).toContain('服务器加载失败');
  expect(host.querySelector('.card .name')?.textContent).toBe('Test server');
});
