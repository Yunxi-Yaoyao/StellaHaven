import { api, ApiError } from "./client";
import { auth, refreshAccess } from '../modules/home/auth';

// Notes deletions use owner authorization only. Never invoke the global admin
// elevation handler, even when talking to a pre-migration server.
async function ownerDelete<T>(path: string, method = 'DELETE', admitted: () => boolean = () => true): Promise<T> {
  const owner = auth.me?.id, generation = auth.sessionGeneration, epoch = auth.requestEpoch;
  const check = () => { if (!admitted() || auth.suspended || auth.sessionClosing || owner !== auth.me?.id || generation !== auth.sessionGeneration || epoch !== auth.requestEpoch) throw new DOMException('会话已改变', 'AbortError'); };
  check();
  let response = await fetch(path, {method, credentials:'same-origin'});
  if (response.status === 401 && await refreshAccess()) { check(); response = await fetch(path, {method, credentials:'same-origin'}); }
  check();
  if (!response.ok) throw new ApiError(response.status, await response.json().then(body => body.detail).catch(() => null));
  if (response.status === 204) return undefined as T;
  const value = await response.json(); check(); return value;
}

export interface NotesPreferenceFields {
  delete_action: 'trash' | 'permanent'; ask_before_delete: boolean;
  font_size?: number; line_height?: number; read_width?: number;
  code_line_numbers?: boolean; code_wrap?: boolean;
  directory_sort?: 'updated' | 'title' | 'created'; hidden_folders?: string[];
}
export interface NotesPreferences extends NotesPreferenceFields { revision: number }
export const getNotesPreferences = () => api<NotesPreferences>('/notes-preferences');
export const patchNotesPreferences = (fields: Partial<NotesPreferenceFields> & {expected_revision: number}) =>
  api<NotesPreferences>('/notes-preferences', {method:'PATCH', body:JSON.stringify(fields)});

export interface TemplateCatalog {
  root_id: string | null;
  items: {id: string; parent_id: string | null; title: string; is_folder: boolean}[];
  recent_ids: string[];
}
export const listTemplates = (workspace: string, initialize = false) => api<TemplateCatalog>(`/notes-tools/templates/${workspace}${initialize ? '/initialize' : ''}`, initialize ? {method:'POST'} : undefined);
export const saveAsTemplate = (workspace:string, source:string) => api<Doc>(`/notes-tools/templates/${workspace}/copy/${source}`, {method:'POST'});
export const createFromTemplate = (workspace: string, template_id: string, parent_id: string | null, title: string) => api<Doc>(`/notes-tools/templates/${workspace}/create`, {method:'POST',body:JSON.stringify({template_id,parent_id,title})});

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
  // Display only; never send this field as a CAS token.
  updated_at_display?: string | null;
  // 草稿元信息
  draft_updated_at: string | null;
  draft_device: string | null;
  has_draft: boolean;
}

export interface ConsumedDraft {
  draft_updated_at: string;
  content_hash: string;
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

export const deleteWorkspace = (id: string, force = false, admitted?: () => boolean) =>
  api<void>(`/workspaces/${id}?force=${force}`, { method: "DELETE" }, admitted);

// ── 文档接口 ──
// 分页拉全量：目录树/缓存都需要完整列表，单一 limit 上限会在文档增长后截断
// （8.26 事故：limit=200 × 299 篇 → v3 文件夹整支不渲染）。后端已排序保证翻页稳定。
export const listDocs = async (wsId: string) => {
  const PAGE = 500;
  const all: Doc[] = [];
  for (let skip = 0; ; skip += PAGE) {
    const page = await api<Doc[]>(`/documents/?workspace_id=${wsId}&skip=${skip}&limit=${PAGE}`);
    all.push(...page);
    if (page.length < PAGE) break;
  }
  return all;
};

export const searchDocs = (wsId: string, q: string) =>
  api<Doc[]>(`/documents/search?q=${encodeURIComponent(q)}&workspace_id=${wsId}`);

export const getDoc = (id: string) => api<Doc>(`/documents/${id}`);

export const createDoc = (wsId: string, title: string, parentId?: string, content = "") =>
  api<Doc>("/documents/", {
    method: "POST",
    body: JSON.stringify({
      title,
      file_path: `/notes/${Date.now()}.md`,
      workspace_id: wsId,
      content,
      parent_id: parentId ?? null,
    }),
  });

export const updateDoc = (id: string, updatedAt: string, fields: { title?: string; content?: string; parent_id?: string | null; consumed_draft?: ConsumedDraft }) => {
  const {consumed_draft, ...values} = fields;
  return api<Doc>(`/documents/${id}`, {
    method: "PUT",
    body: JSON.stringify({ updated_at: updatedAt, ...values, ...(typeof values.content === 'string' && consumed_draft ? {consumed_draft} : {}) }),
  });
};

export interface DeletePreviewRequest {
  workspace_id: string; doc_id?: string; mode: 'trash'|'permanent'|'empty-trash'; cascade: boolean;
}
export interface DeletePreview extends Omit<DeletePreviewRequest, 'doc_id'> {
  doc_id?: string | null;
  scope_token: string; target_ids: string[]; descendant_count: number;
}
export const previewDelete = (request: DeletePreviewRequest) =>
  api<DeletePreview>('/documents/delete-preview', {method:'POST', body:JSON.stringify(request)});
const scopeQuery = (token?: string) => token ? `&scope_token=${encodeURIComponent(token)}` : '';
export const deleteDoc = (id: string, cascade = true, scopeToken?: string, admitted?: () => boolean) =>
  ownerDelete<void>(`/documents/${id}?cascade=${cascade}${scopeQuery(scopeToken)}`, 'DELETE', admitted);

// Existing delete contract is HTTP 204; permanent deletion keeps that shape.
export const permanentDeleteDoc = (id: string, cascade = false, scopeToken?: string, admitted?: () => boolean) =>
  ownerDelete<void>(`/documents/${id}/permanent?cascade=${cascade}${scopeQuery(scopeToken)}`, 'DELETE', admitted);

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

export const emptyTrash = (wsId: string, scopeToken?: string) =>
  ownerDelete<{ purged: number }>(`/documents/trash/empty?workspace_id=${wsId}${scopeQuery(scopeToken)}`, 'POST');

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

export const listAllLinks = (workspaceId: string) =>
  api<{ source_id: string; target_id: string; link_type: string }[]>(`/document-links/?workspace_id=${encodeURIComponent(workspaceId)}`);

export interface SearchItem {kind:string;id:string;label:string;path:string;ts?:string;state?:string;node_id?:number}
export const unifiedSearch = (q:string, workspaceId?:string, signal?:AbortSignal) => api<{items:SearchItem[]}>(`/search?q=${encodeURIComponent(q)}${workspaceId?`&workspace_id=${encodeURIComponent(workspaceId)}`:''}`,{signal});
export const captureNote = (workspaceId:string,title:string,content:string,signal?:AbortSignal) => api<Doc>('/notes-tools/quick-record',{method:'POST',body:JSON.stringify({workspace_id:workspaceId,title,content}),signal});
export const readNoteNode = (id:string,signal?:AbortSignal) => api<{node_id:number|null}>(`/notes-tools/documents/${id}/node`,{signal});
export const setNoteNode = (id:string,nodeId:number|null,signal?:AbortSignal) => api<{node_id:number|null}>(`/notes-tools/documents/${id}/node`,{method:'PUT',body:JSON.stringify({node_id:nodeId}),signal});
export const nodeTimeline = (nodeId:number,workspaceId?:string,signal?:AbortSignal) => api<{items:SearchItem[];has_more:boolean;unknown_notes_present?:boolean;history_path?:string|null}>(`/timeline?node_id=${nodeId}${workspaceId?`&workspace_id=${encodeURIComponent(workspaceId)}`:''}`,{signal});

export interface NoteVersion { id: string; doc_id: string; version_no: number; created_at: string }
export const listVersions = (docId: string, signal?: AbortSignal) => api<NoteVersion[]>(`/document-versions/?doc_id=${encodeURIComponent(docId)}`, {signal});
export const versionDiff = (id: string, signal?: AbortSignal) => api<{diff:string}>(`/document-versions/${id}/diff`, {signal});
export const restoreVersion = (id: string, updatedAt: string, signal?: AbortSignal) => api<Doc>(`/document-versions/${id}/restore`, {method:'POST',body:JSON.stringify({updated_at:updatedAt}),signal});
