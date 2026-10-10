// Synthetic isolated UI edge-case fixtures, not real captures; never query a live backend.
export const hardware = {
  sampled_at: '2026-10-10T07:59:00Z',
  machine: { kind: 'physical' as const, vendor: 'Custom', model: 'Desktop', virtualization: null,
    evidence: ['SMBIOS physical chassis'], detected_at: '2026-10-10T07:59:00Z' },
  physical_inventory: {
    board: { vendor: 'ASUS', model: 'TUF B650' }, bios: { vendor: 'AMI', version: '3210' },
    memory_modules: [{ slot: 'DIMM_A1', capacity_bytes: 17179869184, speed_mts: 6000,
      configured_speed_mts: 5200, vendor: 'Kingston', part_number: 'KF560' }],
    disks: [{ name: 'disk0', model: 'Samsung 990', size_bytes: 1099511627776, bus: 'NVMe', rotational: false }],
  },
  sensors_sampled_at: '2026-10-10T07:59:00Z',
  cpu: { sampled_at: '2026-10-10T07:59:00Z', model: 'AMD Ryzen 7 9700X', physical_cores: 8, logical_cores: 16,
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
