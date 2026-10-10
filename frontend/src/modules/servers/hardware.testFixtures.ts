// Isolated UI fixtures only; never query a live backend for these tests.
export const hardware = {
  sampled_at: '2026-10-10T07:59:00Z',
  cpu: { model: 'AMD Ryzen 7 9700X', physical_cores: 8, logical_cores: 16,
    frequency_mhz: 4200, max_frequency_mhz: 5500, temperature_c: 52.5,
    temperature_source: 'LibreHardwareMonitor', frequency_source: 'psutil' },
  gpus: [{ id: 'GPU-5060', name: 'NVIDIA GeForce RTX 5060', temperature_c: 43,
    graphics_clock_mhz: 2500, memory_clock_mhz: 14001, utilization_pct: 0,
    memory_used_mib: 0, memory_total_mib: 8192, power_w: 12.5, fan_pct: 0, source: 'nvidia-smi' }],
  sensors: [{ name: 'System', kind: 'temperature' as const, value: 35, unit: '°C' as const, source: 'LibreHardwareMonitor' },
    { name: 'Chassis', kind: 'fan' as const, value: 0, unit: 'RPM' as const, source: 'LibreHardwareMonitor' }],
  availability: { cpu_temperature: 'available', gpu: 'available' },
};
export const node = { id: 7, name: 'Windows 5060', status: 'online', platform: 'windows', net_type: 'internal',
  interfaces: { Ethernet: { is_default: true, up: true } }, storage: [], latest_metrics: [],
  sys_info: { hardware } };
