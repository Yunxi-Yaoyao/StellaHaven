<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { importRequestId } from './importRequestId';
import { api, ApiError } from '../../api/client';
import { useNotesStore } from '../../stores/notes';
import { importTreeRows, type ImportSource, type ImportTarget, type ImportEncoding } from './import-helpers';
interface Preview { entries: {path: string; title: string; kind: 'directory' | 'document' | 'attachment'; parent_path: string | null}[]; warnings: string[]; counts: { documents: number; attachments: number } }
interface Result { documents: {id: string; title: string; path: string; parent_id: string | null}[]; attachments: number; warnings: string[]; reused: boolean }
const props = defineProps<{ file: ImportSource; target: ImportTarget; disabled: boolean }>();
const emit = defineEmits<{ busy: [value: boolean]; lock: []; complete: [count: number] }>();
const store = useNotesStore();
const encoding = ref<ImportEncoding>('auto');
const preview = ref<Preview | null>(null), result = ref<Result | null>(null);
const status = ref<'pending' | 'previewing' | 'ready' | 'importing' | 'failed' | 'success'>('pending');
const error = ref('');
const refreshError = ref('');
const snapshot = ref<{target: ImportTarget; encoding: ImportEncoding; importId: string} | null>(null);
const tree = computed(() => importTreeRows((preview.value?.entries ?? []).map(e => ({ ...e, id: e.path, parent_id: e.parent_path }))));
const locked = computed(() => props.disabled || status.value === 'previewing' || status.value === 'importing');
function message(e: unknown) { return e instanceof ApiError && typeof e.detail === 'string' ? e.detail : e instanceof Error ? e.message : String(e); }
watch(() => [props.target.workspaceId, props.target.parentId], () => { if (!snapshot.value) { preview.value = null; error.value = ''; status.value = 'pending'; } });
async function form(target: ImportTarget, codec: ImportEncoding) {
  const body = new FormData();
  body.append('file', props.file instanceof Blob ? props.file : new Blob([await props.file.arrayBuffer()]), props.file.name);
  body.append('workspace_id', target.workspaceId);
  if (target.parentId) body.append('parent_id', target.parentId);
  body.append('encoding', codec);
  return body;
}
async function readPreview(codec = encoding.value) {
  if (locked.value || snapshot.value) return;
  encoding.value = codec; preview.value = null; error.value = ''; status.value = 'previewing'; emit('busy', true);
  try {
    // Explicit empty headers suppress the JSON wrapper default; browser sets multipart boundary.
    preview.value = await api<Preview>('/documents/import/zip/preview', { method: 'POST', headers: {}, body: await form({ ...props.target }, codec) });
    status.value = 'ready';
  } catch (e) { error.value = message(e); status.value = 'pending'; }
  finally { emit('busy', false); }
}
async function commit() {
  if (locked.value || !preview.value || result.value) return;
  snapshot.value ??= { target: { ...props.target }, encoding: encoding.value, importId: importRequestId() };
  emit('lock'); emit('busy', true); status.value = 'importing'; error.value = ''; refreshError.value = '';
  try {
    const frozen = snapshot.value;
    const body = await form(frozen.target, frozen.encoding); body.append('import_id', frozen.importId);
    result.value = await api<Result>('/documents/import/zip', { method: 'POST', headers: {}, body });
    status.value = 'success'; emit('complete', result.value.documents.length);
  } catch (e) { status.value = 'failed'; error.value = message(e); }
  finally {
    try { await store.refreshList(); } catch (e) { refreshError.value = `列表刷新失败：${message(e)}`; }
    emit('busy', false);
  }
}
</script>
<template>
  <article class="zip-import" :data-status="status" aria-live="polite">
    <div class="zip-heading"><strong>{{ file.name }}</strong><span>{{ status === 'success' ? '已导入' : status === 'importing' ? '正在导入…' : status === 'previewing' ? '正在预览…' : status === 'failed' ? '失败 · 可重试' : '结构化 ZIP' }}</span></div>
    <p>保留目录与附件；新建私有笔记，同名自动加后缀，不覆盖已有页面。</p>
    <div class="zip-actions" v-if="!snapshot">
      <span>正文编码</span>
      <button v-for="codec in (['auto', 'utf-8', 'gb18030'] as const)" :key="codec" :aria-pressed="encoding === codec" :disabled="locked" @click="readPreview(codec)">{{ codec === 'auto' ? '自动' : codec.toUpperCase() }}</button>
      <button :disabled="locked" @click="readPreview()">{{ preview ? '重新预览 ZIP' : '预览 ZIP' }}</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="refreshError" class="error" role="alert">{{ refreshError }}</p>
    <progress v-if="status === 'previewing' || status === 'importing'" :aria-label="status === 'previewing' ? 'ZIP 预览进度' : 'ZIP 导入进度'" />
    <template v-if="preview">
      <p>{{ preview.counts.documents }} 篇笔记 · {{ preview.counts.attachments }} 个附件 · 只读预览，不会创建内容</p>
      <ul class="zip-tree" aria-label="ZIP 只读预览">
        <li v-for="entry in tree" :key="entry.path" :style="{ paddingLeft: `${8 + Math.min(entry.depth, 8) * 16}px` }" :title="entry.path"><span class="kind">{{ entry.kind === 'directory' ? '目录' : entry.kind === 'document' ? '笔记' : '附件' }}</span>{{ entry.title }}</li>
      </ul>
      <p v-for="(warning, i) in preview.warnings" :key="i" class="warning">{{ warning }}</p>
      <button v-if="!result" class="primary" :disabled="locked" @click="commit">{{ status === 'failed' ? '重试此 ZIP' : '导入此 ZIP' }}</button>
    </template>
    <template v-if="result">
      <p class="success">已导入 {{ result.documents.length }} 篇笔记、{{ result.attachments }} 个附件{{ result.reused ? ' · 已复用上次结果，未重复创建' : '' }}</p>
      <ul class="zip-tree" aria-label="ZIP 导入结果"><li v-for="doc in result.documents" :key="doc.id">{{ doc.title }}</li></ul>
      <p v-for="(warning, i) in result.warnings" :key="i" class="warning">{{ warning }}</p>
    </template>
  </article>
</template>
<style scoped>
.zip-import { display: grid; gap: 9px; padding: 14px 0; border-bottom: 1px solid var(--accent-dim); font-size: 12px; min-width: 0; }
.zip-heading, .zip-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; } .zip-heading { justify-content: space-between; } strong { overflow-wrap: anywhere; } p { margin: 0; color: var(--text-lo); line-height: 1.6; } .zip-tree { list-style: none; padding: 4px; margin: 0; max-height: 180px; overflow: auto; background: var(--bg-raised); border-radius: var(--radius-sm); } li { padding: 5px 8px; overflow-wrap: anywhere; } .kind { color: var(--text-lo); margin-right: 8px; font-size: 10px; } button { width: fit-content; background: transparent; color: var(--text-hi); border: 1px solid var(--accent-dim); border-radius: var(--radius-sm); padding: 8px 10px; cursor: pointer; font: inherit; } button:disabled { opacity: .45; cursor: default; } button[aria-pressed=true], .primary, .success { color: var(--accent); } .error { color: var(--pink, #f99); } .warning { color: #e3b96b; } progress { width: 100%; accent-color: var(--accent); }
</style>
