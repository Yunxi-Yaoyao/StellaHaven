import { afterEach, expect, test } from 'vitest';
import { createApp, h } from 'vue';
import Panel from './HardwareInfoPanel.vue';
import { machineTypeTitle } from '../../api/servers';
import { hardware } from './hardware.testFixtures';
let app: ReturnType<typeof createApp>;
let host: HTMLDivElement;
const stamp = '2026-10-10T08:00:00Z';
function mount(overrides: any = {}, memory: any = { total_bytes: 8157769728, available_bytes: 0, used_bytes: 4096, source: 'psutil.virtual_memory', scope: 'os_visible', state: 'available', sampled_at: stamp }) {
  host = document.createElement('div'); document.body.append(host);
  app = createApp({ render: () => h(Panel, { hardware: { ...structuredClone(hardware), ...overrides, memory }, status: 'online', now: Date.parse(stamp) }) });
  app.mount(host); return host;
}
afterEach(() => { app?.unmount(); host?.remove(); });
test('unknown classification explains insufficient evidence without claiming physical', () => {
  expect(machineTypeTitle({ kind: 'unknown', evidence: ['insufficient machine evidence'] } as any)).toContain('机器类型证据不足');
});
test.each(['physical', 'virtual', 'container', 'unknown', null])('system capacity is not gated by %s classification', kind => {
  mount({ machine: kind ? { kind } : null });
  const memory = host.querySelector('[aria-label="系统内存"]');
  expect(memory?.textContent).toContain('7.6 GiB');
  expect(memory?.textContent).toContain('可用0 B');
  expect(memory?.textContent).toContain('已用4 KiB');
});
test('legacy without memory never invents capacity from DIMM inventory', () => {
  mount({}, null); expect(host.querySelector('[aria-label="系统内存"]')).toBeNull();
});
test.each([null, -1, true, NaN, Infinity, 0])('invalid total %s never becomes capacity', total => {
  mount({}, { total_bytes: total, scope: 'os_visible', state: 'query_failed' });
  expect(host.querySelector('.system-memory')?.textContent).not.toContain('总量');
});
test('memory failure and source age are separate from healthy GPU/CPU envelope', () => {
  mount({}, { total_bytes: 8192, scope: 'os_visible', state: 'query_failed', sampled_at: '2026-10-10T07:00:00Z' });
  expect(host.querySelector('.system-memory')?.textContent).toContain('刷新失败');
  expect(host.querySelector('.system-memory')?.textContent).toContain('数据已过期');
  expect(host.querySelector('.system-memory')?.textContent).toContain('8 KiB');
});
test('container limits do not replace host-visible capacity or borrow sample time', () => {
  mount({ machine: { kind: 'container' } }, { total_bytes: 8192, available_bytes: 4096, scope: 'host_visible', state: 'available', sampled_at: stamp,
    cgroup: { total_bytes: 1024, used_bytes: 0, available_bytes: 1024, scope: 'cgroup', state: 'query_failed', sampled_at: '2026-10-10T07:00:00Z' } });
  expect(host.querySelector('.system-memory')?.textContent).toContain('宿主可见');
  expect(host.querySelector('.cgroup-memory')?.textContent).toContain('控制组限额');
  expect(host.querySelector('.cgroup-memory')?.textContent).toContain('1 KiB');
  expect(host.querySelector('.cgroup-memory')?.textContent).toContain('刷新失败');
});
test.each(['unknown', 'virtual', 'container'])('public platform metadata is labelled not physical inventory on %s', kind => {
  mount({ machine: { kind }, platform_inventory: { board: { vendor: 'Dell', model: 'Inherited board' }, bios: null,
    memory_modules: [{ capacity_bytes: 34359738368 }], disks: [{ name: 'host-disk' }], source: 'sysfs.dmi', scope: kind === 'container' ? 'host_visible' : 'platform_reported', state: 'available', sampled_at: stamp } });
  expect(host.querySelector('[aria-label="平台报告信息"]')?.textContent).toContain('Inherited board');
  expect(host.querySelector('[aria-label="物理机清单"]')).toBeNull();
  expect(host.querySelector('[aria-label="内存条"]')).toBeNull();
});
test('source-scoped unknown sensors remain visible without asserting bare metal', () => {
  mount({ machine: { kind: 'unknown' }, sensors: [{ name: 'System', value: 35, kind: 'temperature', unit: '°C', source: 'psutil:nct', scope: 'os_visible' }] });
  expect(host.querySelector('.sensors-card')?.textContent).toContain('35 °C');
});
test('host-visible container sensors carry their scope instead of implying exclusive hardware', () => {
  mount({ machine: { kind: 'container' }, sensors: [{ name: 'System', value: 35, kind: 'temperature', unit: '°C', source: 'psutil:nct', scope: 'host_visible' }] });
  expect(host.querySelector('.sensors-card')?.textContent).toContain('宿主可见');
});
test('DIMM installation capacity is named separately from OS capacity', () => {
  mount(); expect(host.querySelector('[aria-label="内存条"]')?.textContent).toContain('DIMM 安装容量');
});
test('platform metadata without provenance is not exposed on a VM', () => {
  mount({ machine: { kind: 'virtual' }, platform_inventory: { board: { model: 'Unsafe passthrough' } } });
  expect(host.textContent).not.toContain('Unsafe passthrough');
});
