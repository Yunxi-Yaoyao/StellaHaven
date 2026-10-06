<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { api } from '../../api/client';
interface BackupHealth {
  timestamp: string | null;
  status: 'missing' | 'invalid' | 'verified' | 'unverified' | 'failed' | 'stale';
  checksumverified: boolean;
  restoreverified: boolean;
  source: 'postgres-dump' | 'postgres-snapshot' | null;
}
const evidence = ref<BackupHealth | null>(null);
const loading = ref(false);
const error = ref('');
let controller: AbortController | null = null;
const statusLabels = { missing: '尚无备份证据', invalid: '证据格式无效', verified: '校验已完成',
  unverified: '校验尚未完成', failed: '备份验证失败', stale: '证据已过期（超过 48 小时）' };
const statusText = computed(() => evidence.value ? statusLabels[evidence.value.status] : '等待证据');
async function refresh() {
  controller?.abort();
  const request = new AbortController(); controller = request;
  loading.value = true; error.value = ''; evidence.value = null;
  try {
    const result = await api<BackupHealth>('/operations/backup-health', {signal:request.signal});
    if (!request.signal.aborted) evidence.value = result;
  } catch {
    if (!request.signal.aborted) error.value = '无法读取备份证据，请稍后重试。';
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}
onMounted(refresh);
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section class="backup-health" aria-labelledby="backup-health-title" :aria-busy="loading">
    <header><h3 id="backup-health-title">备份健康</h3><button type="button" :disabled="loading" @click="refresh">刷新证据</button></header>
    <p class="description">只读证据，不在此页面执行备份或恢复。dump 目录可读不等于恢复成功。</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-else-if="loading" role="status">正在读取证据…</p>
    <dl v-else-if="evidence">
      <dt>状态</dt><dd>{{ statusText }}</dd>
      <dt>最近证据</dt><dd>{{ evidence.timestamp ? new Date(evidence.timestamp).toLocaleString() : '暂无' }}</dd>
      <dt>来源</dt><dd>{{ evidence.source === 'postgres-dump' ? 'PostgreSQL dump' : evidence.source === 'postgres-snapshot' ? 'PostgreSQL 快照' : '暂无' }}</dd>
      <dt>校验和</dt><dd>{{ evidence.checksumverified ? '校验和已验证' : '校验和未验证' }}</dd>
      <dt>隔离恢复演练</dt><dd>{{ evidence.restoreverified ? '恢复已验证' : '恢复未验证' }}</dd>
    </dl>
  </section>
</template>

<style scoped>
.backup-health { border: 1px solid var(--border, #d8dbe3); border-radius: 14px; padding: 20px; }
header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
h3 { margin: 0; font-size: 1rem; }
button { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border, #d8dbe3); color: inherit; background: transparent; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.description, dt { color: var(--text-secondary, #727785); font-size: .875rem; }
dl { display: grid; grid-template-columns: minmax(95px, max-content) minmax(0, 1fr); gap: 12px 20px; }
dd { margin: 0; overflow-wrap: anywhere; }
.error { color: var(--danger, #c63d4a); }
</style>
