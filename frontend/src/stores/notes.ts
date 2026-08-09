import { defineStore } from "pinia";
import { ref } from "vue";
import {
  ensureWorkspace, saveBootstrap, listDocs, searchDocs, listTrash, listRecent,
  listWorkspaces, createWorkspace, renameWorkspace, deleteWorkspace,
  createDoc, deleteDoc, restoreDoc, updateDoc, emptyTrash as emptyTrashApi,
  type Doc, type Bootstrap,
} from "../api/notes";
import { toast } from "../composables/useToast";
import { ApiError } from "../api/client";

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
  // 兄弟间按更新时间倒序（老婆定的：默认排序即可）
  const sortRec = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
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
  const userId = ref<string>("");
  const workspaces = ref<{ id: string; name: string; user_id: string }[]>([]);
  const docs = ref<Doc[]>([]);
  const trash = ref<Doc[]>([]);
  const recent = ref<Doc[]>([]);
  const searchQuery = ref("");
  const searching = ref(false);

  // 删除确认弹窗状态（有下挂时由 NotesPage 弹三选框）
  const pendingDelete = ref<{ doc: Doc; childCount: number } | null>(null);

  async function bootstrap() {
    const b: Bootstrap = await ensureWorkspace();
    userId.value = b.userId;
    workspaceId.value = b.workspaceId;
    await Promise.all([refreshList(), refreshRecent(), refreshWorkspaces()]);
  }

  async function refreshWorkspaces() {
    workspaces.value = await listWorkspaces(userId.value);
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

  async function refreshList() {
    if (!workspaceId.value) return;
    if (searchQuery.value.trim()) {
      searching.value = true;
      docs.value = await searchDocs(workspaceId.value, searchQuery.value.trim());
      docs.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    } else {
      searching.value = false;
      docs.value = await listDocs(workspaceId.value);
    }
  }

  async function refreshTrash() {
    if (!workspaceId.value) return;
    trash.value = await listTrash(workspaceId.value);
  }

  async function refreshRecent() {
    if (!workspaceId.value) return;
    recent.value = await listRecent(workspaceId.value);
  }

  function childCount(id: string): number {
    return docs.value.filter((d) => d.parent_id === id).length;
  }

  async function createNew(parentId?: string): Promise<Doc> {
    const doc = await createDoc(workspaceId.value, "未命名笔记", parentId);
    await refreshList();
    return doc;
  }

  /** 点删除：有下挂 → 弹三选框；没有 → 直接删 */
  function requestDelete(doc: Doc) {
    const n = childCount(doc.id);
    if (n > 0) {
      pendingDelete.value = { doc, childCount: n };
    } else {
      doDelete(doc.id, true);
    }
  }

  async function doDelete(id: string, cascade: boolean) {
    pendingDelete.value = null;
    await deleteDoc(id, cascade);
    await Promise.all([refreshList(), refreshTrash()]);
  }

  async function restore(id: string, cascade: boolean) {
    const r = await restoreDoc(id, cascade);
    await Promise.all([refreshList(), refreshTrash()]);
    if (r.reattached) toast("父页面不在了，已挂回根级");
    else if (r.restored > 1) toast(`已还原 ${r.restored} 篇（含下挂）`);
  }

  async function purge(id: string) {
    await deleteDoc(id); // 回收站里的再删 = 物理删除
    await refreshTrash();
  }

  /** 一键清空回收站，返回清了几篇 */
  async function emptyAllTrash(): Promise<number> {
    const r = await emptyTrashApi(workspaceId.value);
    await refreshTrash();
    return r.purged;
  }

  /** 移动到：改 parent_id。循环防护后端兜底，前端先过滤候选 */
  async function moveTo(doc: Doc, newParentId: string | null): Promise<boolean> {
    try {
      await updateDoc(doc.id, doc.updated_at, { parent_id: newParentId });
      await refreshList();
      toast("已移动 ✓");
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) toast("不能移动到它自己或它的子页面下面");
      return false;
    }
  }

  return {
    workspaceId, userId, workspaces, docs, trash, recent, searchQuery, searching, pendingDelete,
    bootstrap, refreshList, refreshTrash, refreshRecent, refreshWorkspaces,
    switchWorkspace, addWorkspace, renameCurrentWorkspace, deleteCurrentWorkspace,
    childCount, createNew, requestDelete, doDelete, restore, purge, emptyAllTrash, moveTo,
  };
});
