import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, h, nextTick, ref } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import Detail from './NodeDetailView.vue';
import * as api from '../../api/servers';
import { hardware, node } from './hardware.testFixtures';
import type { HardwareInfo } from '../../api/servers';

const charts = vi.hoisted(() => [] as ReturnType<typeof vi.fn>[]);
vi.mock('./chartRuntime', () => ({
  init: () => { const setOption = vi.fn(); charts.push(setOption); return { setOption, dispose: vi.fn(), resize: vi.fn() }; },
  getInstanceByDom: () => undefined,
}));
vi.mock('../../api/servers', async original => ({
  ...await original<typeof import('../../api/servers')>(),
  getNodeDetail: vi.fn(), listMonitors: vi.fn(),
  getNodeMetrics: vi.fn(), getNodeSysMetrics: vi.fn(), getTrafficStats: vi.fn(),
  latestNetTask: vi.fn(),
}));
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
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-10T08:00:00Z')); vi.resetAllMocks(); charts.length = 0; id.value = 7;
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  vi.mocked(api.getNodeDetail).mockResolvedValue(node as any);
  vi.mocked(api.listMonitors).mockResolvedValue([]);
  vi.mocked(api.getNodeMetrics).mockResolvedValue([]);
  vi.mocked(api.getNodeSysMetrics).mockResolvedValue([]);
  vi.mocked(api.getTrafficStats).mockResolvedValue(null as any);
  vi.mocked(api.latestNetTask).mockResolvedValue({ created_at: new Date().toISOString(), result_json: { ufw: {}, rules: [], marks: [], tables: {} } } as any);
});
afterEach(() => { app?.unmount(); app = undefined; host?.remove(); vi.useRealTimers(); });

test('detail renders CPU, every GPU metric and board sensors from the existing detail response including zeros', async () => {
  await mount();
  const panel = host.querySelector('[aria-label="硬件信息"]');
  expect(panel).not.toBeNull();
  const text = panel!.textContent!;
  for (const value of ['AMD Ryzen 7 9700X', '8 核 / 16 线程', '52.5 °C', '4200 MHz', '5500 MHz',
    'NVIDIA GeForce RTX 5060', '43 °C', '2500 MHz', '14001 MHz', '0 %', '0 / 8192 MiB', '12.5 W',
    'System', '35 °C', 'Chassis', '0 RPM', 'nvidia-smi']) expect(text).toContain(value);
  expect(panel!.querySelector('time')?.getAttribute('datetime')).toBe(hardware.sampled_at);
  expect(text).toContain('最近采样');
  expect(api.getNodeDetail).toHaveBeenCalledTimes(1);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(charts).toHaveLength(2);
});

test('legacy agents explicitly show hardware not read without inventing GPU absence or blocking charts', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { cpu_model: 'Legacy CPU' } } as any);
  await mount();
  const text = host.querySelector('[aria-label="硬件信息"]')!.textContent!;
  expect(text).toContain('未读取');
  expect(text).toContain('Agent 尚未上报硬件信息');
  expect(text).not.toContain('无 GPU');
  expect(text).not.toContain('0 °C');
  expect(host.textContent).toContain('Legacy CPU');
  expect(charts).toHaveLength(2);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test.each([
  ['no_nvidia_gpu', '未检测到 NVIDIA GPU'],
  ['nvidia_smi_failed', 'GPU 查询失败'],
  ['nvidia_smi_missing', 'GPU 不可用 · 未安装 nvidia-smi'],
  ['unavailable', 'GPU 不可用'],
  ['driver_not_ready', 'GPU 未读取 · driver_not_ready'],
])('empty GPU list preserves availability meaning: %s', async (status, message) => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: {
    ...hardware, gpus: [], sensors: [], cpu: { ...hardware.cpu, temperature_c: null },
    availability: { cpu_temperature: 'unavailable', gpu: status },
  } } } as any);
  await mount();
  const panel = host.querySelector('[aria-label="硬件信息"]')!;
  expect(panel.textContent).toContain(message);
  expect(panel.querySelector('.cpu-card')?.textContent).toContain('不可用');
  expect(panel.textContent).not.toContain('0 °C');
  expect(panel.querySelector('.sensors-card')).toBeNull();
  if (status !== 'no_nvidia_gpu') expect(panel.textContent).not.toContain('未检测到 NVIDIA GPU');
});

test.each([
  ['offline', '2026-10-10T07:59:00Z', '节点离线'],
  ['online', '2026-10-10T07:56:59Z', '采样已过期'],
  ['online', 'invalid', '采样时间未知'],
])('hardware is not presented as current when %s / %s', async (status, sampledAt, reason) => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, status,
    sys_info: { hardware: { ...hardware, sampled_at: sampledAt } } } as any);
  await mount();
  const text = host.querySelector('[aria-label="硬件信息"]')!.textContent!;
  expect(text).toContain('上次采样 · 非实时');
  expect(text).toContain(reason);
  expect(text).not.toContain('最近采样');
  expect(text).not.toContain('Invalid Date');
  expect(text).toContain('52.5 °C');
});

test('clock aging and failed detail polls retain the previous sample as non-live, then recover without reloading charts', async () => {
  await mount();
  vi.mocked(api.getNodeDetail).mockRejectedValue(new Error('timeout'));
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('详情刷新失败');
  expect(host.querySelector('.sample-status')?.textContent).toContain('非实时');
  expect(host.textContent).toContain('RTX 5060');
  vi.mocked(api.getNodeDetail).mockResolvedValue(node as any);
  await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('采样已过期');
  const updated = { ...hardware, sampled_at: new Date().toISOString(), cpu: { ...hardware.cpu, temperature_c: 49 } };
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: updated } } as any);
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('最近采样');
  expect(host.querySelector('.cpu-card')?.textContent).toContain('49 °C');
  expect(host.textContent).not.toContain('服务器详情加载失败');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(charts).toHaveLength(2);
});

test('hardware aging continues while an existing detail request is stuck without adding another poller', async () => {
  await mount();
  vi.mocked(api.getNodeDetail).mockReturnValueOnce(new Promise(() => {}));
  await vi.advanceTimersByTimeAsync(150000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('采样已过期');
  expect(host.querySelector('.sample-status')?.textContent).toContain('非实时');
  expect(api.getNodeDetail).toHaveBeenCalledTimes(2);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

// Regression coverage of the already-tested nullable formatter and GPU loop.
test('all nullable readings remain unread, multiple GPUs keep identities and one unsupported field does not mask valid readings', async () => {
  const partial: HardwareInfo = { ...hardware,
    cpu: { model: null, physical_cores: null, logical_cores: null, frequency_mhz: null,
      max_frequency_mhz: null, temperature_c: null, temperature_source: null, frequency_source: null },
    gpus: [
      { id: 'GPU-empty', name: 'Unsupported GPU', temperature_c: null, graphics_clock_mhz: null,
        memory_clock_mhz: null, utilization_pct: null, memory_used_mib: null, memory_total_mib: null,
        power_w: null, fan_pct: null, source: 'nvidia-smi' },
      { ...hardware.gpus[0]!, temperature_c: 0, power_w: null },
    ],
    sensors: [{ name: 'Unavailable fan', kind: 'fan', value: null, unit: 'RPM', source: 'test' }],
  };
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: partial } } as any);
  await mount();
  const cpu = host.querySelector('.cpu-card')!;
  expect([...cpu.querySelectorAll('dd')].map(el => el.textContent)).toEqual(['未读取 / 未读取', '未读取', '未读取', '未读取']);
  const cards = [...host.querySelectorAll('.gpu-card')];
  expect(cards).toHaveLength(2);
  expect(cards[0]!.getAttribute('aria-label')).toBe('GPU Unsupported GPU');
  expect(cards[0]!.textContent).not.toContain('0 °C');
  expect(cards[0]!.textContent).not.toContain('0 %');
  expect(cards[0]!.textContent).not.toContain('null');
  expect(cards[1]!.textContent).toContain('0 °C');
  expect(cards[1]!.textContent).toContain('2500 MHz');
  expect(cards[1]!.textContent).toContain('功耗未读取');
  expect(host.querySelector('.sensors-card')?.textContent).toContain('Unavailable fan未读取');
});

test('switching node cannot retain old hardware or reveal it from a late detail response', async () => {
  await mount();
  let resolve!: (data: any) => void;
  vi.mocked(api.getNodeDetail).mockReturnValueOnce(new Promise<any>(done => { resolve = done; }));
  await vi.advanceTimersByTimeAsync(5000); await settle();
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, id: 8, name: 'Legacy Linux', sys_info: null } as any);
  id.value = 8; await settle();
  expect(host.textContent).not.toContain('RTX 5060');
  expect(host.querySelector('.hardware-panel')?.textContent).toContain('未读取');
  resolve(node); await settle();
  expect(host.textContent).not.toContain('RTX 5060');
  expect(host.querySelector('.name')?.textContent).toBe('Legacy Linux');
});

