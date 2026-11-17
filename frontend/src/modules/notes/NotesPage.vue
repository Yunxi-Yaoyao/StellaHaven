<script setup lang="ts">
import {notifyClientPreferenceChange} from '../settings/clientPreferenceEvents';
import { ref, computed, provide, onMounted, onUnmounted, onActivated, onDeactivated, nextTick } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from "vue-router";
import { watch } from "vue";
import { getDoc, listTemplates, updateDoc } from "../../api/notes";
import { toast } from "../../composables/useToast";
const route = useRoute(), router = useRouter();
import { storeToRefs } from "pinia";
import { useNotesStore, type TreeNode } from "../../stores/notes";
import DocList from "./DocList.vue";
import DocEditor from "./DocEditor.vue";
import WebProjectPane from './WebProjectPane.vue';
import DetachedSourcePane from './DetachedSourcePane.vue';
import type { FileProject } from '../../api/projectFiles';
import ProjectFiles from './ProjectFiles.vue';
import {projectCatalogKey,PROJECT_ASSET_MIME} from './projectAssetCopy';
import { useWebProjectCatalog } from './useWebProjectCatalog';
import TrashPanel from "./TrashPanel.vue";
import DeleteNoteDialog from "./DeleteNoteDialog.vue";
import AttachmentsPanel from "./AttachmentsPanel.vue";
import GraphPanel from "./GraphPanel.vue";
import MoveDialog from "./MoveDialog.vue";
import ImportDialog from "./ImportDialog.vue";
import NewChildDialog from "./NewChildDialog.vue";
import NotesSettings from './NotesSettings.vue';
import { useNotesPreferencesStore } from '../../stores/notesPreferences';
const preferences = useNotesPreferencesStore();
const settingsOpen = ref(false);
const drawerScope = ref('');
const settingsScope = computed(() => JSON.stringify([auth.me?.id, auth.sessionGeneration, auth.requestEpoch, auth.suspended, auth.sessionClosing, store.workspaceId]));
let settingsReturnFocus: HTMLElement | null = null;
async function openSettings() { await openSettingsDrawer(); }
async function openSettingsDrawer() {
  const current = catalog.capture();
  const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  if (!(await prepareNavigation()) || !current()) return;
  settingsReturnFocus = returnFocus;
  drawerScope.value = settingsScope.value;
  settingsOpen.value = true;
  void nextTick(() => { if (settingsOpen.value && current()) pageRoot.value?.querySelector<HTMLElement>('.notes-settings-drawer button')?.focus(); });
}
function closeSettings() {
  settingsOpen.value = false;
  settingsReturnFocus?.focus({preventScroll:true});
  if (route.query.settings === 'open') {
    const query = {...route.query}; delete query.settings;
    void router.replace({query});
  }
}

watch(() => [auth.suspended, auth.sessionClosing], () => { if (auth.suspended || auth.sessionClosing) settingsOpen.value = false; });
const newChildTarget = ref<{id:string|null;title:string}|null>(null);
const editorRef = ref<InstanceType<typeof DocEditor> | null>(null);
import { auth } from "../home/auth";
import { isImportFilename, type ImportSource } from './import-helpers';

defineOptions({ name: 'NotesPage' });
const pageRoot = ref<HTMLElement | null>(null);
let scrollSnapshot: [HTMLElement, number, number][] = [];
onBeforeRouteLeave(async to => {
  // Revoked owners cannot flush private work. Only allow the deliberate public
  // escape after auth has discarded the owner; retained/suspended owners still
  // obey the normal save and catalog fences, as do all private destinations.
  if (to.meta.public && !auth.me) return;
  if (!(await prepareNavigation())) return false;
  scrollSnapshot = Array.from(pageRoot.value?.querySelectorAll<HTMLElement>('.rich-editor,.cm-scroller,.preview,.items,.toc-list') ?? [])
    .map(el => [el, el.scrollTop, el.scrollLeft]);
});
onBeforeRouteUpdate(async to => {
  if ((typeof to.query.doc === 'string' && to.query.doc !== currentId.value) || (to.query.settings === 'open' && !settingsOpen.value))
    return await prepareNavigation();
});
const store = useNotesStore();
if (store.userId !== auth.me?.id) store.resetSession();
const { pendingDelete } = storeToRefs(store);
const protectedExplanation = ref('');
watch(() => store.workspaceId, async workspace => {
  store.templateRootId = null;
  if (!workspace) return;
  try {
    const result = await listTemplates(workspace, true);
    if (store.workspaceId === workspace && active.value) { store.templateRootId = result.root_id; await store.refreshList(); }
  } catch { toast('模板目录初始化失败，未改变原笔记；请重新打开笔记页重试'); }
});
watch(() => store.hideProtectedId, async id => {
  if (!id) return;
  await openSettingsDrawer();
  await nextTick();
  const section = pageRoot.value?.querySelector<HTMLDetailsElement>('#notes-hidden-folders');
  if (section) { section.open = true; section.scrollIntoView({block:'center'}); }
  preferences.bindOwner(auth.me?.id??'');
  if (await preferences.load()) {
    const ids = [...new Set([...(preferences.draft.hidden_folders??[]), id])];
    if (await preferences.save({hidden_folders:ids})) protectedExplanation.value = '内置目录不可删除，已为你隐藏。可在隐藏目录中取消勾选恢复显示。';
  }
  store.hideProtectedId = null;
});
watch(() => [auth.me?.id, auth.suspended, auth.sessionClosing], () => {
  preferences.bindOwner(auth.suspended || auth.sessionClosing ? '' : auth.me?.id??'');
  if (preferences.owner) void preferences.load();
}, {immediate:true});
const currentId = ref<string | null>(null);
const currentProject = ref<FileProject | null>(null);
const currentDetached = ref(false);
const detachedRef = ref<InstanceType<typeof DetachedSourcePane> | null>(null);
const directoryRef = ref<InstanceType<typeof ProjectFiles> | null>(null);
const currentDirectory = computed(()=>currentProject.value?.directories?.some(d=>d.id===currentId.value)??false);
function projectUpdated(project:FileProject){if(currentProject.value?.id===project.id)currentProject.value=project;void catalog.load(true);}
const projectRef = ref<InstanceType<typeof WebProjectPane> | null>(null);

const LS_CURRENT = "stella_current_doc";
const trashOpen = ref(false);
const attachOpen = ref(false);
const graphOpen = ref(false);
const ready = ref(false);
const initError = ref('');
const active = ref(true);
const catalog = useWebProjectCatalog(store, active);
provide(projectCatalogKey,catalog);
const { error: catalogError, projectError, permitted: projectActive } = catalog;
const failedProjectId=ref<string|null>(null);
// Import, restore and list-channel updates may introduce project IDs. Do not
// keep using an older successful catalog for a newly refreshed document list.
// Keep the mounted selection pinned: a background failure cannot discard it.
watch(() => store.allDocs, () => { if (ready.value && projectActive.value) void refreshCatalog(); }, {flush:'sync'});
async function refreshCatalog() {
  const current=catalog.capture(), id=currentId.value;
  if (!await catalog.load(true) || !current() || currentId.value!==id) return;
  const identity=catalog.identityFor(id), detached=!!catalog.detachedFor(id);
  if (currentProject.value?.id===identity?.id && currentDetached.value===detached) return;
  const project=identity&&id ? await catalog.loadProject(id) : null;
  if(identity&&!project)return;
  if (!await prepareNavigation() || !current() || currentId.value!==id) return;
  currentProject.value=project;currentDetached.value=detached;
}
watch([() => auth.me?.id, () => auth.sessionGeneration, () => store.workspaceId], () => {
  currentId.value = null; currentProject.value = null; currentDetached.value = false;
  trashOpen.value = false; attachOpen.value = false; graphOpen.value = false;
}, {flush:'sync'});
watch(() => [auth.me?.id, auth.sessionGeneration, auth.requestEpoch, auth.suspended, auth.sessionClosing, store.workspaceId], () => { settingsOpen.value = false; }, {flush:'sync'});
const moving = ref<TreeNode | null>(null);
const importing = ref<{ files: ImportSource[]; workspaceId: string; parentId: string | null } | null>(null);
const importBusy = ref(false);
const sourceMoveBusy = ref(false);
const sourceMovingId = ref<string|null>(null);
async function moveTextOutside(id:string,parentId:string|null) {
  const current=catalog.capture();
  if (sourceMoveBusy.value || !current() || !window.confirm('移出后仍为私有源码文件，原项目将无法读取，相对引用不会自动修复。继续？')) return;
  if (!await catalog.load(true) || !current()) return;
  const project=await catalog.loadProject(id);
  if (!project?.files.some(file=>file.id===id&&file.kind==='text') || catalog.identityFor(parentId)) {toast('文件归属已变化，未移动，请重试');return;}
  if (!await prepareNavigation() || !current()) return;
  sourceMovingId.value=id;sourceMoveBusy.value=true;
  try {
    const doc=await getDoc(id);
    if (!current() || doc.workspace_id!==store.workspaceId) return;
    await updateDoc(id,doc.updated_at,{parent_id:parentId});
    if (!current()) return;
    await store.refreshList();
    toast('已移出项目，保留私有源码编辑');
  } catch(e) {if(current())toast(e instanceof Error?e.message:'移动结果未确认，请刷新目录核对；源码不会转换');}
  finally {sourceMoveBusy.value=false;sourceMovingId.value=null;}
  if(current())await refreshCatalog();
}
async function openImport(files: ImportSource[] = [], parentId: string | null = null) {
  if (importing.value || !store.workspaceId) return;
  if (!(await prepareNavigation())) return;
  importing.value = { files, workspaceId: store.workspaceId, parentId };
}
async function openImported(id:string) {
  if (!importing.value || importBusy.value) return;
  // openLinkedDoc verifies the returned ID/workspace and rechecks the final
  // editor/project prepareNavigation barrier. Keep results when it refuses.
  await openLinkedDoc(id);
  if (currentId.value === id) importing.value = null;
}
function captureDragOver(event: DragEvent) {
  if (store.draggingId || !event.dataTransfer?.types.includes('Files')) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'copy';
}
function captureDrop(event: DragEvent) {
  const element=event.target instanceof Element?event.target:null;
  if(store.draggingId&&element?.closest('.doc-list')) {
    const id=store.draggingId,project=catalog.projectFor(id),parentId=element.closest<HTMLElement>('.row')?.dataset.importParent??null;
    if(catalog.identityFor(id)&&id!==catalog.identityFor(id)?.id&&!catalog.identityFor(parentId)&&!catalog.assetFor(id)&&!project?.files.some(file=>file.id===id&&file.kind==='binary')) {
      event.preventDefault();event.stopPropagation();store.draggingId=null;void moveTextOutside(id,parentId);return;
    }
  }
  if(event.dataTransfer?.types.includes(PROJECT_ASSET_MIME)&&(event.target as Element).closest(".doc-list")&&!(event.target as Element).closest(".row")){
    event.preventDefault();event.stopPropagation();store.draggingId=null;toast("请把项目图片拖到普通笔记正文，以独立复制附件；原项目文件不会移动。");return;
  }
  if (store.draggingId || !event.dataTransfer) return;
  const files: ImportSource[] = Array.from(event.dataTransfer.files);
  for (const item of Array.from(event.dataTransfer.items)) {
    const entry = item.webkitGetAsEntry?.();
    if (entry?.isDirectory) files.push({ name: entry.name, size: 0, isDirectory: true, arrayBuffer: async () => new ArrayBuffer(0) });
  }
  if (!files.length) return;
  const inList = !!element?.closest('.doc-list');
  // Every supported picker format also overrides editor drops, never the draft.
  if (!inList && !files.some(file => isImportFilename(file.name) || /\.html?$/i.test(file.name) || file.isDirectory)) return;
  event.preventDefault();
  event.stopPropagation(); // Never append imported Markdown to an open draft.
  const parentId = inList ? element?.closest<HTMLElement>('[data-import-parent]')?.dataset.importParent ?? null : null;
  openImport(files, parentId);
}

// 列表栏折叠（桌面记忆 + 移动端抽屉）
const listCollapsed = ref(
  localStorage.getItem("stella_list_fold") === "1" || window.innerWidth <= 768
);
function toggleList() {
  listCollapsed.value = !listCollapsed.value;
  notifyClientPreferenceChange('stella_list_fold',listCollapsed.value ? '1' : '0');
  localStorage.setItem("stella_list_fold", listCollapsed.value ? "1" : "0");
}

// 列表频道：任何文档变动（保存/新建/删除/还原）→ 刷新列表 + 回收站
let listWs: WebSocket | null = null;
let listWsTimer: ReturnType<typeof setTimeout> | null = null;
let listWsDead = false;

function connectListWs() {
  if (!store.workspaceId || listWsDead || auth.suspended || auth.sessionClosing) return;
  if (listWs && listWs.readyState <= WebSocket.OPEN) return; // 已有活连接不重复开
  const proto = location.protocol === "https:" ? "wss" : "ws";
  listWs = new WebSocket(`${proto}://${location.host}/ws/list/${store.workspaceId}`);
  listWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "list_changed") {
        if (importBusy.value) return; // ImportDialog refreshes once after the batch.
        store.refreshList();
        store.refreshTrash();
      }
    } catch {
      /* 忽略坏消息 */
    }
  };
  const socket = listWs;
  listWs.onclose = () => {
    if (listWs !== socket) return;
    listWs = null;
    if (!listWsDead) listWsTimer = setTimeout(connectListWs, 3000);
  };
}

// This event comes from the mounted current-workspace editor. A plain /notes
// push does not reveal a collapsed list (particularly the mobile drawer).
function revealHistory() {
  if (!active.value || auth.suspended || auth.sessionClosing) return;
  store.searchQuery = ''; store.filterTagId = null;
  listCollapsed.value = false;
  void store.refreshList().catch(() => toast('笔记列表刷新失败，请重试搜索或重新打开工作区'));
}

function stopListWs() {
  listWsDead = true;
  if (listWsTimer) clearTimeout(listWsTimer);
  listWsTimer = null;
  if (listWs) { listWs.onclose = null; listWs.onmessage = null; listWs.close(); }
  listWs = null;
}
watch(()=>[auth.suspended,auth.sessionClosing],()=>{if(auth.suspended||auth.sessionClosing)stopListWs();else if(active.value&&ready.value){listWsDead=false;connectListWs();}},{flush:'sync'});
async function initialize() {
  initError.value = '';
  const owner = auth.me?.id, session = auth.sessionGeneration, epoch = auth.requestEpoch;
  try {
    await store.bootstrap();
    if (!active.value || owner !== auth.me?.id || session !== auth.sessionGeneration || epoch !== auth.requestEpoch) return;
    ready.value = true;
    if (active.value) { listWsDead = false; connectListWs(); }
    const navigation = navigationSequence;
    if (!(await catalog.load()) || navigation !== navigationSequence) return;
    if (typeof route.query.doc === "string") await openLinkedDoc(route.query.doc, route.hash);
    else {
      const saved = localStorage.getItem(LS_CURRENT);
      const id = saved && store.docs.some(d => d.id === saved) ? saved : store.docs[0]?.id;
      if(id)await selectInitial(id);
    }
    if (active.value) { listWsDead = false; connectListWs(); }
  } catch { initError.value = '笔记加载失败，请重试喵~'; }
}
onMounted(initialize);
onActivated(() => {
  active.value = true;
  void nextTick(() => { for (const [el, top, left] of scrollSnapshot) { el.scrollTop = top; el.scrollLeft = left; } });
  if (!ready.value) return; // Initial activation is handled by initialize.
  listWsDead = false;
  connectListWs();
  void Promise.allSettled([store.refreshList(), store.refreshRecent(), store.refreshWorkspaces(), store.refreshTags()]);
});
onDeactivated(() => { active.value = false; pendingDelete.value=null; settingsOpen.value=false; ++linkedSequence; importing.value = null; newChildTarget.value = null; stopListWs(); });
onUnmounted(() => { active.value = false; pendingDelete.value=null; stopListWs(); });

// 切换工作区 → 列表频道重连 + 关掉所有面板（图谱/附件/回收站都是旧工作区的数据）+ 打开新工作区的第一篇
async function selectInitial(id:string) {
  const current=catalog.capture(), seq=navigationSequence, identity=catalog.identityFor(id);
  const project=identity ? await catalog.loadProject(id) : null;
  if(!current()||seq!==navigationSequence)return;
  if(identity&&!project){failedProjectId.value=id;return;}
  currentId.value=id;currentProject.value=project;currentDetached.value=!!catalog.detachedFor(id);
}
async function onWsSwitched() {
  newChildTarget.value = null;
  stopListWs();
  listWsDead = !active.value;
  connectListWs();
  trashOpen.value = false;
  attachOpen.value = false;
  graphOpen.value = false;
  currentId.value = null; currentProject.value = null; currentDetached.value = false;
  if (!(await catalog.load())) return;
  const id=store.docs[0]?.id;
  if(id)await selectInitial(id);
  if (currentId.value) localStorage.setItem(LS_CURRENT, currentId.value);
}

let linkedSequence = 0;
async function openLinkedDoc(id: string, hash = '') {
  const seq = ++linkedSequence;
  const current = catalog.capture();
  const owner = auth.me?.id, session = auth.sessionGeneration, epoch = auth.requestEpoch;
  const identityCurrent = () => active.value && !auth.suspended && !auth.sessionClosing && owner === auth.me?.id && session === auth.sessionGeneration && epoch === auth.requestEpoch;
  try {
    if (currentId.value !== id && !(await prepareNavigation())) return;
    const nav = navigationSequence;
    const target = await getDoc(id);
    if (seq !== linkedSequence || nav !== navigationSequence || !current() || target.id !== id) return;
    if (target.workspace_id !== store.workspaceId) {
      if (!(await prepareNavigation()) || !current()) return;
      await store.switchWorkspace(target.workspace_id);
      if (seq !== linkedSequence || !identityCurrent() || store.workspaceId !== target.workspace_id) return;
      await onWsSwitched();
    }
    if (seq !== linkedSequence || !identityCurrent()) return;
    await onOpen(id, hash);
  } catch { if (identityCurrent()) toast('链接指向的笔记不可访问或已删除喵~'); }
}
watch(() => route.query.doc, id => {
  if (ready.value && active.value && route.path === '/notes' && typeof id === 'string' && id !== currentId.value) void openLinkedDoc(id, route.hash);
});
// Failed barriers must not change selection, route, panels or workspace.
let navigationSequence = 0;
async function prepareNavigation(): Promise<boolean> {
  const seq = ++navigationSequence, current = catalog.capture();
  if (importBusy.value || sourceMoveBusy.value || !current()) return false;
  try {
    let allowed = true;
    if (currentProject.value && !trashOpen.value && !attachOpen.value && !graphOpen.value)
      allowed = currentDirectory.value ? !!directoryRef.value && await directoryRef.value.prepareNavigation() : !!projectRef.value && await projectRef.value.prepareNavigation();
    else if (currentDetached.value && !trashOpen.value && !attachOpen.value && !graphOpen.value)
      allowed = !!detachedRef.value && await detachedRef.value.prepareNavigation();
    else if (editorRef.value) allowed = await editorRef.value.prepareNavigation();
    return allowed && current() && seq === navigationSequence;
  } catch { toast('内容尚未保存，已保留当前页面，请重试'); return false; }
}
async function showPanel(panel: 'trash' | 'attachments' | 'graph') {
  if (!(await prepareNavigation())) return;
  trashOpen.value = panel === 'trash';
  attachOpen.value = panel === 'attachments';
  graphOpen.value = panel === 'graph';
}
async function onOpen(id: string, hash = '') {
  const current = catalog.capture(), seq = ++navigationSequence;
  if (!(await catalog.load()) || !current() || seq !== navigationSequence) return;
  const identity=catalog.identityFor(id);
  const project=identity ? await catalog.loadProject(id) : null;
  if(!current() || seq!==navigationSequence)return;
  if(identity&&!project){failedProjectId.value=id;return;}
  failedProjectId.value=null;
  // Do not flush before a slow catalog fetch: the user can edit again while
  // that fetch is pending. The final barrier belongs immediately before commit.
  if (currentId.value !== id && !(await prepareNavigation())) return;
  trashOpen.value = false;
  attachOpen.value = false;
  graphOpen.value = false;
  currentId.value = id;
  currentProject.value = project;
  currentDetached.value = !!catalog.detachedFor(id);
  if (route.query.doc !== id || route.hash !== hash) await router.replace({path:"/notes",query:{...route.query,doc:id},hash});
  localStorage.setItem(LS_CURRENT, id); // 记住正在看的
  // 移动端打开笔记后自动收起列表抽屉
  if (window.innerWidth <= 768) listCollapsed.value = true;
  // 打开 → 服务端已戳 last_viewed_at，稍后刷新最近查看
  setTimeout(() => store.refreshRecent(), 300);
}

async function onNewChild(node: TreeNode | null) {
  if (!(await prepareNavigation())) return;
  trashOpen.value = false;
  newChildTarget.value = {id: node?.id ?? null, title: node?.title ?? (store.workspaces.find(w => w.id === store.workspaceId)?.name || '工作区根目录')};
}

async function onNewChildById(parentId: string) {
  if (!(await prepareNavigation())) return;
  const parent = store.allDocs.find(d => d.id === parentId);
  if (parent) newChildTarget.value = {id: parentId, title: parent.title};
}

async function onMove(node: TreeNode) {
  if (!(await prepareNavigation())) return;
  moving.value = node;
}

async function onDel(node: TreeNode) {
  if ((currentProject.value || currentDetached.value) && !(await beforeTrash([node.id]))) return;
  store.requestDelete(node as any);
}

function onSaved() {
  store.refreshList();
}

async function beforeTrash(ids: readonly string[]): Promise<boolean> {
  const current = catalog.capture();
  if (!current() || sourceMoveBusy.value) return false;
  if (currentDetached.value) return !!detachedRef.value && await detachedRef.value.prepareDeletion() && current();
  if(currentProject.value&&currentDirectory.value)return !!directoryRef.value&&await directoryRef.value.prepareDeletion()&&current();
  if (currentProject.value && projectRef.value) {
    try { return await projectRef.value.prepareDeletion() && current(); }
    catch { toast('内容尚未保存，未删除，请重试'); return false; }
  }
  if (!currentId.value || !ids.includes(currentId.value)) return true;
  // A loaded current editor is required; never treat an unavailable barrier as success.
  return !!editorRef.value && await editorRef.value.prepareDeletion();
}
async function onDeleted() {
  if (currentId.value && !store.allDocs.some(doc=>doc.id===currentId.value)) {
    currentId.value = null; currentProject.value = null; currentDetached.value = false;
    if (!(await catalog.load(true))) return;
    const next = store.docs[0]?.id;
    if (next) await onOpen(next);
  }
}
watch(() => [route.query.settings,ready.value], () => { if (active.value&&ready.value&&route.query.settings === 'open') void openSettings(); });
</script>

<template>
  <div ref="pageRoot" class="notes-page" :style="{'--notes-font-size':`${preferences.draft.font_size??16}px`,'--notes-line-height':preferences.draft.line_height??1.8,'--notes-read-width':`${preferences.draft.read_width??800}px`,'--notes-code-wrap':(preferences.draft.code_wrap??true)?'pre-wrap':'pre'}" :aria-busy="!ready" @keydown.esc="listCollapsed=true" @dragover.capture="captureDragOver" @drop.capture="captureDrop">
    <div v-if="projectError" class="project-catalog-error" role="alert">{{projectError}} <button class="ghost-btn" @click="failedProjectId && onOpen(failedProjectId)">重试此项目</button></div>
    <div v-if="catalogError && currentId" class="project-catalog-error" role="alert">{{ catalogError }} <button class="ghost-btn" @click="catalog.load(true)">重试</button></div>
    <Transition v-if="drawerScope === settingsScope && active && !auth.suspended && !auth.sessionClosing" name="notes-settings-slide"><aside v-if="settingsOpen" class="notes-settings-drawer" role="dialog" aria-label="笔记设置" @keydown.esc.stop="closeSettings">
      <button aria-label="关闭笔记设置" @click="closeSettings">关闭</button>
      <NotesSettings />
      <div v-if="protectedExplanation" role="alertdialog" aria-label="内置目录已隐藏" class="protected-explanation"><p>{{protectedExplanation}}</p><button @click="protectedExplanation=''">知道了</button></div>
    </aside></Transition>
    <ImportDialog v-if="importing" v-bind="importing" @busy="importBusy = $event" @close="importing = null" @open="openImported" />
    <!-- 列表收起时的窄条把手 -->
    <div v-if="!listCollapsed" class="list-drawer-shade" @click="toggleList" />
    <DocList
      v-show="!listCollapsed" :style="!ready ? { pointerEvents: 'none', opacity: .65 } : undefined"
      :current-id="currentId"
      :trash-open="trashOpen"
      :attach-open="attachOpen"
      :graph-open="graphOpen"
      :before-workspace-change="prepareNavigation"
      :before-workspace-delete="() => beforeTrash(currentId ? [currentId] : [])"
      @open="onOpen"
      @show-trash="showPanel('trash')"
      @show-attachments="showPanel('attachments')"
      @show-graph="showPanel('graph')"
      @new-child="onNewChild"
      @settings="openSettings"
      @move="onMove"
      @del="onDel"
      @switched="onWsSwitched"
      @fold="toggleList"
      @import="openImport()"
    />
    <GraphPanel v-if="graphOpen" @close="graphOpen = false" @open="onOpen" />
    <AttachmentsPanel v-else-if="attachOpen" @close="attachOpen = false" @open="onOpen" />
    <TrashPanel v-else-if="trashOpen" @close="trashOpen = false" />
    <ProjectFiles v-else-if="currentProject && currentId && currentDirectory" ref="directoryRef" :key="currentId" :project="currentProject" :file-id="currentId" :active="projectActive && !pendingDelete && !(sourceMoveBusy && currentId===sourceMovingId)" @open="onOpen" @directory="toggleList" @updated="projectUpdated" />
    <WebProjectPane v-else-if="currentProject && currentId" ref="projectRef" :key="currentId" :project="currentProject" :file-id="currentId" :active="projectActive && !pendingDelete && !(sourceMoveBusy && currentId===sourceMovingId)" @open="onOpen" @directory="toggleList" @saved="onSaved" @updated="projectUpdated" />
    <DetachedSourcePane v-else-if="currentDetached && currentId" ref="detachedRef" :key="currentId" :file-id="currentId" :active="projectActive && !pendingDelete && !(sourceMoveBusy && currentId===sourceMovingId)" @directory="toggleList" @saved="onSaved" />
    <DocEditor
      ref="editorRef"
      v-else-if="currentId"
      :key="currentId"
      :doc-id="currentId"
      @directory="toggleList"
      @history="revealHistory"
      @saved="onSaved"
      @deleted="onDeleted"
      @create-child="onNewChildById"
      @open="onOpen"
    />
    <div v-else class="blank">
      <div class="blank-icon">📝</div>
      <p>{{ catalogError || initError || (ready ? '选一篇，或者新建一篇开始写' : '正在载入笔记…') }}</p>
      <button class="ghost-btn" v-if="catalogError || initError" @click="initialize">重试</button>
      <template v-else-if="ready">
        <button class="ghost-btn" @click="toggleList" aria-label="笔记目录">笔记目录</button>
        <button class="primary" @click="onNewChild(null)">新建笔记</button>
      </template>
    </div>

    <NewChildDialog v-if="newChildTarget" :parent-id="newChildTarget.id" :parent-title="newChildTarget.title" @close="newChildTarget = null" @created="newChildTarget = null; onOpen($event)" />

    <!-- 移动对话框 -->
    <MoveDialog v-if="moving" :node="moving" @done="moving = null" @cancel="moving = null" />

    <DeleteNoteDialog v-if="pendingDelete&&active&&!auth.suspended&&!auth.sessionClosing" :before-trash="beforeTrash" @deleted="onDeleted" />

  </div>

</template>

<style scoped>
.project-catalog-error{position:absolute;top:0;right:0;z-index:91;max-width:min(520px,90%);padding:12px;background:var(--bg-raised);color:var(--danger);border:1px solid var(--danger);border-radius:8px;font-size:13px}.project-catalog-error button{margin-left:8px}
.notes-settings-slide-enter-active,.notes-settings-slide-leave-active{transition:transform .2s ease,opacity .2s ease}
.notes-settings-slide-enter-from,.notes-settings-slide-leave-to{transform:translateX(100%);opacity:0}
.notes-settings-drawer :deep(.notes-settings){border:0;padding:4px 8px;background:transparent;border-radius:0}
@media(prefers-reduced-motion:reduce){.notes-settings-slide-enter-active,.notes-settings-slide-leave-active{transition:none}}
.notes-settings-drawer{position:absolute;inset:0 0 0 auto;width:min(480px,100%);z-index:90;overflow:auto;background:var(--bg-panel);box-shadow:-8px 0 30px #0005;padding:16px;box-sizing:border-box}.notes-settings-drawer>button{color:var(--text-hi);background:var(--bg-raised);border:1px solid var(--accent-dim);padding:8px 16px;margin-bottom:12px;border-radius:8px}.protected-explanation{position:sticky;bottom:0;background:var(--bg-raised);border:1px solid var(--accent);padding:16px;border-radius:8px;color:var(--text-hi)}
.notes-page :deep(.markdown-body),.notes-page :deep(.milkdown .ProseMirror){font-size:var(--notes-font-size);line-height:var(--notes-line-height);max-width:var(--notes-read-width);margin-inline:auto;box-sizing:border-box;width:100%}
.notes-page :deep(.markdown-body pre),.notes-page :deep(.milkdown pre){white-space:var(--notes-code-wrap);overflow-wrap:anywhere}


.notes-page {
  display: flex;
  height: 100%;
  min-height: 0;
  min-width: 0;
  border-radius: var(--radius);
  overflow: hidden;
  position: relative;
}
.blank {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--bg-panel);
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--text-faint);
}
.blank-icon { font-size: 36px; opacity: 0.6; }
.loading { height: 100%; display: grid; place-items: center; color: var(--text-faint); }

/* 列表收起窄条把手 */
.list-strip {
  width: 26px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  background: var(--bg-panel);
  border-radius: var(--radius) 0 0 var(--radius);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  color: var(--text-faint);
  cursor: pointer;
  transition: all var(--transition);
}
.list-strip:hover { color: var(--accent); background: var(--bg-raised); }
@media (max-width: 768px) {
  .list-strip {
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    height: 64px;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    z-index: 75;
    box-shadow: 2px 0 10px rgba(0, 0, 0, 0.35);
  }
}

.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 100;
}
.dialog {
  width: 380px;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
}
.head { padding: 14px 18px; font-size: 14px; font-weight: 600; }
.body { padding: 0 18px 14px; font-size: 13px; color: var(--text-lo); }
.btns { display: flex; flex-direction: column; gap: 8px; padding: 0 18px 16px; }
.btns button {
  padding: 9px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-dim);
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--transition);
}
.btns button:hover { background: var(--bg-raised); }
.btns button.danger { border-color: var(--pink); color: var(--pink); }
.btns button.cancel { border-color: var(--text-faint); color: var(--text-faint); }
.list-drawer-shade { display: none; }
@media(max-width:768px) { .list-drawer-shade { display:block; position:fixed; inset:0; background:#0008; z-index:74; } .dialog { width:min(380px,94vw); overflow-wrap:anywhere; } }
</style>
