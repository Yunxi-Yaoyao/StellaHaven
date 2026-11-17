// 告警与通知 API
import { api } from "./client";

export interface AlertRule {
  id: number;
  kind: "node_offline" | "monitor_down" | "wg_link";
  target: string;
  label: string;
  link: string;
  severity: "warning" | "critical";
  debounce: number;
  repeat_minutes: number;
  email: boolean;
  enabled: boolean;
  created_at: string;
  state: "ok" | "firing";
  last_change_at: string | null;
  message: string | null;
  wg_manual?: {node_id:number;interface:string;target:string} | null;
  wg_observation?: {health:"ok"|"degraded"|"failed"|"unknown";reason:string|null;checked_at:string|null};
}

export interface NotificationItem {
  id: number;
  rule_id: number | null;
  title: string;
  body: string;
  severity: string;
  kind: string;
  context?: {incident_id?: number | null; event?: string; node_id?: number | null; label?: string; source?: string; outcome?: string} | null;
  link: string | null;
  read: boolean;
  ts: string;
}

export const KIND_LABELS: Record<AlertRule["kind"], string> = {
  node_offline: "节点上报中断",
  monitor_down: "监控项异常",
  wg_link: "WG 链路中断",
};

export interface Incident {
  id: number; rule_id: number; label: string; kind: string; severity: string;
  node_id: number | null; message: string; started_at: string | null; resolved_at: string | null;
  duration_seconds: number | null; status: 'unresolved' | 'resolved' | 'incomplete';
  metadata_source: 'snapshot' | 'legacy_rule'; start_missing: boolean; recovery_unconfirmed: boolean;
  evaluated_at: string | null; watermark: string | null; enabled: boolean; archived: boolean;
  observation: 'recent' | 'unknown';
}
export interface IncidentPage {items: Incident[]; total: number; limit: number; offset: number; untracked?:{rule_id:number;label:string;message:string}[]}
export interface IncidentDetail extends Incident {
  timeline: {id:number;event:string;ts:string;message:string}[];
  notifications: NotificationItem[];
}
export interface NotificationDetail extends NotificationItem {
  entities: {type:'node';id:number;label:string;available:boolean}[];
}
export const getNotification = (id:number,signal?:AbortSignal) => api<NotificationDetail>(`/notifications/${id}`,{signal});
export const getIncident = (id:number,signal?:AbortSignal) => api<IncidentDetail>(`/alerts/incidents/${id}`,{signal});
export const listIncidents = (query:URLSearchParams,signal?:AbortSignal) => api<IncidentPage>(`/alerts/incidents?${query}`,{signal});
export function fullTime(ts:string|null){return ts?new Date(ts).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'medium'}):'未知';}
export function duration(seconds:number|null){
  if(seconds===null)return '未知（记录不完整）';
  const m=Math.floor(seconds/60),h=Math.floor(m/60),d=Math.floor(h/24);
  return d?`${d}天 ${h%24}小时`:h?`${h}小时 ${m%60}分钟`:m?`${m}分钟`:`${seconds}秒`;
}
export const incidentStatus = (i:Incident) => i.status==='resolved'?'已恢复':i.status==='incomplete'?'记录不完整':i.archived?'已归档 · 未确认恢复':'未恢复';

export const listRules = () => api<AlertRule[]>("/alerts/rules");
export const createRule = (data: Partial<AlertRule> & { kind: string; target: string }) =>
  api<{ id: number }>("/alerts/rules", { method: "POST", body: JSON.stringify(data) });
export const patchRule = (id: number, data: Partial<AlertRule>) =>
  api<{ ok: boolean }>(`/alerts/rules/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const deleteRule = (id: number) =>
  api<{ ok: boolean }>(`/alerts/rules/${id}`, { method: "DELETE" });

export const listNotifications = (limit = 50) =>
  api<NotificationItem[]>(`/notifications?limit=${limit}`);
export const unreadCount = () => api<{ count: number }>("/notifications/unread-count");
export const markRead = (id: number) =>
  api<{ ok: boolean }>(`/notifications/${id}/read`, { method: "POST" });
export const markAllRead = () =>
  api<{ ok: boolean; marked: number }>("/notifications/read-all", { method: "POST" });
