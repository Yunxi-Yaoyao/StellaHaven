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

interface UserRead {
  id: string;
  username: string;
  display_name: string;
}

interface WorkspaceRead {
  id: string;
  name: string;
  user_id: string;
}

// ── 引导：默认用户 + 默认工作区（M2 阶段单用户，auth 后面补）──
const LS_KEY = "stella_bootstrap";

export async function ensureWorkspace(): Promise<string> {
  const cached = localStorage.getItem(LS_KEY);
  if (cached) return JSON.parse(cached).workspaceId as string;

  // 找或建默认用户
  const users = await api<UserRead[]>("/users/?limit=100");
  let user = users.find((u) => u.username === "yunxi");
  if (!user) {
    user = await api<UserRead>("/users/", {
      method: "POST",
      body: JSON.stringify({ username: "yunxi", display_name: "云曦" }),
    });
  }

  // 找或建默认工作区
  const wss = await api<WorkspaceRead[]>(`/workspaces/?user_id=${user.id}`);
  let ws = wss.find((w) => w.name === "云曦的笔记本");
  if (!ws) {
    ws = await api<WorkspaceRead>("/workspaces/", {
      method: "POST",
      body: JSON.stringify({ user_id: user.id, name: "云曦的笔记本" }),
    });
  }

  localStorage.setItem(LS_KEY, JSON.stringify({ workspaceId: ws.id }));
  return ws.id;
}

// ── 文档接口 ──
export const listDocs = (wsId: string) =>
  api<Doc[]>(`/documents/?workspace_id=${wsId}&limit=200`);

export const searchDocs = (wsId: string, q: string) =>
  api<Doc[]>(`/documents/search?q=${encodeURIComponent(q)}&workspace_id=${wsId}`);

export const getDoc = (id: string) => api<Doc>(`/documents/${id}`);

export const createDoc = (wsId: string, title: string) =>
  api<Doc>("/documents/", {
    method: "POST",
    body: JSON.stringify({
      title,
      file_path: `/notes/${Date.now()}.md`,
      workspace_id: wsId,
      content: "",
    }),
  });

export const updateDoc = (id: string, updatedAt: string, fields: { title?: string; content?: string }) =>
  api<Doc>(`/documents/${id}`, {
    method: "PUT",
    body: JSON.stringify({ updated_at: updatedAt, ...fields }),
  });

export const deleteDoc = (id: string) =>
  api<void>(`/documents/${id}`, { method: "DELETE" });

export const restoreDoc = (id: string) =>
  api<Doc>(`/documents/${id}/restore`, { method: "POST" });

export const listTrash = (wsId: string) =>
  api<Doc[]>(`/documents/trash?workspace_id=${wsId}`);

export const getDraft = (id: string) => api<Draft>(`/documents/${id}/draft`);

export const toggleFavorite = (id: string) =>
  api<Doc>(`/documents/${id}/favorite`, { method: "POST" });
