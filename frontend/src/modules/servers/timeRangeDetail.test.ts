import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, nextTick, h, ref } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Detail from './NodeDetailView.vue';
import * as api from '../../api/servers';

const charts = vi.hoisted(() => [] as { el: HTMLElement; setOption: ReturnType<typeof vi.fn> }[]);
vi.mock('./NodeComponents.vue', () => ({ default: { render: () => null } }));
vi.mock('./chartRuntime', () => ({
  init: (el: HTMLElement) => { const chart = { el, setOption: vi.fn(), dispose: vi.fn(), resize: vi.fn() }; charts.push(chart); return chart; },
  getInstanceByDom: () => undefined,
}));
vi.mock('../../api/servers', async original => ({
  ...await original<typeof import('../../api/servers')>(),
  getNodeDetail: vi.fn(), listMonitors: vi.fn(), getNodeMetrics: vi.fn(),
  getNodeSysMetrics: vi.fn(), getTrafficStats: vi.fn(), updateNodeIfaces: vi.fn(),
  getHost: vi.fn(async () => null), getPublicHost: vi.fn(async () => ({ value: '' })),
  latestNetTask: vi.fn(async () => ({ created_at: new Date().toISOString(), result_json: { ufw: {}, rules: [], marks: [], tables: {} } })),
}));
const node = { id: 7, name: 'Time fixture server', status: 'online', platform: 'linux', net_type: 'internal',
  interfaces: { eth0: { is_default: true, up: true } }, storage: [], latest_metrics: [] };
let app: ReturnType<typeof createApp> | undefined;
let host: HTMLElement;
const id = ref(7);
async function settle() { for (let i = 0; i < 50; i++) await Promise.resolve(); await nextTick(); }
async function mount() {
  host = document.createElement('div'); document.body.append(host);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
  await router.push('/'); await router.isReady();
  app = createApp({ render: () => h(Detail, { nodeId: id.value }) }); app.use(router); app.mount(host); await settle();
}
async function click(selector: string) { const el = host.querySelector<HTMLElement>(selector); expect(el, selector).not.toBeNull(); el!.click(); await settle(); }
async function button(text: string, selector = 'button') { const el = [...host.querySelectorAll<HTMLElement>(selector)].find(e => e.textContent?.trim() === text); expect(el, text).toBeTruthy(); el!.click(); await settle(); }
async function preset(text: string) { await click('.preset-btn'); await button(text, '.pop-item'); }
function inputs() { return [...host.querySelectorAll<HTMLInputElement>('.chart-toolbar input[type="datetime-local"]')]; }
async function edit(index: number, value: string) { const input = inputs()[index]!; expect(input).toBeTruthy(); input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })); await settle(); }
function option() { return charts.find(c => c.el === host.querySelector('.chart'))!.setOption.mock.calls.at(-1)![0]; }
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-10T08:00:00Z')); vi.resetAllMocks(); charts.length = 0; id.value = 7;
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  vi.mocked(api.getNodeDetail).mockResolvedValue(node as any);
  vi.mocked(api.listMonitors).mockResolvedValue([]);
  vi.mocked(api.getNodeMetrics).mockResolvedValue([{ ts: '2026-10-10T07:59:55Z', rx_delta: 625000, tx_delta: 0 }] as any);
  vi.mocked(api.getNodeSysMetrics).mockResolvedValue([{ ts: '2026-10-10T07:59:55Z', cpu_pct: 20, mem_pct: 40, disk_pct: 30 }] as any);
  vi.mocked(api.getTrafficStats).mockResolvedValue({ sample_count: 10, rx_95: 625000, tx_95: 0, rx_total: 100, tx_total: 0, rx_max: 625000, rx_min: 0, tx_max: 0, tx_min: 0 });
});
afterEach(() => { app?.unmount(); app = undefined; host?.remove(); vi.unstubAllGlobals(); vi.useRealTimers(); });

test('editing immediately exits live and debounces one shared valid request without blur', async () => {
  await mount(); await click('.live-btn');
  const before = vi.mocked(api.getNodeMetrics).mock.calls.length;
  await edit(0, '2026-10-09T00:00');
  expect(host.querySelector('.preset-btn')?.textContent).toContain('自定义');
  expect(host.querySelector('.live-btn')?.classList.contains('on')).toBe(false);
  await vi.advanceTimersByTimeAsync(150);
  await edit(1, '2026-10-10T00:00');
  await vi.advanceTimersByTimeAsync(249); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(before);
  await vi.advanceTimersByTimeAsync(1); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(before + 1);
  expect(api.getNodeSysMetrics).toHaveBeenCalledTimes(before + 1);
  expect(api.getTrafficStats).toHaveBeenCalledTimes(before + 1);
  for (const request of [api.getNodeMetrics, api.getNodeSysMetrics, api.getTrafficStats]) {
    const opts = vi.mocked(request).mock.calls.at(-1)![1]!;
    expect([opts.start, opts.end]).toEqual(['2026-10-08T16:00:00.000Z', '2026-10-09T16:00:00.000Z']);
  }
  await vi.advanceTimersByTimeAsync(4000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(before + 1);
});

test('invalid or partial drafts retain plots and never query even on retry or visibility', async () => {
  await mount(); const previous = option();
  await edit(0, '2026-10-11T00:00');
  expect(host.querySelector('.range-error')?.textContent).toContain('结束时间须晚于开始时间');
  await vi.advanceTimersByTimeAsync(10000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(option()).toBe(previous);
  await edit(0, '');
  expect(host.querySelector('.range-error')?.textContent).toContain('完整');
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(inputs()[0]!.value).toBe('');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(option()).toBe(previous);
  await edit(0, '2026-10-09T00:00');
  await vi.advanceTimersByTimeAsync(250); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(host.querySelector('.range-error')).toBeNull();
});

test.each([
  ['UTC+0', '2026-10-10T07:00', '2026-10-09T00:00:00.000Z'],
  ['UTC+1', '2026-10-10T08:00', '2026-10-08T23:00:00.000Z'],
  ['UTC+9', '2026-10-10T16:00', '2026-10-08T15:00:00.000Z'],
  ['UTC-5', '2026-10-10T02:00', '2026-10-09T05:00:00.000Z'],
  ['UTC-8', '2026-10-09T23:00', '2026-10-09T08:00:00.000Z'],
])('manual date input uses displayed %s instead of the browser timezone', async (tz, initial, start) => {
  await mount(); await button('UTC+8 ▾'); await button(tz, '.tz-menu button');
  expect(inputs()[0]!.value).toBe(initial);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  await edit(0, '2026-10-09T00:00'); await edit(1, '2026-10-10T00:00');
  await vi.advanceTimersByTimeAsync(250); await settle();
  expect(vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.start).toBe(start);
  const count = vi.mocked(api.getNodeMetrics).mock.calls.length;
  await button(`${tz} ▾`); await button('UTC+8', '.tz-menu button');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(count);
  // Changing the display timezone preserves the exact custom UTC window.
  await button('网卡（1）▾'); await click('.iface-menu input');
  expect(vi.mocked(api.getNodeSysMetrics).mock.calls.at(-1)![1]!.start).toBe(start);
});

test('hidden debounce resumes exactly once with the edited window on return', async () => {
  await mount(); await edit(0, '2026-10-09T00:00');
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  await vi.advanceTimersByTimeAsync(1000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.start).toBe('2026-10-08T16:00:00.000Z');
});

test('node navigation cancels pending edits rather than double fetching the new node', async () => {
  await mount(); await edit(0, '2026-10-09T00:00');
  id.value = 8; await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![0]).toBe(8);
});

test('unmount aborts the custom group and cannot revive after a late failed reply', async () => {
  await mount();
  let reject!: (error: Error) => void;
  vi.mocked(api.getNodeMetrics).mockReturnValueOnce(new Promise((_yes, no) => { reject = no; }));
  await edit(0, '2026-10-09T00:00'); await vi.advanceTimersByTimeAsync(250); await settle();
  const signal = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!.signal!;
  app!.unmount(); app = undefined;
  expect(signal.aborted).toBe(true);
  reject(new Error('late timeout')); await settle();
  await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
});

test('chart container resize repairs hidden-tab canvases without requery and disconnects on leave', async () => {
  let notify!: ResizeObserverCallback;
  const observe = vi.fn(), disconnect = vi.fn();
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { notify = callback; }
    observe = observe; disconnect = disconnect;
  });
  await mount();
  expect(observe.mock.calls.map(c => c[0])).toEqual([...host.querySelectorAll('.chart')]);
  for (const el of host.querySelectorAll('.chart')) Object.defineProperty(el, 'clientWidth', { value: 934 });
  notify([], {} as ResizeObserver); await settle();
  for (const chart of charts) expect((chart as any).resize).toHaveBeenCalled();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  app!.unmount(); app = undefined;
  expect(disconnect).toHaveBeenCalled();
  vi.unstubAllGlobals();
});

test.each([
  ['本月', '2026-10-01T00:00', '2026-10-10T16:00', '2026-10-01T00:00:00.000Z', '2026-10-10T08:00:00.000Z'],
  ['上月', '2026-09-01T00:00', '2026-10-01T00:00', '2026-09-01T00:00:00.000Z', '2026-10-01T00:00:00.000Z'],
])('%s synchronizes drafts and requeries exactly one calendar group on timezone change', async (text, startInput, endInput, start, end) => {
  await mount(); await preset(text);
  expect(inputs().map(i => i.value)).toEqual([startInput, endInput]);
  const count = vi.mocked(api.getNodeMetrics).mock.calls.length;
  await button('UTC+8 ▾'); await button('UTC+0', '.tz-menu button');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(count + 1);
  for (const request of [api.getNodeMetrics, api.getNodeSysMetrics, api.getTrafficStats]) {
    const opts = vi.mocked(request).mock.calls.at(-1)![1]!;
    expect([opts.start, opts.end]).toEqual([start, end]);
  }
  expect(inputs()[0]!.value).toBe(start.slice(0, 16));
  expect(inputs()[1]!.value).toBe(end.slice(0, 16));
  expect(host.querySelector('.preset-btn')?.textContent).toContain(text);
});

test.each(['1小时', '本月'])('%s reselection captures the new clock once and does not turn custom', async text => {
  await mount(); await preset(text);
  vi.setSystemTime(new Date('2026-11-01T00:01:19Z'));
  await preset(text);
  const traffic = vi.mocked(api.getNodeMetrics).mock.calls.at(-1)![1]!;
  expect(traffic.end).toBe('2026-11-01T00:01:19.000Z');
  for (const request of [api.getNodeSysMetrics, api.getTrafficStats]) {
    const opts = vi.mocked(request).mock.calls.at(-1)![1]!;
    expect([opts.start, opts.end]).toEqual([traffic.start, traffic.end]);
  }
  expect(inputs()[1]!.value).toBe('2026-11-01T08:01');
  expect(host.querySelector('.preset-btn')?.textContent).toContain(text);
});

test('selecting a preset cancels pending custom work and repeated status polls do not overwrite drafts', async () => {
  await mount(); await edit(0, '2026-10-09T00:00'); await preset('6小时');
  expect(inputs().map(i => i.value)).toEqual(['2026-10-10T10:00', '2026-10-10T16:00']);
  await vi.advanceTimersByTimeAsync(1000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  await edit(0, '');
  await vi.advanceTimersByTimeAsync(10000); await settle();
  expect(inputs()[0]!.value).toBe('');
  expect(inputs()[1]!.value).toBe('2026-10-10T16:00');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  await button('UTC+8 ▾'); await button('UTC+0', '.tz-menu button');
  expect(inputs()[0]!.value).toBe('');
  expect(inputs()[1]!.value).toBe('2026-10-10T08:00');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
});

test('opening/cancelling a native picker without any changed input leaves preset and live untouched', async () => {
  await mount(); await click('.live-btn');
  const count = vi.mocked(api.getNodeMetrics).mock.calls.length;
  const before = inputs()[0]!.value;
  inputs()[0]!.click(); inputs()[0]!.dispatchEvent(new Event('input', { bubbles: true })); await settle();
  expect(inputs()[0]!.value).toBe(before);
  expect(host.querySelector('.live-btn')?.classList.contains('on')).toBe(true);
  expect(host.querySelector('.preset-btn')?.textContent).toContain('1小时');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(count);
});

test('invalid draft also blocks the manual history retry without losing the valid plot', async () => {
  await mount();
  vi.mocked(api.getNodeMetrics).mockRejectedValueOnce(new Error('timeout'));
  await preset('6小时'); const previous = option();
  await edit(0, ''); await button('重试历史');
  await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(2);
  expect(option()).toBe(previous);
});

test('a new valid edit resumes after hiding even when the previous retry budget was exhausted', async () => {
  vi.mocked(api.getNodeMetrics).mockRejectedValue(new Error('timeout'));
  await mount(); await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(4);
  vi.mocked(api.getNodeMetrics).mockResolvedValue([]);
  await edit(0, '2026-10-09T00:00');
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  await vi.advanceTimersByTimeAsync(1000);
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange')); await settle();
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(5);
  expect(host.textContent).not.toContain('历史数据加载失败');
});

test.each(['自定义', '6小时'])('leaving live restores the %s history window in inputs and every query', async text => {
  await mount();
  if (text === '自定义') {
    await edit(0, '2026-10-09T00:00'); await edit(1, '2026-10-10T00:00');
    await vi.advanceTimersByTimeAsync(250); await settle();
  } else await preset(text);
  const historical = inputs().map(i => i.value);
  await click('.live-btn');
  expect(inputs().map(i => i.value)).not.toEqual(historical);
  const count = vi.mocked(api.getNodeSysMetrics).mock.calls.length;
  await click('.live-btn');
  expect(inputs().map(i => i.value)).toEqual(historical);
  expect(api.getNodeSysMetrics).toHaveBeenCalledTimes(count + 1);
  expect(host.querySelector('.preset-btn')?.textContent).toContain(text);
  for (const request of [api.getNodeMetrics, api.getNodeSysMetrics, api.getTrafficStats]) {
    const opts = vi.mocked(request).mock.calls.at(-1)![1]!;
    expect([opts.start, opts.end]).toEqual(historical.map(value => new Date(Date.parse(value + 'Z') - 480 * 60000).toISOString()));
  }
  await button('网卡（1）▾'); await click('.iface-menu input');
  expect(inputs().map(i => i.value)).toEqual(historical);
  expect(vi.mocked(api.getNodeSysMetrics).mock.calls.at(-1)![1]!.start)
    .toBe(new Date(Date.parse(historical[0] + 'Z') - 480 * 60000).toISOString());
  const finalCount = vi.mocked(api.getNodeSysMetrics).mock.calls.length;
  await vi.advanceTimersByTimeAsync(4000); await settle();
  expect(api.getNodeSysMetrics).toHaveBeenCalledTimes(finalCount);
});

test('one inline range remains the only date editor when clicked or custom is selected', async () => {
  await mount();
  expect(inputs()).toHaveLength(2);
  expect(inputs().map(i => i.value)).toEqual(['2026-10-10T15:00', '2026-10-10T16:00']);
  inputs()[0]!.click(); await settle();
  await preset('自定义');
  expect(host.querySelectorAll('input[type="datetime-local"]')).toHaveLength(2);
  expect(host.querySelector('.range-btn')).toBeNull();
  expect(host.querySelector('.custom-range')).toBeNull();
  expect(inputs()[0]!.getAttribute('aria-label')).toContain('开始');
  expect(inputs()[0]!.getAttribute('aria-label')).toContain('UTC+8');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});
