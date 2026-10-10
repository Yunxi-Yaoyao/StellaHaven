import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createApp, h, nextTick, ref, type Component } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import Detail from './NodeDetailView.vue';
import Nodes from './NodesView.vue';
import HardwarePanel from './HardwareInfoPanel.vue';
vi.mock('./NodeComponents.vue', () => ({ default: { render: () => null } }));
import * as api from '../../api/servers';
import { hardware, node } from './hardware.testFixtures';
import type { HardwareInfo } from '../../api/servers';
import captured5060 from './fixtures/node-57.captured.json';
import capturedNAS from './fixtures/node-55.captured.json';
import nasContract from './fixtures/node-55.contract-fixture.json';
import windowsContract from './fixtures/node-57.contract-fixture.json';

const charts = vi.hoisted(() => [] as ReturnType<typeof vi.fn>[]);
vi.mock('./chartRuntime', () => ({
  init: () => { const setOption = vi.fn(); charts.push(setOption); return { setOption, dispose: vi.fn(), resize: vi.fn() }; },
  getInstanceByDom: () => undefined,
}));
vi.mock('../../api/servers', async original => ({
  ...await original<typeof import('../../api/servers')>(),
  getNodeDetail: vi.fn(), listMonitors: vi.fn(),
  getNodeMetrics: vi.fn(), getNodeSysMetrics: vi.fn(), getTrafficStats: vi.fn(),
  latestNetTask: vi.fn(), listNodes: vi.fn(), getHost: vi.fn(), getPublicHost: vi.fn(),
}));
let app: ReturnType<typeof createApp> | undefined;
let host: HTMLElement;
const id = ref(7);
async function settle() { for (let i = 0; i < 50; i++) await Promise.resolve(); await nextTick(); }
async function mount(component: Component = Detail, props: Record<string, unknown> = {}) {
  host = document.createElement('div'); document.body.append(host);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] });
  await router.push('/'); await router.isReady();
  app = createApp({ render: () => h(component, { nodeId: id.value, ...props }) }); app.use(router); app.mount(host); await settle();
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-10T08:00:00Z')); vi.resetAllMocks(); charts.length = 0; id.value = 7;
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  vi.mocked(api.getNodeDetail).mockResolvedValue(node as any);
  vi.mocked(api.listMonitors).mockResolvedValue([]);
  vi.mocked(api.getHost).mockResolvedValue({ installed: true } as any);
  vi.mocked(api.getPublicHost).mockResolvedValue({ value: '' });
  vi.mocked(api.listNodes).mockResolvedValue([]);
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
  for (const value of ['AMD Ryzen 7 9700X', '8 核 / 16 线程', '52.5 °C', '4200 MHz',
    'NVIDIA GeForce RTX 5060', '43 °C', '2500 MHz', '14001 MHz', '0 %', '0 / 8192 MiB', '12.5 W',
    '系统温度 · System', '35 °C', '机箱风扇 · Chassis', '0 RPM', '转速比例']) expect(text).toContain(value);
  for (const diagnostic of ['5500 MHz', '来源', 'nvidia-smi', '最近采样', '未读取']) expect(text).not.toContain(diagnostic);
  expect(panel!.querySelector('time')).toBeNull();
  expect(panel!.querySelectorAll('.metric-primary')).toHaveLength(3);
  expect(api.getNodeDetail).toHaveBeenCalledTimes(1);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(charts).toHaveLength(2);
});

test('legacy agents show uncollected hardware without inventing GPU absence or blocking charts', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { cpu_model: 'Legacy CPU' } } as any);
  await mount();
  const text = host.querySelector('[aria-label="硬件信息"]')!.textContent!;
  expect(text).toContain('硬件尚未采集');
  expect(text).not.toContain('未读取');
  expect(text).not.toContain('无 GPU');
  expect(text).not.toContain('0 °C');
  expect(host.textContent).toContain('Legacy CPU');
  expect(charts).toHaveLength(2);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test.each([
  ['no_nvidia_gpu', '未检测到 NVIDIA GPU'],
  ['nvidia_smi_failed', '刷新失败'],
  ['nvidia_smi_missing', 'GPU 遥测未采集'],
  ['unavailable', 'GPU 状态未知'],
  ['driver_not_ready', '刷新失败'],
])('empty GPU list preserves availability meaning: %s', async (status, message) => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: {
    ...hardware, gpus: [], sensors: [], cpu: { ...hardware.cpu, temperature_c: null },
    availability: { cpu_temperature: 'unavailable', gpu: status },
  } } } as any);
  await mount();
  const panel = host.querySelector('[aria-label="硬件信息"]')!;
  expect(panel.textContent).toContain(message);
  expect(panel.querySelector('.cpu-card')?.textContent).not.toContain('温度');
  expect(panel.textContent).not.toContain('0 °C');
  expect(panel.querySelector('.sensors-card')).toBeNull();
  if (status !== 'no_nvidia_gpu') expect(panel.textContent).not.toContain('未检测到 NVIDIA GPU');
});

test.each([
  ['offline', '2026-10-10T07:59:00Z', '数据已过期'],
  ['online', '2026-10-10T07:56:59Z', '数据已过期'],
  ['online', 'invalid', '采样状态未知'],
])('hardware is not presented as current when %s / %s', async (status, sampledAt, reason) => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, status,
    sys_info: { hardware: { ...hardware, sampled_at: sampledAt } } } as any);
  await mount();
  const text = host.querySelector('[aria-label="硬件信息"]')!.textContent!;
  expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
  expect(text).toContain(reason);
  expect(text).not.toContain('最近采样');
  expect(text).not.toContain('Invalid Date');
  expect(text).toContain('52.5 °C');
});

test('clock aging and failed detail polls retain the previous sample as non-live, then recover without reloading charts', async () => {
  await mount();
  vi.mocked(api.getNodeDetail).mockRejectedValue(new Error('timeout'));
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('刷新失败');
  expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
  expect(host.textContent).toContain('RTX 5060');
  vi.mocked(api.getNodeDetail).mockResolvedValue(node as any);
  await vi.advanceTimersByTimeAsync(120000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('数据已过期');
  const updated = { ...hardware, sampled_at: new Date().toISOString(), sensors_sampled_at: new Date().toISOString(),
    cpu: { ...hardware.cpu, sampled_at: new Date().toISOString(), temperature_c: 49 } };
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: updated } } as any);
  await vi.advanceTimersByTimeAsync(5000); await settle();
  expect(host.querySelector('.sample-status')).toBeNull();
  expect(host.querySelector('.cpu-card')?.textContent).toContain('49 °C');
  expect(host.textContent).not.toContain('服务器详情加载失败');
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
  expect(charts).toHaveLength(2);
});

test('hardware aging continues while an existing detail request is stuck without adding another poller', async () => {
  await mount();
  vi.mocked(api.getNodeDetail).mockReturnValueOnce(new Promise(() => {}));
  await vi.advanceTimersByTimeAsync(150000); await settle();
  expect(host.querySelector('.sample-status')?.textContent).toContain('数据已过期');
  expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
  expect(api.getNodeDetail).toHaveBeenCalledTimes(2);
  expect(api.getNodeMetrics).toHaveBeenCalledTimes(1);
});

test.each([
  ['physical', '物理机'], ['virtual', '虚拟机'], ['container', '容器'], ['unknown', '未确定'],
  [undefined, '未确定'], ['invalid', '未确定'],
])('node detail and real list cards use reported machine kind %s, never node names or VBS', async (kind, label) => {
  const machine = kind === undefined ? undefined : { kind, vendor: 'ACME', model: 'Node model',
    virtualization: 'Hyper-V / VBS enabled', evidence: ['SMBIOS chassis evidence'], detected_at: hardware.sampled_at };
  const fixture = { ...node, name: 'Generic node', sys_info: { hardware: { ...hardware, machine } } } as any;
  vi.mocked(api.getNodeDetail).mockResolvedValue(fixture);
  await mount();
  const detailBadge = host.querySelector('.d-head .machine-badge');
  expect(detailBadge?.textContent).toBe(label);
  if (machine) {
    expect(detailBadge?.getAttribute('title')).toContain('SMBIOS chassis evidence');
    expect(detailBadge?.getAttribute('title')).toContain('Hyper-V / VBS enabled');
    expect(detailBadge?.getAttribute('title')).toContain('ACME');
  } else expect(detailBadge?.getAttribute('title')).toContain('尚未上报');
  app!.unmount(); host.remove();
  vi.mocked(api.listNodes).mockResolvedValue([fixture, { ...node, id: 8, name: 'Windows 5060', sys_info: null }] as any);
  await mount(Nodes);
  const cards = [...host.querySelectorAll('.grid > .card')];
  expect(cards).toHaveLength(2);
  expect(cards[0]!.querySelector('.machine-badge')?.textContent).toBe(label);
  expect(cards[1]!.querySelector('.machine-badge')?.textContent).toBe('未确定');
});

test.each(['physical', 'virtual', 'container', 'unknown', undefined])(
  'physical inventory and board sensors are visible only for explicit physical machines: %s', async kind => {
    vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: { ...hardware,
      machine: kind === undefined ? undefined : { ...hardware.machine, kind },
    } } } as any);
    await mount();
    const inventory = host.querySelector('[aria-label="物理机清单"]');
    if (kind === 'physical') {
      expect(inventory).not.toBeNull();
      for (const value of ['Custom', 'Desktop', 'ASUS', 'TUF B650', 'AMI', '3210', 'DIMM_A1',
        '16 GiB', '6000 MT/s', '5200 MT/s', 'Kingston', 'KF560']) {
        expect(inventory!.textContent).toContain(value);
      }
      expect(host.querySelector('.sensors-card')?.textContent).toContain('0 RPM');
    } else {
      expect(inventory).toBeNull();
      expect(host.querySelector('.sensors-card')).toBeNull();
      expect(host.textContent).not.toContain('TUF B650');
    }
    // CPU/GPU remain useful on every machine kind, including old agents.
    expect(host.querySelector('.cpu-card')?.textContent).toContain('52.5 °C');
    expect(host.querySelector('.gpu-card')?.textContent).toContain('0 %');
  });

test('physical machine missing specs omits empty inventory while nullable modules never invent readings', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: { ...hardware,
    physical_inventory: null,
  } } } as any);
  await mount();
  expect(host.querySelector('[aria-label="物理机清单"]')).toBeNull();
  app!.unmount(); host.remove();
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: { ...hardware,
    physical_inventory: { board: null, bios: null, memory_modules: [{ slot: 'DIMM0', capacity_bytes: 0,
      speed_mts: null, configured_speed_mts: 0, vendor: null, part_number: null }],
      disks: [{ name: 'disk0', model: null, size_bytes: null, bus: null, rotational: null }] },
  } } } as any);
  await mount();
  const text = host.querySelector('[aria-label="物理机清单"]')!.textContent!;
  expect(text).toContain('0 B'); expect(text).toContain('0 MT/s'); expect(text).not.toContain('未读取');
  expect(text).not.toContain('null'); expect(text).not.toContain('undefined');
});

test.each([
  ['CPU', { cpu: { ...hardware.cpu, sampled_at: '2026-10-10T07:57:59Z' } }, '数据已过期'],
  ['sensors', { sensors_sampled_at: '2026-10-10T07:57:59Z' }, '数据已过期'],
  ['CPU null', { cpu: { ...hardware.cpu, sampled_at: null } }, '采样状态未知'],
  ['sensors null', { sensors_sampled_at: null }, '采样状态未知'],
  ['CPU future', { cpu: { ...hardware.cpu, sampled_at: '2026-10-10T08:00:06Z' } }, '采样状态未知'],
  ['sensors future', { sensors_sampled_at: '2026-10-10T08:00:06Z' }, '采样状态未知'],
  ['overall future', { sampled_at: '2026-10-10T08:00:06Z' }, '采样状态未知'],
  ['overall null', { sampled_at: null }, '采样状态未知'],
])('fresh overall snapshot does not disguise missing, stale or future source time: %s', async (_, change, reason) => {
  await mount(HardwarePanel, { hardware: { ...hardware, ...change }, status: 'online', now: Date.now() });
  const status = host.querySelector('.sample-status')!.textContent!;
  expect(status).toContain(reason); expect(status).not.toContain('最近采样');
  expect(host.textContent).not.toContain('Invalid Date');
});

test.each(['cpu_temperature', 'gpu'])(
  'availability %s reports stale, failed and collecting in visible Chinese, not a recent sample', async field => {
    for (const [state, label] of [['stale', '数据已过期'], ['collection_failed', '刷新失败'], ['collecting', '采集中']]) {
      await mount(HardwarePanel, { hardware: { ...hardware, gpus: [],
        cpu: { ...hardware.cpu, temperature_c: null }, availability: { ...hardware.availability, [field]: state } },
        status: 'online', now: Date.now() });
      expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
      expect(host.querySelector('.sample-status')?.textContent).toContain(label);
      expect(host.querySelector('.sample-status')?.textContent).not.toContain('最近采样');
      expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
      expect(host.textContent).not.toContain(state);
      app!.unmount(); host.remove();
    }
  });

test('CPU sensor-file failures have visible Chinese meaning and an empty sample never claims recent readings', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, temperature_c: null },
    availability: { ...hardware.availability, cpu_temperature: 'sensors_file_unavailable' } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.sample-status')?.textContent).toBe('刷新失败');
  expect(host.textContent).not.toContain('sensors_file_unavailable');
  app!.unmount(); host.remove();
  await mount(HardwarePanel, { hardware: { ...hardware, sampled_at: null, gpus: [], sensors: [],
    cpu: { model: null, physical_cores: null, logical_cores: null, temperature_c: null,
      frequency_mhz: null, max_frequency_mhz: null, frequency_source: null, temperature_source: null, sampled_at: null },
    availability: { cpu_temperature: 'collecting', gpu: 'collecting' } }, status: 'online', now: Date.now() });
  expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
  expect(host.querySelector('.sample-status')?.textContent).toContain('采集中');
  expect(host.querySelector('.sample-status')?.textContent).not.toContain('最近采样');
  expect(host.querySelector('.sample-status time')).toBeNull();
});

test('source times tolerate exact age and future skew limits without default diagnostic text', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, sampled_at: '2026-10-10T07:57:00Z',
    cpu: { ...hardware.cpu, sampled_at: '2026-10-10T07:58:00Z' }, sensors_sampled_at: '2026-10-10T08:00:05Z' },
    status: 'online', now: Date.now() });
  expect(host.querySelector('.sample-status')).toBeNull();
  expect(host.querySelector('.cpu-card time')).toBeNull();
  expect(host.querySelector('.sensors-card time')).toBeNull();
});

test('WMI metadata stays out of default summary and is never called measured current, base or maximum boost', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu,
    frequency_mhz: 3600, max_frequency_mhz: 9999, base_frequency_mhz: 3800,
    frequency_source: 'Win32_Processor.CurrentClockSpeed (WMI; not measured boost)',
    base_frequency_source: 'Win32_Processor.MaxClockSpeed (WMI nominal metadata; not measured base/boost)',
  } }, status: 'online', now: Date.now() });
  const cpu = host.querySelector('.cpu-card')!;
  for (const hidden of ['WMI', '3800 MHz', '3600 MHz', '标称', '来源', 'Win32_Processor']) expect(cpu.textContent).not.toContain(hidden);
  expect(cpu.textContent).not.toContain('当前频率');
  expect(cpu.textContent).not.toContain('基准频率');
  expect(cpu.textContent).not.toContain('最高频率');
  expect(cpu.textContent).not.toContain('9999 MHz');
});

test('dynamic CPU zero frequency survives while source and report caps stay out of the summary', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, frequency_mhz: 0,
    frequency_source: 'LibreHardwareMonitor:Cores (Average)', base_frequency_mhz: 0,
    base_frequency_source: 'Win32_Processor.MaxClockSpeed',
  } }, status: 'online', now: Date.now() });
  const cpu = host.querySelector('.cpu-card')!;
  expect(cpu.textContent).toContain('当前频率');
  expect(cpu.textContent).not.toContain('频率来源 LibreHardwareMonitor:Cores (Average)');
  expect(cpu.textContent).not.toContain('动态传感器读数');
  expect(cpu.textContent).not.toContain('温度来源 LibreHardwareMonitor');
  expect(cpu.textContent).toContain('0 MHz');
  expect(cpu.textContent).not.toContain('报告上限频率');
  expect(cpu.textContent).not.toContain('最高频率');
});

test.each([
  ['sensors_file_missing', '传感器文件尚未生成'],
  ['sensors_file_stale', '传感器文件过期'],
  ['sensors_file_invalid', '传感器文件格式异常'],
  ['sensors_file_permission_denied', '无权读取传感器文件'],
])('CPU bridge error %s keeps its Chinese reason on hover and a short visible failure', async (state, label) => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, temperature_c: null },
    availability: { ...hardware.availability, cpu_temperature: state } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.cpu-card')?.textContent).not.toContain('温度');
  expect(host.querySelector('.sample-status')?.textContent).toBe(state === 'sensors_file_stale' ? '数据已过期' : '刷新失败');
  expect(host.querySelector('.sample-status')?.getAttribute('title')).toContain(label);
  expect(host.textContent).not.toContain(state);
});

test('GPU partial memory reading preserves measured used bytes without inventing a total', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, gpus: [{ ...hardware.gpus[0], memory_used_mib: 0, memory_total_mib: null }] }, status: 'online', now: Date.now() });
  const gpu = host.querySelector('.gpu-card')!;
  expect(gpu.textContent).toContain('显存已用0 MiB');
  expect(gpu.textContent).not.toContain('/ 0 MiB');
});

test.each(['query_failed', 'driver_missing'])('GPU hardware inventory survives telemetry error %s with one short failure', async telemetry_status => {
  await mount(HardwarePanel, { hardware: { ...hardware, gpus: [{ ...hardware.gpus[0], telemetry_status }], availability: { cpu_temperature: 'available', gpu: 'inventory_only' } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.gpu-card')?.textContent).toContain('NVIDIA GeForce');
  expect(host.querySelector('.sample-status')?.textContent).toBe('刷新失败');
  expect(host.querySelectorAll('.sample-status')).toHaveLength(1);
  expect(host.textContent).not.toContain('未检测到');
});

test.each([['no_gpu', '未检测到 GPU'], ['unknown', 'GPU 状态未知'], ['collection_failed', '刷新失败']])('new GPU availability %s preserves absence versus unknown versus error', async (gpu, label) => {
  await mount(HardwarePanel, { hardware: { ...hardware, gpus: [], availability: { cpu_temperature: 'available', gpu } }, status: 'online', now: Date.now() });
  expect(host.textContent).toContain(label);
  if (gpu !== 'no_gpu') expect(host.textContent).not.toContain('未检测到 GPU');
});

test('no source proves no measured CPU frequency and no upper or nominal metadata leaks into default summary', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, frequency_source: null, frequency_mhz: 3000 } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.cpu-card')?.textContent).not.toContain('当前频率');
  expect(host.textContent).not.toContain('3000 MHz');
});

test('compact raw probe labels receive Chinese and normalized English while missing CPU temperature retains its sensor', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, temperature_c: null }, sensors: [
    { name: 'Chip / Temperature#1', kind: 'temperature', value: 0, unit: '°C', source: 'test' },
    { name: 'Chip / Fan#2', kind: 'fan', value: 0, unit: 'RPM', source: 'test' },
    { name: 'CPU / Core (Tctl/Tdie)', kind: 'temperature', value: 42, unit: '°C', source: 'test' },
  ] }, status: 'online', now: Date.now() });
  const text = host.querySelector('.sensors-card')!.textContent!;
  for (const label of ['温度探头 1 · Temperature #1', '风扇 2 · Fan #2', 'CPU 温度 · Core (Tctl/Tdie)', '0 °C', '0 RPM']) expect(text).toContain(label);
});

test('CPU Tctl and Tdie aliases do not duplicate the main temperature while CCD temperatures remain separate', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, sensors: ['Tctl', 'Tdie', 'CPU / Tctl/Tdie', 'CPU / CCD1 (Tdie)'].map(name => ({ name, kind: 'temperature', value: 42, unit: '°C', source: 'test' })) }, status: 'online', now: Date.now() });
  expect(host.querySelectorAll('.sensor-row')).toHaveLength(1);
  expect(host.querySelector('.sensors-card')?.textContent).toContain('核心簇 1 温度 · CCD1 (Tdie)');
});

test('captured detail promotes latest CPU utilization and keeps OS runtime compact without duplicate metadata', async () => {
  vi.setSystemTime(new Date('2026-10-10T12:22:50Z'));
  vi.mocked(api.getNodeDetail).mockResolvedValue(captured5060 as any);
  await mount();
  expect(host.querySelector('.cpu-card')?.textContent).toContain('20.8 %');
  expect(host.querySelector('.system-strip')?.textContent).toContain('Windows-11');
  expect(host.querySelector('.system-strip')?.textContent).toContain('运行');
  expect(host.querySelector('.system-strip')?.textContent).not.toContain('AMD Ryzen');
  expect(host.textContent).not.toContain('12 核');
  expect(host.textContent?.match(/AMD64/g)).toHaveLength(1);
  expect(host.textContent?.match(/0.6.11/g)).toHaveLength(1);
  expect([...host.querySelectorAll('.d-head > .name, .d-head > .machine-badge, .d-head > .badge')].map(el => el.className)).toEqual(['name', 'machine-badge', 'badge online']);
});

test('legacy CPU logical count is labelled threads rather than cores', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { cpu_model: 'Legacy', cpu_cores: 12 } } as any);
  await mount();
  expect(host.textContent).toContain('12 线程');
  expect(host.textContent).not.toContain('12 核');
});

test('captured sensors translate probe names without inventing positions or duplicating the CPU primary temperature', async () => {
  vi.setSystemTime(new Date('2026-10-10T12:22:50Z'));
  await mount(HardwarePanel, { hardware: captured5060.sys_info.hardware, status: 'online', now: Date.now() });
  const text = host.querySelector('.sensors-card')!.textContent!;
  for (const value of ['温度探头 1 · Temperature #1', '风扇 2 · Fan #2', '核心簇 1 温度 · CCD1 (Tdie)']) expect(text).toContain(value);
  expect(text).not.toContain('Core (Tctl/Tdie)');
  expect(text).not.toContain('ITE IT8613E');
  expect(host.querySelector('.sensor-row')?.getAttribute('title')).toContain('ITE IT8613E');
  expect(text).not.toContain('南桥');
});

test.each([nasContract, windowsContract])('inventory-only GPU is model and kind, not a grid of fabricated missing telemetry ($name)', async fixture => {
  vi.setSystemTime(new Date('2026-10-10T12:22:50Z'));
  vi.mocked(api.getNodeDetail).mockResolvedValue(fixture as any);
  await mount();
  const card = [...host.querySelectorAll('.gpu-card')].find(el => el.textContent?.includes('Graphics'))!;
  expect(card.textContent).toContain('集成显卡');
  expect(card.querySelectorAll('dd')).toHaveLength(0);
  expect(card.textContent).not.toContain('未读取');
  expect(card.textContent).not.toContain('不可用');
});

test('NAS contract renders all seven physical disks and five measured volumes with no per-member pool usage', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue(nasContract as any);
  await mount();
  const panel = host.querySelector('[aria-label="存储"]')!;
  expect(panel).not.toBeNull();
  expect(panel.querySelectorAll('.physical-disk-row')).toHaveLength(7);
  expect(panel.querySelectorAll('.volume-row')).toHaveLength(5);
  expect(panel.querySelectorAll('.physical-disk-row .usage-track')).toHaveLength(0);
  expect(panel.querySelectorAll('.disk-ring')).toHaveLength(0);
  for (const value of ['SSD 410GB', 'Netac SSD 512GB', 'YS9086BB-1', '/vol1', '/vol2', '/vol3', '/boot/efi']) expect(panel.textContent).toContain(value);
  expect(panel.querySelectorAll('.volume-row.system-volume')).toHaveLength(2);
  expect(panel.querySelectorAll('.volume-row .usage-track')).toHaveLength(5);
});

test('legacy captured NAS disks never show unattributable duplicate usage as individual occupancy', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue(capturedNAS as any);
  await mount();
  const panel = host.querySelector('[aria-label="存储"]')!;
  expect(panel.querySelectorAll('.physical-disk-row')).toHaveLength(7);
  expect(panel.querySelectorAll('.physical-disk-row .usage-track')).toHaveLength(0);
  expect(panel.querySelectorAll('.volume-row')).toHaveLength(3);
});

test('captured Windows empty storage falls back to disk inventory without claiming no disks', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue(captured5060 as any);
  await mount();
  const panel = host.querySelector('[aria-label="存储"]')!;
  expect(panel.querySelectorAll('.physical-disk-row')).toHaveLength(2);
  expect(panel.textContent).toContain('KINGSTON SNV2S1000G');
  expect(panel.textContent).not.toContain('暂无存储');
  expect(panel.querySelectorAll('.usage-track')).toHaveLength(0);
});

test('measured zero volume usage survives and missing values omit only the invalid fields', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, storage: [
    { device: 'vol', mount: '/zero', kind: 'volume', total: 1024, used: 0, percent: 0, usage_scope: 'measured' },
    { device: 'disk', mount: 'disk', kind: 'physical', total: 1024, used: null, percent: null, usage_scope: 'unmeasured', model: 'Disk' },
  ] } as any);
  await mount();
  const zero = host.querySelector('.volume-row')!;
  expect(zero.textContent).toContain('0 B / 1 KiB');
  expect(zero.textContent).toContain('0 %');
  expect(zero.querySelector('.usage-track span')?.getAttribute('style')).toContain('0%');
  expect(host.querySelector('.physical-disk-row')?.textContent).not.toContain('0 %');
});

test('unknown storage remains uncollected rather than no disks', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: null, storage: null } as any);
  await mount();
  expect(host.querySelector('[aria-label="存储"]')?.textContent).toContain('存储尚未采集');
  expect(host.textContent).not.toContain('无磁盘');
});

// Regression coverage of the already-tested nullable formatter and GPU loop.
test('nullable readings are omitted, multiple GPUs keep identities and one unsupported field does not mask valid readings', async () => {
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
  expect(cpu.querySelectorAll('dd')).toHaveLength(0);
  const cards = [...host.querySelectorAll('.gpu-card')];
  expect(cards).toHaveLength(2);
  expect(cards[0]!.getAttribute('aria-label')).toBe('GPU Unsupported GPU');
  expect(cards[0]!.textContent).not.toContain('0 °C');
  expect(cards[0]!.textContent).not.toContain('0 %');
  expect(cards[0]!.textContent).not.toContain('null');
  expect(cards[1]!.textContent).toContain('0 °C');
  expect(cards[1]!.textContent).toContain('2500 MHz');
  expect(cards[1]!.textContent).not.toContain('功耗');
  expect(host.querySelector('.sensors-card')).toBeNull();
});

test('switching node cannot retain old hardware or reveal it from a late detail response', async () => {
  await mount();
  let resolve!: (data: any) => void;
  vi.mocked(api.getNodeDetail).mockReturnValueOnce(new Promise<any>(done => { resolve = done; }));
  await vi.advanceTimersByTimeAsync(5000); await settle();
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, id: 8, name: 'Legacy Linux', sys_info: null } as any);
  id.value = 8; await settle();
  expect(host.textContent).not.toContain('RTX 5060');
  expect(host.querySelector('.hardware-panel')?.textContent).toContain('硬件尚未采集');
  resolve(node); await settle();
  expect(host.textContent).not.toContain('RTX 5060');
  expect(host.querySelector('.name')?.textContent).toBe('Legacy Linux');
});

