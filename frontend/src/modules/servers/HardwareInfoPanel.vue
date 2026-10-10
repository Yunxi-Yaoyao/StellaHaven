<script setup lang="ts">
import { computed } from 'vue';
import type { HardwareInfo, SysMetricPoint } from '../../api/servers';
import Icon from '../../shell/Icon.vue';
import { hasValue, metric, bytes, joinSpec, measuredFrequency, sensorLabel } from './hardwareDisplay';
const props = defineProps<{ hardware?: HardwareInfo | null; status: string; now: number; refreshFailed?: boolean; latestSysMetric?: SysMetricPoint | null }>();
const isPhysical = computed(() => props.hardware?.machine?.kind === 'physical');
const inventory = computed(() => isPhysical.value ? props.hardware?.physical_inventory : null);
const sensors = computed(() => isPhysical.value ? (props.hardware?.sensors || []).filter(s => hasValue(s.value)
  && !(hasValue(props.hardware?.cpu.temperature_c) && s.kind === 'temperature'
    && /Core \(Tctl\/Tdie\)|Package id/i.test(s.name))) : []);
const coreSpec = computed(() => joinSpec(metric(props.hardware?.cpu.physical_cores, '核'), metric(props.hardware?.cpu.logical_cores, '线程')).replace(' · ', ' / '));
const failureLabels: Record<string, string> = {
  sensors_file_missing: '传感器文件尚未生成', sensors_file_stale: '传感器文件过期',
  sensors_file_invalid: '传感器文件格式异常', sensors_file_permission_denied: '无权读取传感器文件',
  sensors_file_unavailable: '传感器文件不可用', nvidia_smi_failed: 'GPU 查询失败',
  driver_not_ready: 'GPU 驱动尚未就绪', collection_failed: '采集失败',
};
const sampleStatus = computed(() => {
  const hw = props.hardware;
  if (!hw) return '';
  const states = [hw.availability.cpu_temperature, hw.availability.gpu];
  if (props.refreshFailed || hw.gpus.some(gpu => gpu.telemetry_status === 'query_failed' || gpu.telemetry_status === 'driver_missing')
    || states.some(s => failureLabels[s] && s !== 'sensors_file_stale')) return '刷新失败';
  if (states.includes('collecting')) return '采集中';
  const timestamps: [string | null | undefined, number][] = [[hw.sampled_at, 180000], [hw.cpu.sampled_at, 120000]];
  if (sensors.value.length) timestamps.push([hw.sensors_sampled_at, 120000]);
  if (hasValue(props.latestSysMetric?.cpu_pct)) timestamps.push([props.latestSysMetric?.ts, 180000]);
  const times = timestamps.map(([stamp, maxAge]) => ({ time: stamp ? Date.parse(stamp) : NaN, maxAge }));
  if (props.status !== 'online' || states.some(s => s === 'stale' || s === 'sensors_file_stale')
    || times.some(t => Number.isFinite(t.time) && props.now - t.time > t.maxAge)) return '数据已过期';
  if (times.some(t => !Number.isFinite(t.time) || t.time - props.now > 5000)) return '采样状态未知';
  return '';
});
const statusTitle = computed(() => [props.refreshFailed ? '详情刷新失败' : '',
  ...Object.values(props.hardware?.availability || {}).map(s => failureLabels[s] || '')].filter(Boolean).join(' · '));
const emptyGpuLabel = computed(() => {
  const state = props.hardware?.availability.gpu;
  if (['no_gpu', 'no_nvidia_gpu'].includes(state || '')) return state === 'no_gpu' ? '未检测到 GPU' : '未检测到 NVIDIA GPU';
  if (state === 'nvidia_smi_missing') return 'GPU 遥测未采集';
  if (sampleStatus.value === '刷新失败' || state === 'collecting' || state === 'stale') return '';
  return 'GPU 状态未知';
});
</script>

<template>
  <section class="hardware-panel" aria-label="硬件信息">
    <header class="hardware-head"><span class="hardware-title"><Icon name="server" :size="14" />硬件信息</span><span v-if="sampleStatus" class="sample-status" role="status" :title="statusTitle">{{ sampleStatus }}</span></header>
    <p v-if="!hardware" class="hardware-note">硬件尚未采集</p>
    <div v-if="hardware" class="hardware-grid">
      <article class="hardware-card cpu-card" aria-label="CPU 硬件">
        <header class="device-card-head"><span class="device-kind">CPU</span><span v-if="coreSpec" class="device-spec">{{ coreSpec }}</span></header>
        <h3 v-if="hardware.cpu.model">{{ hardware.cpu.model }}</h3>
        <dl class="primary-metrics">
          <div v-if="hasValue(hardware.cpu.temperature_c)" class="metric-primary"><dt>温度</dt><dd>{{ metric(hardware.cpu.temperature_c, '°C') }}</dd></div>
          <div v-if="hasValue(latestSysMetric?.cpu_pct)" class="metric-primary"><dt>利用率</dt><dd>{{ metric(latestSysMetric?.cpu_pct, '%') }}</dd></div>
        </dl>
        <div v-if="hasValue(latestSysMetric?.cpu_pct)" class="metric-track" aria-label="CPU 利用率"><span :style="{ width: `${Math.min(latestSysMetric!.cpu_pct!, 100)}%` }" /></div>
        <dl class="hardware-metrics"><div v-if="measuredFrequency(hardware.cpu)"><dt>当前频率</dt><dd>{{ metric(hardware.cpu.frequency_mhz, 'MHz') }}</dd></div></dl>
      </article>
      <article v-if="!hardware.gpus.length && emptyGpuLabel" class="hardware-card gpu-card" aria-label="GPU 采集状态"><span class="device-kind">GPU</span><p class="hardware-note">{{ emptyGpuLabel }}</p></article>
      <article v-for="gpu in hardware.gpus" :key="gpu.id" class="hardware-card gpu-card" :aria-label="`GPU ${gpu.name}`">
        <header class="device-card-head"><span class="device-kind">GPU</span><span v-if="gpu.kind && gpu.kind !== 'unknown'" class="device-spec">{{ gpu.kind === 'integrated' ? '集成显卡' : '独立显卡' }}</span></header>
        <h3>{{ gpu.name }}</h3>
        <dl class="primary-metrics">
          <div v-if="hasValue(gpu.temperature_c)" class="metric-primary"><dt>温度</dt><dd>{{ metric(gpu.temperature_c, '°C') }}</dd></div>
          <div v-if="hasValue(gpu.utilization_pct)" class="metric-primary"><dt>利用率</dt><dd>{{ metric(gpu.utilization_pct, '%') }}</dd></div>
        </dl>
        <div v-if="hasValue(gpu.utilization_pct)" class="metric-track" aria-label="GPU 利用率"><span :style="{ width: `${Math.min(gpu.utilization_pct!, 100)}%` }" /></div>
        <dl class="hardware-metrics">
          <div v-if="hasValue(gpu.graphics_clock_mhz)"><dt>核心频率</dt><dd>{{ metric(gpu.graphics_clock_mhz, 'MHz') }}</dd></div>
          <div v-if="hasValue(gpu.memory_clock_mhz)"><dt>显存频率</dt><dd>{{ metric(gpu.memory_clock_mhz, 'MHz') }}</dd></div>
          <div v-if="hasValue(gpu.memory_used_mib) && hasValue(gpu.memory_total_mib)"><dt>显存</dt><dd>{{ metric(gpu.memory_used_mib) }} / {{ metric(gpu.memory_total_mib, 'MiB') }}</dd></div>
          <div v-else-if="hasValue(gpu.memory_total_mib)"><dt>显存容量</dt><dd>{{ metric(gpu.memory_total_mib, 'MiB') }}</dd></div>
          <div v-else-if="hasValue(gpu.memory_used_mib)"><dt>显存已用</dt><dd>{{ metric(gpu.memory_used_mib, 'MiB') }}</dd></div>
          <div v-if="hasValue(gpu.power_w)"><dt>功耗</dt><dd>{{ metric(gpu.power_w, 'W') }}</dd></div>
          <div v-if="hasValue(gpu.fan_pct)"><dt>转速比例</dt><dd>{{ metric(gpu.fan_pct, '%') }}</dd></div>
        </dl>
      </article>
      <article v-if="sensors.length" class="hardware-card sensors-card" aria-label="主板温度 / 风扇">
        <header class="device-card-head"><span class="device-kind">传感器</span></header>
        <dl class="sensor-list">
          <div v-for="(sensor, index) in sensors" :key="`${sensor.name}:${index}`" class="sensor-row" :title="joinSpec(sensorLabel(sensor).chip, sensor.source)"><dt>{{ sensorLabel(sensor).label }}</dt><dd>{{ metric(sensor.value, sensor.unit) }}</dd></div>
        </dl>
      </article>
    </div>
    <section v-if="inventory" class="physical-inventory" aria-label="物理机清单">
      <header class="hardware-head"><span class="hardware-title">设备规格</span><span class="hardware-note">{{ joinSpec(hardware?.machine?.vendor, hardware?.machine?.model) }}</span></header>
      <div class="spec-grid">
        <dl v-if="inventory.board || inventory.bios" class="spec-board">
          <div v-if="joinSpec(inventory.board?.vendor, inventory.board?.model)"><dt>主板</dt><dd>{{ joinSpec(inventory.board?.vendor, inventory.board?.model) }}</dd></div>
          <div v-if="joinSpec(inventory.bios?.vendor, inventory.bios?.version)"><dt>BIOS</dt><dd>{{ joinSpec(inventory.bios?.vendor, inventory.bios?.version) }}</dd></div>
        </dl>
        <div v-if="inventory.memory_modules?.length" class="memory-list" aria-label="内存条">
          <div v-for="(module, index) in inventory.memory_modules" :key="index" class="memory-item">
            <span class="hardware-note">{{ module.slot || '内存条' }}</span><strong v-if="hasValue(module.capacity_bytes)">{{ bytes(module.capacity_bytes) }}</strong>
            <span v-if="joinSpec(module.vendor, module.part_number)" class="memory-model">{{ joinSpec(module.vendor, module.part_number) }}</span>
            <span v-if="hasValue(module.configured_speed_mts)" class="hardware-note">配置 {{ metric(module.configured_speed_mts, 'MT/s') }}</span>
            <span v-if="hasValue(module.speed_mts) && module.speed_mts !== module.configured_speed_mts" class="hardware-note">标称 {{ metric(module.speed_mts, 'MT/s') }}</span>
          </div>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.hardware-panel { min-width: 0; margin: 16px 0; }
.hardware-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 14px; margin-bottom: 12px; }
.hardware-title { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 600; color: var(--text-hi); }
.hardware-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 290px), 1fr)); gap: 14px; align-items: start; }
.hardware-card { min-width: 0; padding: 20px; background: linear-gradient(140deg, rgba(158,183,229,.045), transparent 75%), var(--bg-panel); border: 1px solid rgba(158,183,229,.1); border-radius: 12px; }
.device-card-head { display: flex; align-items: center; gap: 12px; justify-content: space-between; margin-bottom: 12px; }
.device-kind { color: var(--accent); font-size: 11px; font-weight: 650; letter-spacing: .08em; }
.device-spec { color: var(--text-lo); font-size: 11px; }
h3 { margin: 0 0 22px; font-size: 15px; line-height: 1.5; color: var(--text-hi); font-weight: 550; overflow-wrap: anywhere; }
dl { margin: 0; }
dt { color: var(--text-lo); font-size: 11px; overflow-wrap: anywhere; }
dd { margin: 4px 0 0; color: var(--text-hi); font-size: 12px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.primary-metrics { display: flex; flex-wrap: wrap; gap: 20px 28px; }
.metric-primary dd { font-size: 28px; font-weight: 550; line-height: 1.3; letter-spacing: -.04em; }
.metric-track { height: 4px; border-radius: 6px; overflow: hidden; background: rgba(158,183,229,.1); margin: 15px 0 18px; }
.metric-track span { display: block; height: 100%; background: var(--accent); border-radius: inherit; }
.hardware-metrics { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px 16px; }
.primary-metrics:not(:empty) + .hardware-metrics { margin-top: 18px; }
.hardware-note { margin: 0; color: var(--text-faint); font-size: 11px; overflow-wrap: anywhere; }
.sample-status { color: #d5af80; font-size: 11px; }
.sensor-list { display: flex; flex-direction: column; }
.sensor-row { display: flex; gap: 16px; justify-content: space-between; align-items: baseline; padding: 10px 0; border-bottom: 1px solid rgba(158,183,229,.06); }
.sensor-row:last-child { border-bottom: 0; padding-bottom: 0; }
.sensor-row dt { min-width: 0; }
.sensor-row dd { flex-shrink: 0; margin: 0; }
.physical-inventory { margin-top: 14px; padding: 18px 20px; background: var(--bg-panel); border: 1px solid rgba(158,183,229,.08); border-radius: 12px; }
.spec-grid { display: grid; grid-template-columns: 1fr 1.6fr; gap: 24px; align-items: start; }
.spec-board { display: grid; gap: 12px; }
.memory-list { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,200px),1fr)); gap: 14px; }
.memory-item { display: flex; flex-wrap: wrap; gap: 5px 12px; min-width: 0; }
.memory-item strong { color: var(--text-hi); font-size: 12px; font-weight: 550; }
.memory-model { flex-basis: 100%; color: var(--text-lo); font-size: 12px; overflow-wrap: anywhere; }
@media(max-width:600px) { .spec-grid { grid-template-columns: 1fr; gap: 20px; } .hardware-card { padding: 18px; } }
</style>
