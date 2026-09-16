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
}

export interface NotificationItem {
  id: number;
  rule_id: number | null;
  title: string;
  body: string;
  severity: string;
  kind: "alert" | "alert_resolved";
  link: string | null;
  read: boolean;
  ts: string;
}

export const KIND_LABELS: Record<AlertRule["kind"], string> = {
  node_offline: "节点离线",
  monitor_down: "监控项异常",
  wg_link: "WG 链路中断",
};

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
