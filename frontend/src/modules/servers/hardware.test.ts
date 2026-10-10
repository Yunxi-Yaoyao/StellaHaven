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
  ['driver_not_ready', 'GPU 不可用 · 驱动尚未就绪'],
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
  const updated = { ...hardware, sampled_at: new Date().toISOString(), sensors_sampled_at: new Date().toISOString(),
    cpu: { ...hardware.cpu, sampled_at: new Date().toISOString(), temperature_c: 49 } };
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
        '16 GiB', '6000 MT/s', '5200 MT/s', 'Kingston', 'KF560', 'disk0', 'Samsung 990', '1 TiB', 'NVMe', '固态']) {
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

test('physical machine with unavailable inventory is explicit and nullable modules never invent readings', async () => {
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: { ...hardware,
    physical_inventory: null,
  } } } as any);
  await mount();
  expect(host.querySelector('[aria-label="物理机清单"]')?.textContent).toContain('物理机清单尚未读取');
  app!.unmount(); host.remove();
  vi.mocked(api.getNodeDetail).mockResolvedValue({ ...node, sys_info: { hardware: { ...hardware,
    physical_inventory: { board: null, bios: null, memory_modules: [{ slot: 'DIMM0', capacity_bytes: 0,
      speed_mts: null, configured_speed_mts: 0, vendor: null, part_number: null }],
      disks: [{ name: 'disk0', model: null, size_bytes: null, bus: null, rotational: null }] },
  } } } as any);
  await mount();
  const text = host.querySelector('[aria-label="物理机清单"]')!.textContent!;
  expect(text).toContain('0 B'); expect(text).toContain('0 MT/s'); expect(text).toContain('未读取');
  expect(text).not.toContain('null'); expect(text).not.toContain('undefined');
});

test.each([
  ['CPU', { cpu: { ...hardware.cpu, sampled_at: '2026-10-10T07:57:59Z' } }, 'CPU 源采样已过期'],
  ['sensors', { sensors_sampled_at: '2026-10-10T07:57:59Z' }, '传感器源采样已过期'],
  ['CPU null', { cpu: { ...hardware.cpu, sampled_at: null } }, 'CPU 源采样时间未知'],
  ['sensors null', { sensors_sampled_at: null }, '传感器源采样时间未知'],
  ['CPU future', { cpu: { ...hardware.cpu, sampled_at: '2026-10-10T08:00:06Z' } }, 'CPU 源采样时间异常'],
  ['sensors future', { sensors_sampled_at: '2026-10-10T08:00:06Z' }, '传感器源采样时间异常'],
  ['overall future', { sampled_at: '2026-10-10T08:00:06Z' }, '采样时间异常'],
  ['overall null', { sampled_at: null }, '采样时间未知'],
])('fresh overall snapshot does not disguise missing, stale or future source time: %s', async (_, change, reason) => {
  await mount(HardwarePanel, { hardware: { ...hardware, ...change }, status: 'online', now: Date.now() });
  const status = host.querySelector('.sample-status')!.textContent!;
  expect(status).toContain('非实时'); expect(status).toContain(reason); expect(status).not.toContain('最近采样');
  expect(host.textContent).not.toContain('Invalid Date');
});

test.each(['cpu_temperature', 'gpu'])(
  'availability %s reports stale, failed and collecting in visible Chinese, not a recent sample', async field => {
    for (const [state, label] of [['stale', '过期'], ['collection_failed', '采集失败'], ['collecting', '采集中']]) {
      await mount(HardwarePanel, { hardware: { ...hardware, gpus: [],
        cpu: { ...hardware.cpu, temperature_c: null }, availability: { ...hardware.availability, [field]: state } },
        status: 'online', now: Date.now() });
      expect(host.querySelector('.sample-status')?.textContent).toContain('非实时');
      expect(host.querySelector('.sample-status')?.textContent).toContain(label);
      expect(host.querySelector('.sample-status')?.textContent).not.toContain('最近采样');
      expect(host.querySelector(field === 'gpu' ? '.gpu-card' : '.cpu-card')?.textContent).toContain(label);
      expect(host.textContent).not.toContain(state);
      app!.unmount(); host.remove();
    }
  });

test('CPU sensor-file failures have visible Chinese meaning and an empty sample never claims recent readings', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, temperature_c: null },
    availability: { ...hardware.availability, cpu_temperature: 'sensors_file_unavailable' } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.cpu-card')?.textContent).toContain('传感器文件不可用');
  expect(host.textContent).not.toContain('sensors_file_unavailable');
  app!.unmount(); host.remove();
  await mount(HardwarePanel, { hardware: { ...hardware, sampled_at: null, gpus: [], sensors: [],
    cpu: { model: null, physical_cores: null, logical_cores: null, temperature_c: null,
      frequency_mhz: null, max_frequency_mhz: null, frequency_source: null, temperature_source: null, sampled_at: null },
    availability: { cpu_temperature: 'collecting', gpu: 'collecting' } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.sample-status')?.textContent).toContain('非实时');
  expect(host.querySelector('.sample-status')?.textContent).toContain('采集中');
  expect(host.querySelector('.sample-status')?.textContent).not.toContain('最近采样');
  expect(host.querySelector('.sample-status time')).toBeNull();
});

test('source timestamps are visible and tolerate exact age and future skew limits', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, sampled_at: '2026-10-10T07:57:00Z',
    cpu: { ...hardware.cpu, sampled_at: '2026-10-10T07:58:00Z' }, sensors_sampled_at: '2026-10-10T08:00:05Z' },
    status: 'online', now: Date.now() });
  expect(host.querySelector('.sample-status')?.textContent).toContain('最近采样');
  expect(host.querySelector('.cpu-card time')?.getAttribute('datetime')).toBe('2026-10-10T07:58:00Z');
  expect(host.querySelector('.sensors-card time')?.getAttribute('datetime')).toBe('2026-10-10T08:00:05Z');
});

test('WMI frequency metadata is visible on mobile and never called measured current, base or maximum boost', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu,
    frequency_mhz: 3600, max_frequency_mhz: 9999, base_frequency_mhz: 3800,
    frequency_source: 'Win32_Processor.CurrentClockSpeed (WMI; not measured boost)',
    base_frequency_source: 'Win32_Processor.MaxClockSpeed (WMI nominal metadata; not measured base/boost)',
  } }, status: 'online', now: Date.now() });
  const cpu = host.querySelector('.cpu-card')!;
  expect(cpu.textContent).toContain('WMI 报告频率');
  expect(cpu.textContent).toContain('WMI 标称频率');
  expect(cpu.textContent).toContain('3800 MHz');
  expect(cpu.textContent).toContain('标称元数据');
  expect(cpu.textContent).toContain('非实测最高');
  expect(cpu.textContent).toContain('Win32_Processor.CurrentClockSpeed');
  expect(cpu.textContent).toContain('Win32_Processor.MaxClockSpeed');
  expect(cpu.textContent).not.toContain('当前频率');
  expect(cpu.textContent).not.toContain('基准频率');
  expect(cpu.textContent).not.toContain('最高频率');
  expect(cpu.textContent).not.toContain('9999 MHz');
});

test('dynamic CPU frequency and temperature source are visible with zero readings retained', async () => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, frequency_mhz: 0,
    frequency_source: 'LibreHardwareMonitor:Cores (Average)', base_frequency_mhz: 0,
    base_frequency_source: 'Win32_Processor.MaxClockSpeed',
  } }, status: 'online', now: Date.now() });
  const cpu = host.querySelector('.cpu-card')!;
  expect(cpu.textContent).toContain('当前频率');
  expect(cpu.textContent).toContain('频率来源 LibreHardwareMonitor:Cores (Average)');
  expect(cpu.textContent).toContain('动态传感器读数');
  expect(cpu.textContent).toContain('温度来源 LibreHardwareMonitor');
  expect(cpu.textContent).toContain('0 MHz');
  expect(cpu.textContent).toContain('报告上限频率');
  expect(cpu.textContent).not.toContain('最高频率');
});

test.each([
  ['sensors_file_missing', '传感器文件尚未生成'],
  ['sensors_file_stale', '传感器文件过期'],
  ['sensors_file_invalid', '传感器文件格式异常'],
  ['sensors_file_permission_denied', '无权读取传感器文件'],
])('CPU bridge error %s keeps its specific reason in visible Chinese', async (state, label) => {
  await mount(HardwarePanel, { hardware: { ...hardware, cpu: { ...hardware.cpu, temperature_c: null },
    availability: { ...hardware.availability, cpu_temperature: state } }, status: 'online', now: Date.now() });
  expect(host.querySelector('.cpu-card')?.textContent).toContain(label);
  expect(host.querySelector('.sample-status')?.textContent).toContain(label);
  expect(host.querySelector('.sample-status')?.textContent).not.toContain('最近采样');
  expect(host.textContent).not.toContain(state);
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

