<script setup lang="ts">
import { computed } from 'vue';
import type { HardwareInfo } from '../../api/servers';
import Icon from '../../shell/Icon.vue';
const props = defineProps<{ hardware?: HardwareInfo | null; status: string; now: number; refreshFailed?: boolean }>();
// Hardware is a 60s snapshot, not the 5s detail response. Match the system
// sample tolerance (three periods); a fresh heartbeat does not refresh it.
const sampledTime = computed(() => props.hardware?.sampled_at ? Date.parse(props.hardware.sampled_at) : NaN);
const sampleReason = computed(() => [
  props.status !== 'online' ? '节点离线' : '',
  props.refreshFailed ? '详情刷新失败' : '',
  !Number.isFinite(sampledTime.value) ? '采样时间未知' : '',
  props.now - sampledTime.value > 180000 ? '采样已过期' : '',
].filter(Boolean).join(' · '));
function value(number: number | null | undefined, unit = ''): string {
  return typeof number === 'number' && Number.isFinite(number) ? `${number}${unit ? ` ${unit}` : ''}` : '未读取';
}
function gpuAvailability(status: string): string {
  const labels: Record<string, string> = {
    no_nvidia_gpu: '未检测到 NVIDIA GPU',
    nvidia_smi_failed: 'GPU 查询失败',
    nvidia_smi_missing: 'GPU 不可用 · 未安装 nvidia-smi',
    unavailable: 'GPU 不可用',
  };
  return labels[status] || `GPU 未读取${status && status !== 'available' ? ` · ${status}` : ''}`;
}
</script>

<template>
  <section class="hardware-panel" aria-label="硬件信息">
    <header class="hardware-head">
      <span class="hardware-title"><Icon name="server" :size="14" />硬件信息</span>
      <span v-if="hardware" class="sample-status" role="status">
        {{ sampleReason ? `上次采样 · 非实时 · ${sampleReason}` : '最近采样' }} ·
        <time v-if="Number.isFinite(sampledTime)" :datetime="hardware.sampled_at">{{ new Date(sampledTime).toLocaleString('zh-CN', { hour12: false }) }}</time>
      </span>
    </header>
    <p v-if="!hardware" class="hardware-source">未读取 · Agent 尚未上报硬件信息</p>
    <div v-if="hardware" class="hardware-grid">
      <article class="hardware-card cpu-card" aria-label="CPU 硬件">
        <h3>CPU <span>{{ hardware.cpu.model || '未读取' }}</span></h3>
        <dl class="hardware-metrics">
          <div><dt>核心 / 线程</dt><dd>{{ value(hardware.cpu.physical_cores, '核') }} / {{ value(hardware.cpu.logical_cores, '线程') }}</dd></div>
          <div :title="hardware.cpu.temperature_source || '未读取'"><dt>温度</dt><dd>{{ hardware.cpu.temperature_c == null && hardware.availability.cpu_temperature === 'unavailable' ? '不可用' : value(hardware.cpu.temperature_c, '°C') }}</dd></div>
          <div :title="hardware.cpu.frequency_source || '未读取'"><dt>当前频率</dt><dd>{{ value(hardware.cpu.frequency_mhz, 'MHz') }}</dd></div>
          <div :title="hardware.cpu.frequency_source || '未读取'"><dt>最高频率</dt><dd>{{ value(hardware.cpu.max_frequency_mhz, 'MHz') }}</dd></div>
        </dl>
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
        <p class="hardware-source">来源 {{ gpu.source || '未读取' }}</p>
      </article>
      <article v-if="hardware.sensors.length" class="hardware-card sensors-card" aria-label="主板温度 / 风扇">
        <h3>主板 / 其他传感器</h3>
        <dl class="hardware-metrics">
          <div v-for="(sensor, index) in hardware.sensors" :key="`${sensor.source}:${sensor.kind}:${sensor.name}:${index}`" :title="sensor.source">
            <dt>{{ sensor.name }}</dt><dd>{{ value(sensor.value, sensor.unit) }}</dd>
          </div>
        </dl>
      </article>
    </div>
  </section>
</template>

<style scoped>
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
