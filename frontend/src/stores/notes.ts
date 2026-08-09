import { defineStore } from "pinia";
import { ref } from "vue";
import {
  ensureWorkspace, listDocs, searchDocs, listTrash,
  createDoc, deleteDoc, restoreDoc, type Doc,
} from "../api/notes";

// 笔记模块的全局状态：工作区、文档列表、回收站
export const useNotesStore = defineStore("notes", () => {
  const workspaceId = ref<string>("");
  const docs = ref<Doc[]>([]);
  const trash = ref<Doc[]>([]);
  const searchQuery = ref("");
  const searching = ref(false);

  async function bootstrap() {
    workspaceId.value = await ensureWorkspace();
    await refreshList();
  }

  async function refreshList() {
    if (!workspaceId.value) return;
    if (searchQuery.value.trim()) {
      searching.value = true;
      docs.value = await searchDocs(workspaceId.value, searchQuery.value.trim());
    } else {
      searching.value = false;
      docs.value = await listDocs(workspaceId.value);
    }
    // 新的排前面
    docs.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }

  async function refreshTrash() {
    if (!workspaceId.value) return;
    trash.value = await listTrash(workspaceId.value);
  }

  async function createNew(): Promise<Doc> {
    const doc = await createDoc(workspaceId.value, "未命名笔记");
    await refreshList();
    return doc;
  }

  async function remove(id: string) {
    await deleteDoc(id); // 软删 → 进回收站
    await Promise.all([refreshList(), refreshTrash()]);
  }

  async function restore(id: string) {
    await restoreDoc(id);
    await Promise.all([refreshList(), refreshTrash()]);
  }

  async function purge(id: string) {
    // 回收站里的再删一次 = 物理删除（后端两级删除语义）
    await deleteDoc(id);
    await refreshTrash();
  }

  return {
    workspaceId, docs, trash, searchQuery, searching,
    bootstrap, refreshList, refreshTrash, createNew, remove, restore, purge,
  };
});
