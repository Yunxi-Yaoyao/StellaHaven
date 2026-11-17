import { defineStore } from "pinia";
import { ref, watch } from "vue";
import {
  ensureWorkspace, saveBootstrap, listDocs, searchDocs, listTrash, listRecent,
  listWorkspaces, createWorkspace, renameWorkspace, deleteWorkspace,
  createDoc, restoreDoc, updateDoc,
  clearAllDocs as clearAllDocsApi,
  type Doc, type Bootstrap,
} from "../api/notes";
import { toast } from "../composables/useToast";
import { ApiError } from "../api/client";
import { workspaceDeletionContext } from '../modules/notes/workspaceDeletion';

// 树节点：Doc + 子节点数组（客户端从平铺列表建树，个人规模 200 篇全量构建无压力）
export interface TreeNode extends Doc {
  children: TreeNode[];
}

export function buildTree(docs: Doc[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  const roots: TreeNode[] = [];
  for (const d of docs) map.set(d.id, { ...d, children: [] });
  for (const n of map.values()) {
    if (n.parent_id && map.has(n.parent_id)) {
      map.get(n.parent_id)!.children.push(n);
    } else {
      roots.push(n); // 父级不在列表里（回收站等）也按根级显示，防孤儿消失
    }
  }
  // 兄弟间按标题排序：数字升序 → A-Z → 中文拼音（老婆定的）
  const collator = new Intl.Collator("zh-Hans-CN", { numeric: true });
  // zh 排序器会把拉丁字母排到中文后面，手动分组：0数字 1拉丁 2中文
  const rankOf = (t: string): number => {
    const ch = t.trim().charAt(0);
    if (/\d/.test(ch)) return 0;
    if (/[a-zA-Z]/.test(ch)) return 1;
    return 2;
  };
  const sortRec = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      const ra = rankOf(a.title);
      const rb = rankOf(b.title);
      if (ra !== rb) return ra - rb;
      return collator.compare(a.title, b.title);
    });
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

// 收集某节点的所有后代 id（移动/删除时排除用）
export function collectDescendants(roots: TreeNode[], id: string): Set<string> {
  const result = new Set<string>();
  const walk = (nodes: TreeNode[]) => {
    for (const n of nodes) {
      if (n.id === id) {
        const grab = (x: TreeNode) => { result.add(x.id); x.children.forEach(grab); };
        grab(n);
        return true;
      }
      if (walk(n.children)) return true;
    }
    return false;
  };
  walk(roots);
  return result;
}

export const useNotesStore = defineStore("notes", () => {
  const workspaceId = ref<string>("");
  let workspaceEpoch = 0, workspaceDeleteBusy = false;
  watch(workspaceId, () => ++workspaceEpoch, {flush:'sync'});
  const userId = ref<string>("");
  const workspaces = ref<{ id: string; name: string; user_id: string }[]>([]);
  const docs = ref<Doc[]>([]);
  const allDocs = ref<Doc[]>([]); // authoritative workspace hierarchy, never search-filtered
  const trash = ref<Doc[]>([]);
  const recent = ref<Doc[]>([]);
  const searchQuery = ref("");
  const searching = ref(false);
  const draggingId = ref<string | null>(null); // 树拖拽：正在被拖的节点
  // 全量文档缓存：搜索时 docs 只剩命中项，路径/面包屑计算需要完整上下文
  const docsCache = new Map<string, Doc>();
  function cacheDocs(list: Doc[]) {
    for (const d of list) docsCache.set(d.id, d);
  }
  // 标签：全量标签表 + 全量关联（个人规模一次拉全）
  const tags = ref<{ id: string; name: string; color: string | null }[]>([]);
  const docTags = ref<{ doc_id: string; tag_id: string }[]>([]);
  const filterTagId = ref<string | null>(null); // 列表按标签筛选

  const templateRootId = ref<string | null>(null);
  const hideProtectedId = ref<string | null>(null);
  const pendingDelete = ref<{kind:'note'|'trash'|'empty'|'batch'; doc:Doc|null; docs?:Doc[]; childCount:number|null; count:number; workspaceId:string} | null>(null);

  let sessionEpoch = 0;
  function resetSession() {
    sessionEpoch++; ++listSequence;
    userId.value = ''; workspaceId.value = ''; workspaces.value = [];
    allDocs.value = []; docs.value = []; trash.value = []; recent.value = []; tags.value = []; docTags.value = [];
    searchQuery.value = ''; searching.value = false; filterTagId.value = null;
    draggingId.value = null; pendingDelete.value = null; templateRootId.value = null; hideProtectedId.value = null; docsCache.clear();
  }
  async function bootstrap() {
    const epoch = sessionEpoch;
    const b: Bootstrap = await ensureWorkspace();
    if (epoch !== sessionEpoch) return;
    userId.value = b.userId;
    workspaceId.value = b.workspaceId;
    // Only the document list blocks first content; auxiliary panels hydrate independently.
    void Promise.allSettled([refreshRecent(), refreshWorkspaces(), refreshTags()]);
    await refreshList();
  }

  async function refreshTags() {
    const { listTags, listAllDocTags } = await import("../api/notes");
    const epoch = sessionEpoch;
    const result = await Promise.all([listTags(), listAllDocTags()]);
    if (epoch === sessionEpoch) [tags.value, docTags.value] = result;
  }

  /** 文档路径（面包屑字符串）：装修日志 / 材料清单 / 瓷砖选购 */
  function pathOf(docId: string): string {
    const chain: string[] = [];
    // 优先全量缓存（搜索时 docs 只剩命中项，找父级会断链）
    const find = (id: string | null | undefined) =>
      id ? (docsCache.get(id) ?? docs.value.find((d) => d.id === id)) : undefined;
    let cur = find(docId);
    let guard = 0;
    while (cur && guard++ < 20) {
      chain.unshift(cur.title);
      cur = find(cur.parent_id);
    }
    return chain.join(" / ");
  }

  /** 文档的标签对象列表 */
  function tagsOf(docId: string) {
    const ids = new Set(docTags.value.filter((r) => r.doc_id === docId).map((r) => r.tag_id));
    return tags.value.filter((t) => ids.has(t.id));
  }

  /** 打标签：没有就新建（自动分配调色板颜色） */
  async function tagDoc(docId: string, name: string) {
    const TAG_PALETTE = ["#c9d4e8", "#e8a0bf", "#9ec9a8", "#e8c98a", "#a8b8e8", "#d4a8e8", "#8ad4d4"];
    const { createTag, addDocTag } = await import("../api/notes");
    let tag = tags.value.find((t) => t.name === name);
    if (!tag) {
      tag = await createTag(name, TAG_PALETTE[tags.value.length % TAG_PALETTE.length]);
    }
    if (docTags.value.some((r) => r.doc_id === docId && r.tag_id === tag!.id)) return;
    await addDocTag(docId, tag.id);
    await refreshTags();
  }

  async function untagDoc(docId: string, tagId: string) {
    const { removeDocTag } = await import("../api/notes");
    await removeDocTag(docId, tagId);
    await refreshTags();
  }

  async function refreshWorkspaces() {
    const epoch = sessionEpoch;
    const result = await listWorkspaces(userId.value);
    if (epoch === sessionEpoch) workspaces.value = result;
  }

  /** 切换工作区：记住选择 + 全量重载（列表频道由页面监听 workspaceId 重连） */
  async function switchWorkspace(id: string) {
    if (id === workspaceId.value) return;
    workspaceId.value = id;
    saveBootstrap({ userId: userId.value, workspaceId: id });
    searchQuery.value = "";
    await Promise.all([refreshList(), refreshRecent(), refreshTrash()]);
  }

  async function addWorkspace(name: string) {
    const ws = await createWorkspace(userId.value, name);
    await refreshWorkspaces();
    await switchWorkspace(ws.id);
    toast(`已建工作区「${name}」`);
  }

  async function renameCurrentWorkspace(name: string) {
    await renameWorkspace(workspaceId.value, name);
    await refreshWorkspaces();
    toast("已重命名 ✓");
  }

  function workspaceDeletionAdmission(admitted: () => boolean) {
    const epoch = sessionEpoch, navigation = workspaceEpoch;
    const current = workspaceDeletionContext({get userId(){return userId.value;}, get workspaceId(){return workspaceId.value;}});
    return () => epoch === sessionEpoch && navigation === workspaceEpoch && current() && admitted();
  }

  /** Reconcile without replaying DELETE; prove acknowledged IDs absent first. */
  async function reconcileWorkspaceDeletions(deletedIds: string[], admitted: () => boolean = () => true) {
    const valid = workspaceDeletionAdmission(admitted);
    if (!valid()) return false;
    try {
      const inventory = await listWorkspaces(userId.value);
      if (!valid() || inventory.some(w => deletedIds.includes(w.id) || w.user_id !== userId.value)) return false;
      workspaces.value = inventory;
      if (deletedIds.includes(workspaceId.value)) {
        const next = inventory[0];
        if (next) await switchWorkspace(next.id);
        else {
          // ensureWorkspace writes its cache internally before admission can be
          // checked. Reuse owner creation + switchWorkspace so only this still-
          // current operation may save a replacement bootstrap selection.
          const replacement = await createWorkspace(userId.value, '云曦的笔记本');
          if (!valid()) return false;
          workspaces.value = [replacement];
          await switchWorkspace(replacement.id);
        }
      }
      return true;
    } catch { return false; }
  }

  /** One explicit confirmation admits one sequential pass; never retry a DELETE. */
  async function deleteWorkspaceBatch(ids: string[], admitted: () => boolean = () => true) {
    const valid = workspaceDeletionAdmission(admitted);
    const results: {id:string; status:'deleted'|'failed'|'unknown'|'skipped'}[] = [];
    if (workspaceDeleteBusy) return {results:[...new Set(ids)].map(id => ({id,status:'skipped' as const})), refreshFailed:false};
    workspaceDeleteBusy = true;
    try {
      for (const id of new Set(ids)) {
        if (!valid() || !workspaces.value.some(w => w.id === id && w.user_id === userId.value)) { results.push({id,status:'skipped'}); continue; }
        try { await deleteWorkspace(id, true, valid); results.push({id, status:'deleted'}); }
        catch (error) { results.push({id, status:error instanceof ApiError && error.status < 500 ? 'failed' : 'unknown'}); }
      }
      if (!valid()) return {results, refreshFailed:false};
      const verified = await reconcileWorkspaceDeletions(results.filter(r=>r.status==='deleted').map(r=>r.id),valid);
      return {results, refreshFailed:!verified};
    } finally { workspaceDeleteBusy = false; }
  }

  /** 删除当前工作区：返回结果码让 UI 决定弹什么（deleted / not_empty / has_trash） */
  async function deleteCurrentWorkspace(force = false): Promise<string> {
    try {
      await deleteWorkspace(workspaceId.value, force);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const code = (e.detail as any)?.code;
        return code === "has_trash" ? "has_trash" : "not_empty";
      }
      return "error";
    }
    await refreshWorkspaces();
    const next = workspaces.value[0];
    if (next) {
      await switchWorkspace(next.id);
    } else {
      localStorage.removeItem("stella_bootstrap");
      await bootstrap();
    }
    return "deleted";
  }

  let listSequence = 0, trashSequence = 0;
  async function refreshList() {
    const sequence = ++listSequence;
    if (!workspaceId.value) return;
    const workspace = workspaceId.value;
    const query = searchQuery.value.trim();
    const [inventory, matches] = await Promise.all([listDocs(workspace), query ? searchDocs(workspace, query) : Promise.resolve(null)]);
    const result = matches ?? inventory;
    if (sequence !== listSequence || workspace !== workspaceId.value || query !== searchQuery.value.trim()) return;
    allDocs.value = inventory;
    docsCache.clear();
    cacheDocs(inventory);
    searching.value = !!query;
    docs.value = query ? result.sort((a, b) => b.updated_at.localeCompare(a.updated_at)) : result;
    cacheDocs(docs.value); // 搜索结果只含命中项，但路径计算需要全量上下文
  }

  async function refreshTrash() {
    if (!workspaceId.value) return;
    const epoch = sessionEpoch, ws = workspaceId.value, sequence = ++trashSequence;
    const result = await listTrash(workspaceId.value);
    if (sequence === trashSequence && epoch === sessionEpoch && ws === workspaceId.value) trash.value = result;
  }

  function acceptDeletionReadback(ws: string, inventory: Doc[], deletedDocs: Doc[]) {
    if (ws !== workspaceId.value) return;
    ++listSequence; ++trashSequence;
    allDocs.value = inventory; trash.value = deletedDocs;
    const ids = new Set(inventory.map(d=>d.id));
    docs.value = searchQuery.value ? docs.value.filter(d=>ids.has(d.id)) : inventory;
    docsCache.clear(); cacheDocs(inventory);
  }

  async function refreshRecent() {
    if (!workspaceId.value) return;
    const epoch = sessionEpoch, ws = workspaceId.value;
    const result = await listRecent(workspaceId.value);
    if (epoch === sessionEpoch && ws === workspaceId.value) recent.value = result;
  }

  function childCount(id: string): number {
    return allDocs.value.filter((d) => d.workspace_id === workspaceId.value && d.parent_id === id).length;
  }

  async function createNew(parentId?: string, initial?: {title:string;content:string}): Promise<Doc> {
    const doc = await createDoc(workspaceId.value, initial?.title || "未命名笔记", parentId, initial?.content || "");
    // The POST is authoritative; a secondary read must not turn success into failure.
    if (doc.workspace_id === workspaceId.value) {
      ++listSequence; // discard list requests started before the create completed
      docs.value = [doc, ...docs.value.filter((d) => d.id !== doc.id)];
      allDocs.value = [doc, ...allDocs.value.filter(d => d.id !== doc.id)];
      cacheDocs([doc]);
    }
    return doc;
  }

  /** All note deletion entry points are mediated by DeleteNoteDialog. */
  function requestDelete(doc: Doc) {
    if (doc.id === templateRootId.value) { hideProtectedId.value = doc.id; return; }
    if (!pendingDelete.value) pendingDelete.value = {kind:'note',doc,childCount:null,count:1,workspaceId:workspaceId.value};
  }

  function requestDeleteBatch(selected: Doc[]) {
    if (pendingDelete.value) return;
    const unique = [...new Map(selected.filter(d => d.workspace_id === workspaceId.value && d.id !== templateRootId.value && allDocs.value.some(row => row.id === d.id)).map(d => [d.id, {...d}])).values()];
    if (unique.length) pendingDelete.value = {kind:'batch',doc:null,docs:unique,childCount:null,count:unique.length,workspaceId:workspaceId.value};
  }

  // Descendant counts come only from the complete server delete preview.
  function requestPurge(doc: Doc) {
    if (!pendingDelete.value) pendingDelete.value = {kind:'trash',doc,childCount:null,count:1,workspaceId:workspaceId.value};
  }
  function requestEmptyTrash() {
    if (!pendingDelete.value && trash.value.length) pendingDelete.value = {kind:'empty',doc:null,childCount:0,count:trash.value.length,workspaceId:workspaceId.value};
  }

  async function restore(id: string, cascade: boolean) {
    const r = await restoreDoc(id, cascade);
    await Promise.all([refreshList(), refreshTrash()]);
    if (r.reattached) toast("父页面不在了，已挂回根级");
    else if (r.restored > 1) toast(`已还原 ${r.restored} 篇（含下挂）`);
  }


  /** 清空笔记：全部移入回收站（可还原），返回篇数 */
  async function clearAll(): Promise<number> {
    const r = await clearAllDocsApi(workspaceId.value);
    await Promise.all([refreshList(), refreshTrash()]);
    return r.trashed;
  }

  /** 移动到：改 parent_id。循环防护后端兜底，前端先过滤候选 */
  async function moveTo(doc: Doc, newParentId: string | null): Promise<boolean> {
    try {
      await updateDoc(doc.id, doc.updated_at, { parent_id: newParentId });
      await refreshList();
      toast("已移动 ✓");
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) toast(typeof e.detail === "string" ? e.detail : "移动未完成，请刷新目录核对目标与版本喵~");
      return false;
    }
  }

  return {
    workspaceId, userId, workspaces, docs, allDocs, trash, recent, searchQuery, searching, pendingDelete,
    tags, docTags, filterTagId, draggingId,
    templateRootId, hideProtectedId,
    acceptDeletionReadback, resetSession, bootstrap, refreshList, refreshTrash, refreshRecent, refreshWorkspaces, refreshTags,
    tagsOf, tagDoc, untagDoc, pathOf,
    switchWorkspace, addWorkspace, renameCurrentWorkspace, deleteCurrentWorkspace, deleteWorkspaceBatch, reconcileWorkspaceDeletions,
    childCount, createNew, requestDelete, requestDeleteBatch, requestPurge, requestEmptyTrash, restore, clearAll, moveTo,
  };
});
