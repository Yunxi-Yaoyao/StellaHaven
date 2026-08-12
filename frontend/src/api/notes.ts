import { api } from "./client";

// ── 类型：对齐后端 DocumentRead ──
export interface Doc {
  id: string;
  title: string;
  file_path: string;
  workspace_id: string;
  parent_id: string | null;
  content: string | null;
  content_hash: string;
  status: string;
  is_folder: boolean;
  is_pinned: boolean;
  is_favorite: boolean;
  created_at: string;
  updated_at: string;
  // 草稿元信息
  draft_updated_at: string | null;
  draft_device: string | null;
  has_draft: boolean;
}

export interface Draft {
  content: string;
  updated_at: string;
  device: string | null;
}

interface WorkspaceRead {
  id: string;
  name: string;
  user_id: string;
}

// ── 引导：默认用户 + 默认工作区（M2 阶段单用户，auth 后面补）──
const LS_KEY = "stella_bootstrap";

export interface Bootstrap {
  userId: string;
  workspaceId: string;
}

export async function ensureUser(): Promise<string> {
  // 认证时代：用户身份只认 /auth/me（不再从用户列表里翻 yunxi）
  const cached = localStorage.getItem(LS_KEY);
  if (cached) {
    try {
      const id = JSON.parse(cached).userId;
      if (id) return id as string;
    } catch {
      /* 缓存坏了往下走 */
    }
  }
  const r = await fetch("/auth/me");
  if (!r.ok) throw new Error("未登录");
  const me = await r.json();
  return me.id as string;
}

export async function ensureWorkspace(): Promise<Bootstrap> {
  const cached = localStorage.getItem(LS_KEY);
  if (cached) {
    const b = JSON.parse(cached);
    if (b.userId && b.workspaceId) {
      // 缓存的工作区可能已不属于当前账号（数据隔离时代）——先验归属，不对就重建
      const chk = await fetch(`/workspaces/${b.workspaceId}`);
      if (chk.ok) return b;
      localStorage.removeItem(LS_KEY);
    }
  }

  const userId = await ensureUser();
  // 数据隔离后：/workspaces/ 只返回当前用户自己的区（user_id 参数已被后端忽略）
  const wss = await api<WorkspaceRead[]>(`/workspaces/?limit=100`);
  let ws = wss.find((w) => w.name === "云曦的笔记本") ?? wss[0];
  if (!ws) {
    ws = await api<WorkspaceRead>("/workspaces/", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, name: "云曦的笔记本" }),
    });
  }

  const b: Bootstrap = { userId, workspaceId: ws.id };
  localStorage.setItem(LS_KEY, JSON.stringify(b));
  return b;
}

export function saveBootstrap(b: Bootstrap) {
  localStorage.setItem(LS_KEY, JSON.stringify(b));
}

// ── 工作区管理 ──
export const listWorkspaces = (userId: string) =>
  api<WorkspaceRead[]>(`/workspaces/?user_id=${userId}&limit=100`);

export const createWorkspace = (userId: string, name: string) =>
  api<WorkspaceRead>("/workspaces/", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, name }),
  });

export const renameWorkspace = (id: string, name: string) =>
  api<WorkspaceRead>(`/workspaces/${id}?name=${encodeURIComponent(name)}`, { method: "PUT" });

export const deleteWorkspace = (id: string, force = false) =>
  api<void>(`/workspaces/${id}?force=${force}`, { method: "DELETE" });

// ── 文档接口 ──
export const listDocs = (wsId: string) =>
  api<Doc[]>(`/documents/?workspace_id=${wsId}&limit=200`);

export const searchDocs = (wsId: string, q: string) =>
  api<Doc[]>(`/documents/search?q=${encodeURIComponent(q)}&workspace_id=${wsId}`);

export const getDoc = (id: string) => api<Doc>(`/documents/${id}`);

export const createDoc = (wsId: string, title: string, parentId?: string) =>
  api<Doc>("/documents/", {
    method: "POST",
    body: JSON.stringify({
      title,
      file_path: `/notes/${Date.now()}.md`,
      workspace_id: wsId,
      content: "",
      parent_id: parentId ?? null,
    }),
  });

export const updateDoc = (id: string, updatedAt: string, fields: { title?: string; content?: string; parent_id?: string | null }) =>
  api<Doc>(`/documents/${id}`, {
    method: "PUT",
    body: JSON.stringify({ updated_at: updatedAt, ...fields }),
  });

export const deleteDoc = (id: string, cascade = true) =>
  api<void>(`/documents/${id}?cascade=${cascade}`, { method: "DELETE" });

export interface RestoreResult {
  doc: Doc;
  reattached: boolean; // 父页面不在，已挂回根级
  restored: number;    // 一共还原了几篇（级联）
}

export const restoreDoc = (id: string, cascade = false) =>
  api<RestoreResult>(`/documents/${id}/restore?cascade=${cascade}`, { method: "POST" });

export const listTrash = (wsId: string) =>
  api<Doc[]>(`/documents/trash?workspace_id=${wsId}`);

export const listRecent = (wsId: string) =>
  api<Doc[]>(`/documents/recent?workspace_id=${wsId}`);

export const emptyTrash = (wsId: string) =>
  api<{ purged: number }>(`/documents/trash/empty?workspace_id=${wsId}`, { method: "POST" });

export const clearAllDocs = (wsId: string) =>
  api<{ trashed: number }>(`/documents/clear-all?workspace_id=${wsId}`, { method: "POST" });

export const getDraft = (id: string) => api<Draft>(`/documents/${id}/draft`);

export const toggleFavorite = (id: string) =>
  api<Doc>(`/documents/${id}/favorite`, { method: "POST" });

// ── 标签 ──
export interface Tag {
  id: string;
  name: string;
  color: string | null;
}
export interface DocTag {
  doc_id: string;
  tag_id: string;
}

export const listTags = () => api<Tag[]>("/tags/?limit=200");
export const createTag = (name: string, color?: string) =>
  api<Tag>("/tags/", { method: "POST", body: JSON.stringify({ name, color }) });
export const listAllDocTags = () => api<DocTag[]>("/doc-tags/");
export const getDocTags = (docId: string) => api<DocTag[]>(`/doc-tags/?doc_id=${docId}`);
export const addDocTag = (docId: string, tagId: string) =>
  api<DocTag>("/doc-tags/", { method: "POST", body: JSON.stringify({ doc_id: docId, tag_id: tagId }) });
export const removeDocTag = (docId: string, tagId: string) =>
  api<void>(`/doc-tags/?doc_id=${docId}&tag_id=${tagId}`, { method: "DELETE" });

export const listAllLinks = () =>
  api<{ source_id: string; target_id: string; link_type: string }[]>("/document-links/");
