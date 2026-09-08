<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import Dropdown from '../../shell/Dropdown.vue';
import { api } from '../../api/client';
import { listDocs, type Doc } from '../../api/notes';
import { useNotesStore } from '../../stores/notes';
import { prepareImport, queueImports, runImportBatch, type ImportEncoding, type ImportSource, type ImportTarget, type ImportRow } from './import-helpers';

const props = defineProps<{ files: ImportSource[]; workspaceId: string; parentId: string | null }>();
const emit = defineEmits<{ close: []; busy: [value: boolean] }>();
const store = useNotesStore();
const rows = ref(queueImports(props.files));
const workspaceId = ref(props.workspaceId);
const parentId = ref(props.parentId ?? '');
const docs = ref<Doc[]>([]);
const busy = ref(false);
const preparing = ref(true);
const loadingTargets = ref(false);
const frozen = ref<ImportTarget | null>(null);
const error = ref('');
const finalizeError = ref('');
const synced = ref<number | null>(null);
const phase = ref('等待导入');
const completed = computed(() => rows.value.filter(row => row.status === 'success' || row.status === 'failed').length);
const actionable = computed(() => rows.value.filter(row => row.payload || ['ready', 'importing', 'failed', 'success'].includes(row.status)).length);
const readCount = computed(() => rows.value.filter(row => !['reading', 'pending'].includes(row.status)).length);
const currentFile = computed(() => rows.value.find(row => row.status === 'importing')?.file.name);

const workspaceOptions = computed(() => store.workspaces.map(w => ({ value: w.id, label: w.name })));
const parentOptions = computed(() => [{ value: '', label: '工作区根目录' }, ...docs.value.map(d => ({ value: d.id, label: d.title, desc: d.file_path }))]);
const encodingOptions = [{ value: 'auto', label: '自动 / BOM' }, { value: 'utf-8', label: 'UTF-8' }, { value: 'gb18030', label: 'GB18030' }];
const eligible = computed(() => rows.value.filter(r => r.status === 'ready' || r.status === 'failed').length);
const successes = computed(() => rows.value.filter(r => r.status === 'success').length);
const labels: Record<ImportRow['status'], string> = { pending: '等待读取', reading: '读取中', ready: '待导入', 'encoding-error': '请指定编码', rejected: '已拒绝', importing: '导入中', success: '已导入', failed: '失败 · 可重试' };
async function loadTargets() {
  loadingTargets.value = true;
  error.value = '';
  try { docs.value = await listDocs(workspaceId.value); }
  catch (e) { error.value = `无法加载完整目标列表：${message(e)}`; }
  finally { loadingTargets.value = false; }
}
async function changeWorkspace(value: string | number | boolean) {
  if (frozen.value || busy.value) return;
  workspaceId.value = String(value); parentId.value = ''; docs.value = [];
  await loadTargets();
}
function message(e: unknown) { return e instanceof Error ? e.message : String(e); }
async function reDecode(row: ImportRow, value: string | number | boolean) {
  if (busy.value || row.payload) return;
  row.encoding = value as ImportEncoding;
  await prepareImport(row);
}
onMounted(async () => {
  await Promise.all([loadTargets(), ...rows.value.map(row => prepareImport(row))]);
  preparing.value = false;
});
async function run() {
  if (busy.value || preparing.value || loadingTargets.value) return;
  phase.value = '正在检查目标位置…'; busy.value = true; emit('busy', true); error.value = ''; finalizeError.value = ''; synced.value = null;
  // Never follow the selected editor or a later workspace switch.
  const target = frozen.value ?? { workspaceId: workspaceId.value, parentId: parentId.value || null };
  frozen.value = { ...target };
  try {
    const all = await listDocs(target.workspaceId); // Full workspace, never filtered store.docs.
    if (target.parentId && !all.some(d => d.id === target.parentId)) throw new Error('目标笔记已不存在，请关闭后重新选择');
    phase.value = '正在导入文件…';
    await runImportBatch(rows.value, target, all.map(d => d.title), payload =>
      api<{ id: string }>('/documents/', { method: 'POST', body: JSON.stringify(payload) }));
    const ids = rows.value.filter(r => r.status === 'success' && r.documentId).map(r => r.documentId!);
    if (ids.length) {
      phase.value = '正在同步双链…';
      try {
        const result = await api<{ synced: number }>('/documents/import/finalize', {
          method: 'POST', body: JSON.stringify({ workspace_id: target.workspaceId, document_ids: ids }),
        });
        synced.value = result.synced;
      } catch (e) { finalizeError.value = `笔记已创建，但双链同步失败：${message(e)}。可重试同步，不会重复创建成功笔记。`; }
    }
  } catch (e) { error.value = message(e); }
  finally {
    phase.value = '正在刷新列表…';
    try { await store.refreshList(); } // Exactly one refresh per run; no editor navigation.
    catch (e) { error.value += ` 列表刷新失败：${message(e)}`; }
    phase.value = '本轮处理完成'; busy.value = false; emit('busy', false);
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="import-mask" @click.self="!busy && emit('close')" @keydown.esc="!busy && emit('close')">
      <section class="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title" tabindex="-1">
        <header><h2 id="import-title">导入 Markdown / 文本</h2><button :disabled="busy" aria-label="关闭导入" @click="emit('close')">✕</button></header>
        <p>每个文件新建一篇私有笔记，不覆盖旧笔记、不切换当前编辑器。最多 50 个文件，单个 5 MiB，每批 20 MiB。</p>
        <fieldset :disabled="busy || !!frozen || loadingTargets" class="targets">
          <label>工作区<Dropdown :model-value="workspaceId" :options="workspaceOptions" @update:model-value="changeWorkspace" /></label>
          <label>导入到<Dropdown :model-value="parentId" :options="parentOptions" @update:model-value="parentId = String($event)" /></label>
        </fieldset>
        <p v-if="frozen">目标已锁定，失败重试仍导入原位置。</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p v-if="finalizeError" class="warning" role="alert">{{ finalizeError }}</p>
        <div class="import-progress" aria-live="polite">
          <template v-if="preparing"><span>正在读取文件 {{ readCount }} / {{ rows.length }}…</span><progress aria-label="文件读取进度" :value="readCount" :max="rows.length || 1" /></template>
          <template v-else><span>{{ currentFile ? `正在导入：${currentFile}` : busy ? phase : frozen ? '本轮处理完成' : `已读取 ${rows.length} 个文件，确认位置后点击导入` }}</span><progress aria-label="文件导入进度" :value="completed" :max="actionable || 1" /><span>{{ completed }} / {{ actionable }} 已处理 · {{ successes }} 成功</span></template>
        </div>
        <div class="import-rows" aria-live="polite">
          <article v-for="row in rows" :key="row.id" class="import-row" :data-status="row.status">
            <div class="row-heading"><strong>{{ row.file.name }}</strong><span>{{ labels[row.status] }}</span></div>
            <div v-if="row.title !== row.file.name.replace(/\.(md|txt)$/i, '')">新标题：{{ row.title }}</div>
            <p v-if="row.error" class="error">{{ row.error }}</p>
            <p v-if="row.warning" class="warning">{{ row.warning }}</p>
            <fieldset v-if="row.status === 'encoding-error'" :disabled="busy"><legend>重试解码</legend><Dropdown :model-value="row.encoding" :options="encodingOptions" @update:model-value="reDecode(row, $event)" /></fieldset>
          </article>
        </div>
        <footer><span>{{ preparing ? '正在读取文件…' : `已导入 ${successes} / ${rows.length}` }}<template v-if="synced !== null"> · 双链已同步 {{ synced }} 篇</template></span>
          <button :disabled="busy" @click="emit('close')">{{ successes ? '完成' : '取消' }}</button>
          <button class="primary" :disabled="busy || preparing || loadingTargets || (!eligible && !finalizeError)" @click="run">{{ busy ? '导入中…' : eligible ? (frozen ? '重试未成功文件' : `导入 ${eligible} 篇`) : '重试双链同步' }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.import-progress { display: grid; gap: 6px; font-size: 12px; color: var(--text-lo); }
.import-progress progress { width: 100%; height: 7px; accent-color: var(--accent); border: none; border-radius: 4px; overflow: hidden; }
.import-progress progress::-webkit-progress-bar { background: var(--bg-raised); }
.import-progress progress::-webkit-progress-value { background: var(--accent); transition: width .15s; }

.import-mask { position: fixed; inset: 0; z-index: 200; background: rgba(0,0,0,.62); display: grid; place-items: center; padding: 16px; }
.import-dialog { width: min(680px, 100%); max-height: 90dvh; display: flex; flex-direction: column; gap: 14px; padding: 22px; background: var(--bg-panel); color: var(--text-hi); border: 1px solid var(--accent-dim); border-radius: var(--radius); box-shadow: 0 20px 60px #0006; }
header, footer, .row-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { font-size: 18px; margin: 0; } p { margin: 0; font-size: 12px; line-height: 1.6; color: var(--text-lo); }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0; } .targets { display: flex; gap: 18px; } label { display: grid; gap: 6px; font-size: 12px; min-width: 0; }
fieldset:disabled { opacity: .6; pointer-events: none; } .import-rows { overflow-y: auto; min-height: 70px; flex: 1; }
.import-row { padding: 12px 0; border-bottom: 1px solid var(--bg-raised); font-size: 12px; display: grid; gap: 6px; } strong { overflow-wrap: anywhere; } .row-heading span { flex-shrink: 0; color: var(--text-lo); }
.error { color: var(--pink, #f99); } .warning { color: #e3b96b; } [data-status=success] .row-heading span { color: var(--accent); }
button { border: 1px solid var(--accent-dim); background: transparent; color: var(--text-hi); padding: 7px 12px; border-radius: var(--radius-sm); cursor: pointer; } button:disabled { opacity: .45; cursor: default; } .primary { color: var(--accent); } footer { flex-wrap: wrap; font-size: 12px; } footer span { margin-right: auto; }
@media(max-width: 520px) { .targets { flex-direction: column; } .import-dialog { padding: 16px; } }
</style>
