import { afterEach, expect, test, vi } from 'vitest';
import { createApp, nextTick } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import Overview from './OverviewView.vue';

const chart = vi.hoisted(() => ({ resize: vi.fn(), setOption: vi.fn(), dispose: vi.fn() }));
vi.mock('./chartRuntime', () => ({ init: () => chart, getInstanceByDom: () => undefined }));
vi.mock('./ServerWorldMap.vue', () => ({ __esModule: true, default: { render: () => null } }));
vi.mock('../../api/servers', () => ({
  listNodes: async () => [{ id: 7, name: 'geometry', status: 'online', platform: 'linux' }],
  getNodeDetail: async () => ({ id: 7, interfaces: { eth0: { up: true, is_default: true } } }),
  getNodeMetrics: async () => [], listMonitors: async () => [], listMonitorGroups: async () => [],
  getMonitorSeries: async () => [], listAlertIncidents: async () => ({ items: [], untracked: [] }),
}));
let app: ReturnType<typeof createApp> | undefined;
let host: HTMLElement | undefined;
afterEach(() => {
  app?.unmount(); app = undefined; host?.remove();
  vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});

test('traffic resize delegates CSS layout measurement instead of feeding zoomed viewport bounds back as CSS pixels', async () => {
  vi.useFakeTimers(); chart.resize.mockClear();
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  let notify!: ResizeObserverCallback;
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { notify = callback; }
    observe() {} disconnect() {}
  });
  // CSS 125%: 246.4×200 layout pixels become 308×250 viewport pixels.
  // ECharts' own resize() uses unscaled client/computed CSS dimensions.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 308, height: 250 } as DOMRect);
  host = document.createElement('div'); document.body.append(host);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
  await router.push('/'); app = createApp(Overview); app.use(router); app.mount(host);
  const settle = async () => { for (let i = 0; i < 40; i++) { await Promise.resolve(); await nextTick(); } };
  await settle();
  expect(chart.resize).toHaveBeenCalled();
  expect(chart.resize.mock.calls.every(args => args.length === 0)).toBe(true);
  chart.resize.mockClear(); notify([], {} as ResizeObserver); await settle();
  expect(chart.resize).toHaveBeenCalledWith();
  chart.resize.mockClear(); window.dispatchEvent(new Event('resize')); await settle();
  expect(chart.resize).toHaveBeenCalledWith();
});
