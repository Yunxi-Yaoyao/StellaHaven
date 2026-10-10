<script setup lang="ts">
import { computed } from 'vue';
import type { HardwareInfo } from '../../api/servers';
import Icon from '../../shell/Icon.vue';
const props = defineProps<{ hardware?: HardwareInfo | null; status: string; now: number; refreshFailed?: boolean }>();
// Overall snapshots expire after 180s; CPU/sensor sources after 120s.
// A successful detail refresh must not refresh old sensor timestamps.
const sampledTime = computed(() => props.hardware?.sampled_at ? Date.parse(props.hardware.sampled_at) : NaN);
function timeReason(timestamp: string | null | undefined, label: string, tolerance: number): string {
  const time = timestamp ? Date.parse(timestamp) : NaN;
  if (!Number.isFinite(time)) return `${label}时间未知`;
  if (time - props.now > 5000) return `${label}时间异常`;
  return props.now - time > tolerance ? `${label}已过期` : '';
}
function validTime(timestamp: string | null | undefined): boolean { return !!timestamp && Number.isFinite(Date.parse(timestamp)); }
function displayTime(timestamp: string | null | undefined): string {
  return validTime(timestamp) ? new Date(timestamp!).toLocaleString('zh-CN', { hour12: false }) : '时间未知';
}
const cpuReason = computed(() => timeReason(props.hardware?.cpu.sampled_at, 'CPU 源采样', 120000));
const sensorReason = computed(() => timeReason(props.hardware?.sensors_sampled_at, '传感器源采样', 120000));
const sampleReason = computed(() => [
  props.status !== 'online' ? '节点离线' : '',
  props.refreshFailed ? '详情刷新失败' : '',
  timeReason(props.hardware?.sampled_at, '采样', 180000),
  cpuReason.value,
  isPhysical.value && props.hardware?.sensors.length ? sensorReason.value : '',
  ...(['cpu_temperature', 'gpu'] as const).map(field => {
    const state = props.hardware?.availability[field];
    return state && !['available', 'no_nvidia_gpu', 'unavailable'].includes(state)
      ? `${field === 'gpu' ? 'GPU' : 'CPU 温度'} ${availability(state)}` : '';
  }),
].filter(Boolean).join(' · '));
function value(number: number | null | undefined, unit = ''): string {
  return typeof number === 'number' && Number.isFinite(number) ? `${number}${unit ? ` ${unit}` : ''}` : '未读取';
}
const isWmiFrequency = computed(() => /WMI|Win32_Processor/i.test(props.hardware?.cpu.frequency_source || ''));
const frequencyDescription = computed(() => isWmiFrequency.value ? 'WMI 标称元数据 · 非实测动态频率或 boost'
  : /LibreHardwareMonitor/i.test(props.hardware?.cpu.frequency_source || '') ? '动态传感器读数' : '系统报告频率');
const isPhysical = computed(() => props.hardware?.machine?.kind === 'physical');
const inventory = computed(() => isPhysical.value ? props.hardware?.physical_inventory : null);
function bytes(number: number | null | undefined): string {
  if (typeof number !== 'number' || !Number.isFinite(number) || number < 0) return '未读取';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = number === 0 ? 0 : Math.min(Math.floor(Math.log(number) / Math.log(1024)), units.length - 1);
  return `${Number((number / 1024 ** index).toFixed(2))} ${units[index]}`;
}
function availability(status?: string): string {
  const labels: Record<string, string> = {
    available: '已采集', collecting: '采集中', collection_failed: '采集失败', stale: '过期',
    no_nvidia_gpu: '未检测到 NVIDIA GPU', nvidia_smi_failed: 'GPU 查询失败',
    nvidia_smi_missing: 'GPU 不可用 · 未安装 nvidia-smi', unavailable: '不可用',
    sensors_file_unavailable: '传感器文件不可用', driver_not_ready: 'GPU 不可用 · 驱动尚未就绪',
    sensors_file_missing: '传感器文件尚未生成', sensors_file_stale: '传感器文件过期',
    sensors_file_invalid: '传感器文件格式异常', sensors_file_permission_denied: '无权读取传感器文件',
  };
  return status ? labels[status] || '未读取 · 未识别的采集状态' : '未读取';
}
function gpuAvailability(status: string): string {
  return status === 'unavailable' ? 'GPU 不可用' : status === 'available' ? 'GPU 未读取' : availability(status);
}
</script>

<template>
  <section class="hardware-panel" aria-label="硬件信息">
    <header class="hardware-head">
      <span class="hardware-title"><Icon name="server" :size="14" />硬件信息</span>
      <span v-if="hardware" class="sample-status" role="status">
        {{ sampleReason ? `上次采样 · 非实时 · ${sampleReason}` : '最近采样' }} ·
        <time v-if="Number.isFinite(sampledTime)" :datetime="hardware.sampled_at!">{{ new Date(sampledTime).toLocaleString('zh-CN', { hour12: false }) }}</time>
      </span>
    </header>
    <p v-if="!hardware" class="hardware-source">未读取 · Agent 尚未上报硬件信息</p>
    <div v-if="hardware" class="hardware-grid">
      <article class="hardware-card cpu-card" aria-label="CPU 硬件">
        <h3>CPU <span>{{ hardware.cpu.model || '未读取' }}</span></h3>
        <dl class="hardware-metrics">
          <div><dt>核心 / 线程</dt><dd>{{ value(hardware.cpu.physical_cores, '核') }} / {{ value(hardware.cpu.logical_cores, '线程') }}</dd></div>
          <div :title="hardware.cpu.temperature_source || '未读取'"><dt>温度</dt><dd>{{ hardware.cpu.temperature_c == null && hardware.availability.cpu_temperature !== 'available' ? availability(hardware.availability.cpu_temperature) : value(hardware.cpu.temperature_c, '°C') }}</dd></div>
          <div :title="hardware.cpu.frequency_source || '未读取'"><dt>{{ isWmiFrequency ? 'WMI 报告频率' : '当前频率' }}</dt><dd>{{ value(hardware.cpu.frequency_mhz, 'MHz') }}</dd></div>
          <div v-if="!isWmiFrequency" :title="hardware.cpu.frequency_source || '未读取'"><dt>报告上限频率</dt><dd>{{ value(hardware.cpu.max_frequency_mhz, 'MHz') }}</dd></div>
          <div v-if="hardware.cpu.base_frequency_mhz != null"><dt>WMI 标称频率</dt><dd>{{ value(hardware.cpu.base_frequency_mhz, 'MHz') }}</dd></div>
        </dl>
        <p class="hardware-source">频率来源 {{ hardware.cpu.frequency_source || '未读取' }} · {{ frequencyDescription }}</p>
        <p v-if="hardware.cpu.base_frequency_mhz != null" class="hardware-source">标称来源 {{ hardware.cpu.base_frequency_source || 'Win32_Processor.MaxClockSpeed' }} · WMI 标称元数据，非实测最高或 boost</p>
        <p class="hardware-source">温度来源 {{ hardware.cpu.temperature_source || '未读取' }}</p>
        <p class="hardware-source">温度采集 {{ availability(hardware.availability.cpu_temperature) }}</p>
        <p class="hardware-source">CPU 源采样 · <time v-if="validTime(hardware.cpu.sampled_at)" :datetime="hardware.cpu.sampled_at!">{{ displayTime(hardware.cpu.sampled_at) }}</time><span v-else>时间未知</span><span v-if="cpuReason"> · 非实时 · {{ cpuReason }}</span></p>
      </article>
      <article v-if="!hardware.gpus.length" class="hardware-card gpu-card" aria-label="GPU 采集状态">
        <h3>GPU</h3><p class="hardware-source">{{ gpuAvailability(hardware.availability.gpu) }}</p>
      </article>
      <article v-for="gpu in hardware.gpus" :key="gpu.id" class="hardware-card gpu-card" :aria-label="`GPU ${gpu.name}`">
        <h3>GPU <span>{{ gpu.name }}</span></h3>
        <dl class="hardware-metrics">
          <div><dt>温度</dt><dd>{{ value(gpu.temperature_c, '°C') }}</dd></div>
          <div><dt>利用率</dt><dd>{{ value(gpu.utilization_pct, '%') }}</dd></div>
          <div><dt>核心频率</dt><dd>{{ value(gpu.graphics_clock_mhz, 'MHz') }}</dd></div>
          <div><dt>显存频率</dt><dd>{{ value(gpu.memory_clock_mhz, 'MHz') }}</dd></div>
          <div><dt>显存</dt><dd>{{ value(gpu.memory_used_mib) }} / {{ value(gpu.memory_total_mib, 'MiB') }}</dd></div>
          <div><dt>功耗</dt><dd>{{ value(gpu.power_w, 'W') }}</dd></div>
          <div><dt>风扇</dt><dd>{{ value(gpu.fan_pct, '%') }}</dd></div>
        </dl>
        <p class="hardware-source">来源 {{ gpu.source || '未读取' }} · {{ availability(hardware.availability.gpu) }}</p>
      </article>
      <article v-if="isPhysical && hardware.sensors.length" class="hardware-card sensors-card" aria-label="主板温度 / 风扇">
        <h3>主板 / 其他传感器</h3>
        <p class="hardware-source">传感器源采样 · <time v-if="validTime(hardware.sensors_sampled_at)" :datetime="hardware.sensors_sampled_at!">{{ displayTime(hardware.sensors_sampled_at) }}</time><span v-else>时间未知</span><span v-if="sensorReason"> · 非实时 · {{ sensorReason }}</span></p>
        <dl class="hardware-metrics">
          <div v-for="(sensor, index) in hardware.sensors" :key="`${sensor.source}:${sensor.kind}:${sensor.name}:${index}`" :title="sensor.source">
            <dt>{{ sensor.name }}</dt><dd>{{ value(sensor.value, sensor.unit) }}</dd><span class="hardware-source">来源 {{ sensor.source || '未读取' }}</span>
          </div>
        </dl>
      </article>
    </div>
    <section v-if="hardware && isPhysical" class="physical-inventory" aria-label="物理机清单">
      <h3>物理机清单 <span>{{ hardware.machine?.vendor || '未读取' }} · {{ hardware.machine?.model || '未读取' }}</span></h3>
      <p v-if="!inventory" class="hardware-source">物理机清单尚未读取</p>
      <div v-else class="hardware-grid">
        <article class="hardware-card" aria-label="主板和 BIOS">
          <dl class="hardware-metrics">
            <div><dt>主板</dt><dd>{{ inventory.board?.vendor || '未读取' }} · {{ inventory.board?.model || '未读取' }}</dd></div>
            <div><dt>BIOS</dt><dd>{{ inventory.bios?.vendor || '未读取' }} · {{ inventory.bios?.version || '未读取' }}</dd></div>
          </dl>
        </article>
        <article class="hardware-card" aria-label="内存条">
          <h3>内存条</h3>
          <p v-if="!inventory.memory_modules?.length" class="hardware-source">未读取</p>
          <dl v-for="(module, index) in inventory.memory_modules" :key="index" class="hardware-metrics inventory-item">
            <div><dt>{{ module.slot || '插槽未读取' }}</dt><dd>{{ bytes(module.capacity_bytes) }}</dd></div>
            <div><dt>厂商 / 型号</dt><dd>{{ module.vendor || '未读取' }} · {{ module.part_number || '未读取' }}</dd></div>
            <div><dt>标称速率</dt><dd>{{ value(module.speed_mts, 'MT/s') }}</dd></div>
            <div><dt>配置速率</dt><dd>{{ value(module.configured_speed_mts, 'MT/s') }}</dd></div>
          </dl>
        </article>
        <article class="hardware-card" aria-label="物理盘清单">
          <h3>物理盘</h3>
          <p v-if="!inventory.disks?.length" class="hardware-source">未读取</p>
          <dl v-for="(disk, index) in inventory.disks" :key="index" class="hardware-metrics inventory-item">
            <div><dt>{{ disk.name || '名称未读取' }}</dt><dd>{{ disk.model || '未读取' }}</dd></div>
            <div><dt>容量</dt><dd>{{ bytes(disk.size_bytes) }}</dd></div>
            <div><dt>总线</dt><dd>{{ disk.bus || '未读取' }}</dd></div>
            <div><dt>介质</dt><dd>{{ disk.rotational === true ? '机械' : disk.rotational === false ? '固态' : '未读取' }}</dd></div>
          </dl>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.physical-inventory { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.05); }
.inventory-item + .inventory-item { margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.05); }
.hardware-panel { min-width: 0; margin: 14px 0; padding: 14px 16px; background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.05); border-radius: var(--radius-sm); }
.hardware-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 14px; margin-bottom: 10px; }
.hardware-title { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-hi); }
.sample-status { color: var(--text-faint); font-size: 11px; overflow-wrap: anywhere; }
.hardware-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 270px), 1fr)); gap: 10px; }
.hardware-card { min-width: 0; padding: 10px 12px; border: 1px solid rgba(255,255,255,0.05); border-radius: var(--radius-sm); }
h3 { display: flex; flex-wrap: wrap; gap: 4px 8px; margin: 0 0 8px; color: var(--accent); font-size: 12px; font-weight: 600; overflow-wrap: anywhere; }
h3 span { min-width: 0; color: var(--text-hi); font-weight: 500; }
.hardware-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 12px; margin: 0; }
.hardware-metrics > div { min-width: 0; }
dt { color: var(--text-faint); font-size: 11px; overflow-wrap: anywhere; }
dd { margin: 2px 0 0; color: var(--text-hi); font-size: 12px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.hardware-source { margin: 8px 0 0; color: var(--text-faint); font-size: 11px; overflow-wrap: anywhere; }
</style>
