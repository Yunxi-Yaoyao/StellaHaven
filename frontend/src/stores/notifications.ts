// 全局通知 store：未读数 + 下拉列表 + WS 实时推送（断线 30s 轮询兜底）
import { reactive, readonly } from "vue";
import { listNotifications, markAllRead, markRead, unreadCount } from "../api/alerts";
import type { NotificationItem } from "../api/alerts";
import { loggedIn } from "../modules/home/auth";

interface NotifyState {
  unread: number;
  items: NotificationItem[];
  loaded: boolean;
}

const state = reactive<NotifyState>({ unread: 0, items: [], loaded: false });

let ws: WebSocket | null = null;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let started = false;

async function refreshCount() {
  if (!loggedIn.value) return;
  try {
    state.unread = (await unreadCount()).count;
  } catch { /* 网络抖动不打扰 */ }
}

async function refreshList() {
  if (!loggedIn.value) return;
  try {
    state.items = await listNotifications(50);
    state.unread = state.items.filter((n) => !n.read).length;
    state.loaded = true;
  } catch { /* 同上 */ }
}

function connectWs() {
  if (ws && ws.readyState <= WebSocket.OPEN) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/notifications`);
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg?.type === "notification") {
        state.unread += 1;
        state.items = state.loaded
          ? [{ id: msg.id, rule_id: null, title: msg.title, body: msg.body,
              severity: msg.severity, kind: msg.kind, link: msg.link,
              read: false, ts: msg.ts }, ...state.items].slice(0, 50)
          : state.items;
      }
    } catch { /* 非本频道消息 */ }
  };
  ws.onclose = () => { ws = null; setTimeout(connectWs, 5000); };  // 自动重连
}

export function startNotifications() {
  if (started) return;
  started = true;
  void refreshCount();
  connectWs();
  pollTimer = setInterval(refreshCount, 30000);   // WS 之外的兜底
}

export function stopNotifications() {
  started = false;
  clearInterval(pollTimer);
  ws?.close();
  ws = null;
  state.unread = 0;
  state.items = [];
  state.loaded = false;
}

async function readOne(id: number) {
  await markRead(id);
  const item = state.items.find((n) => n.id === id);
  if (item && !item.read) { item.read = true; state.unread = Math.max(0, state.unread - 1); }
}

async function readAll() {
  await markAllRead();
  state.items.forEach((n) => { n.read = true; });
  state.unread = 0;
}

export const notifications = readonly(state);
export const notificationActions = { refreshList, readOne, readAll };
