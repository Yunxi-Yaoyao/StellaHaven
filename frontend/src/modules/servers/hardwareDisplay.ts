import type { HardwareCpu, HardwareGpu, HardwareSensor } from '../../api/servers';

export function hasValue(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
export function hasGpuMetrics(gpu: HardwareGpu): boolean {
  return gpuTelemetryValid(gpu) && [gpu.temperature_c, gpu.utilization_pct, gpu.memory_used_mib, gpu.memory_total_mib,
    gpu.power_w].some(hasValue);
}
export function gpuTelemetryValid(gpu: HardwareGpu): boolean {
  return gpu.telemetry_status === undefined || gpu.telemetry_status === 'available';
}
export function metric(value: number | null | undefined, unit = ''): string {
  const precision = ['MHz', 'RPM'].includes(unit) ? 0 : ['°C', 'W', '%'].includes(unit) ? 1 : 2;
  return hasValue(value) ? `${Number(value.toFixed(precision))}${unit ? ` ${unit}` : ''}` : '';
}
export function cpuFrequency(value: number | null | undefined): string {
  if (!hasValue(value)) return '';
  return value >= 1000 ? metric(Math.round(value / 10) / 100, 'GHz') : metric(value, 'MHz');
}
export function bytes(value: number | null | undefined): string {
  if (!hasValue(value)) return '';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = value === 0 ? 0 : Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${Number((value / 1024 ** index).toFixed(index === 0 ? 0 : 1))} ${units[index]}`;
}
export function joinSpec(...fields: (string | null | undefined)[]): string {
  return fields.filter(field => field?.trim()).join(' · ');
}
export function measuredFrequency(cpu: HardwareCpu): boolean {
  return hasValue(cpu.frequency_mhz) && !!cpu.frequency_source && !/WMI|Win32_Processor/i.test(cpu.frequency_source);
}
export function sensorLabel(sensor: HardwareSensor): { label: string; chip: string } {
  const parts = sensor.name.split(' / ');
  const english = parts.pop()!.trim();
  const probe = english.match(/^Temperature\s*#\s*(\d+)$/i);
  const fan = english.match(/^Fan\s*#\s*(\d+)$/i);
  const ccd = english.match(/^CCD\s*(\d+)(?:\s*\(Tdie\))?$/i);
  const core = english.match(/^Core\s+(\d+)$/i);
  const chinese = probe ? `温度探头 ${probe[1]}` : fan ? `风扇 ${fan[1]}`
    : ccd ? `核心簇 ${ccd[1]} 温度` : core ? `核心 ${core[1]} 温度`
    : /Tctl|Tdie|Package id/i.test(english) ? 'CPU 温度'
    : ({ System: '系统温度', Chassis: '机箱风扇', acpitz: 'ACPI 温度' } as Record<string, string>)[english]
      || (sensor.kind === 'fan' ? '风扇' : '温度探头');
  const displayEnglish = probe ? `Temperature #${probe[1]}` : fan ? `Fan #${fan[1]}` : english;
  return { label: `${chinese} · ${displayEnglish}`, chip: parts.join(' / ') };
}
