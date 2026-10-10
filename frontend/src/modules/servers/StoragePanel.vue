<script setup lang="ts">
import { computed } from 'vue';
import type { PhysicalInventory, StorageItem } from '../../api/servers';
import { bytes, hasValue, joinSpec, metric } from './hardwareDisplay';
const props = defineProps<{ storage?: StorageItem[] | null; inventory?: PhysicalInventory | null; now?: number }>();
// Inventory is a fallback, never an extra duplicate list. Legacy physical usage
// mixed raw capacities and shared filesystem usage; it cannot be attributed here.
const disks = computed<StorageItem[]>(() => {
  const reported = (props.storage || []).filter(item => item.kind === 'physical');
  if (reported.length) return reported;
  return (props.inventory?.disks || []).map(disk => ({ kind: 'physical', device: disk.name || '',
    mount: disk.name || '', fstype: '', total: disk.size_bytes!, used: null, percent: null,
    model: disk.model, bus: disk.bus, usage_scope: 'unmeasured' }));
});
const volumes = computed(() => (props.storage || []).filter(item => item.kind !== 'physical')
  .slice().sort((a, b) => Number(isSystem(a)) - Number(isSystem(b)) || a.mount.localeCompare(b.mount)));
function isSystem(item: StorageItem): boolean { return item.mount === '/' || item.mount === '/boot/efi'; }
function canMeasure(item: StorageItem): boolean {
  return item.usage_scope !== 'shared_pool' && item.usage_scope !== 'unmeasured' && hasValue(item.percent);
}
function relation(item: StorageItem): string {
  const mounts = [...new Set([...(item.pool_mounts || []), ...(item.volume_mounts || [])])];
  return mounts.length ? `${item.usage_scope === 'shared_pool' ? '存储池' : '卷'} ${mounts.join(' · ')}` : '';
}
const stale = computed(() => (props.storage || []).some(item => item.sampled_at && props.now != null
  && props.now - Date.parse(item.sampled_at) > 180000));
</script>

<template>
  <section class="storage-panel" aria-label="存储">
    <header class="storage-head"><h2>存储</h2><span v-if="stale" class="storage-status" role="status">数据已过期</span></header>
    <p v-if="!disks.length && !volumes.length" class="storage-note">存储尚未采集</p>
    <section v-if="volumes.length" class="volume-list" aria-label="存储卷 / 存储池">
      <h3>存储卷 / 存储池</h3>
      <div v-for="(item, index) in volumes" :key="`${item.device}:${item.mount}:${index}`" class="volume-row" :class="{ 'system-volume': isSystem(item) }" :title="item.device">
        <div class="volume-name"><strong>{{ item.mount }}</strong><span v-if="item.fstype">{{ item.fstype }}</span></div>
        <div class="volume-usage">
          <span v-if="hasValue(item.used) && hasValue(item.total)">{{ bytes(item.used) }} / {{ bytes(item.total) }}</span>
          <span v-else-if="hasValue(item.total)">{{ bytes(item.total) }}</span>
          <div v-if="canMeasure(item)" class="usage-track" :aria-label="`${item.mount} 占用率`"><span :style="{ width: `${Math.min(item.percent!, 100)}%` }" :class="{ warn: item.percent! > 80 }" /></div>
        </div>
        <strong v-if="canMeasure(item)" class="volume-percent">{{ metric(item.percent, '%') }}</strong>
      </div>
    </section>
    <p v-else-if="disks.length" class="storage-note">卷用量尚未采集</p>
    <section v-if="disks.length" class="physical-disk-list" aria-label="物理盘清单">
      <h3>物理盘 <span>{{ disks.length }} 块</span></h3>
      <div class="disk-columns" aria-hidden="true"><span>设备</span><span>型号</span><span>容量</span><span>接口</span><span>归属卷 / 池</span></div>
      <div v-for="(item, index) in disks" :key="`${item.device}:${index}`" class="physical-disk-row">
        <strong class="disk-device">{{ item.device || item.mount }}</strong>
        <span v-if="item.model" class="disk-model">{{ item.model }}</span><span v-else class="disk-model" />
        <span class="disk-capacity">{{ bytes(item.total) }}</span>
        <span class="disk-bus">{{ joinSpec(item.bus) }}</span>
        <span class="disk-relation">{{ relation(item) }}</span>
      </div>
    </section>
  </section>
</template>

<style scoped>
.storage-panel { min-width: 0; margin: 0 0 20px; padding: 20px; background: var(--bg-panel); border: 1px solid rgba(158,183,229,.1); border-radius: 12px; }
.storage-head { display: flex; gap: 14px; align-items: baseline; margin-bottom: 18px; }
h2 { margin: 0; color: var(--text-hi); font-size: 14px; font-weight: 600; }
h3 { margin: 0 0 10px; font-size: 11px; color: var(--text-lo); font-weight: 500; }
h3 span { margin-left: 8px; color: var(--text-faint); }
.storage-note { margin: 0; color: var(--text-faint); font-size: 12px; }
.storage-status { font-size: 11px; color: #d5af80; }
.volume-row { display: grid; grid-template-columns: minmax(120px,1fr) minmax(150px,2fr) 64px; gap: 24px; align-items: center; padding: 12px 0; }
.volume-row + .volume-row { border-top: 1px solid rgba(158,183,229,.055); }
.volume-name { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.volume-name strong { color: var(--text-hi); font-size: 13px; font-weight: 550; overflow-wrap: anywhere; }
.volume-name span { font-size: 10px; color: var(--text-faint); }
.volume-usage { min-width: 0; color: var(--text-lo); font-size: 11px; font-variant-numeric: tabular-nums; }
.usage-track { height: 4px; margin-top: 7px; border-radius: 4px; overflow: hidden; background: rgba(158,183,229,.1); }
.usage-track span { display: block; height: 100%; border-radius: inherit; background: var(--accent); }
.usage-track .warn { background: #d5af80; }
.volume-percent { text-align: right; color: var(--text-hi); font-size: 14px; font-weight: 500; font-variant-numeric: tabular-nums; }
.system-volume .volume-name strong, .system-volume .volume-percent { color: var(--text-lo); font-size: 11px; }
.system-volume .usage-track span { background: #65758d; }
.physical-disk-list { margin-top: 20px; padding-top: 18px; border-top: 1px solid rgba(158,183,229,.08); }
.disk-columns, .physical-disk-row { display: grid; grid-template-columns: minmax(65px,.7fr) minmax(140px,1.5fr) minmax(90px,.8fr) minmax(45px,.5fr) minmax(140px,1.5fr); gap: 16px; align-items: baseline; }
.disk-columns { color: var(--text-faint); font-size: 10px; padding: 2px 0 9px; }
.physical-disk-row { padding: 11px 0; color: var(--text-lo); font-size: 12px; border-top: 1px solid rgba(158,183,229,.045); }
.physical-disk-row > * { min-width: 0; overflow-wrap: anywhere; }
.disk-device { font-weight: 500; color: var(--text-hi); font-size: 11px; }
.disk-capacity { font-variant-numeric: tabular-nums; }
.disk-bus, .disk-relation { color: var(--text-faint); font-size: 11px; }
@media(max-width:800px) {
  .disk-columns { display: none; }
  .physical-disk-row { grid-template-columns: 85px minmax(0,1fr); gap: 5px 12px; }
  .disk-device { grid-column: 1; }
  .disk-model { grid-column: 2; }
  .disk-capacity { grid-column: 2; }
  .disk-bus { grid-column: 1; grid-row: 2; }
  .disk-relation { grid-column: 2; }
}
@media(max-width:480px) {
  .storage-panel { padding: 18px; }
  .volume-row { grid-template-columns: minmax(0,1fr) 58px; gap: 6px 12px; }
  .volume-name { grid-column: 1; flex-wrap: wrap; gap: 4px 8px; }
  .volume-percent { grid-column: 2; grid-row: 1; }
  .volume-usage { grid-column: 1 / -1; grid-row: 2; }
}
</style>
