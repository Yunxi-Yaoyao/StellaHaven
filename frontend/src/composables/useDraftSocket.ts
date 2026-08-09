import { watch, onUnmounted, type Ref } from "vue";

// 设备名：草稿槽要记录「哪台设备留下的」
export function getDeviceName(): string {
  let d = localStorage.getItem("stella_device");
  if (!d) {
    d = "设备-" + Math.random().toString(36).slice(2, 6);
    localStorage.setItem("stella_device", d);
  }
  return d;
}

export function setDeviceName(name: string) {
  localStorage.setItem("stella_device", name);
}

/**
 * 草稿上行管道 composable：
 * - 打开文档时连 WS，切换/关闭时断开
 * - sendDraft() 由调用方 debounce 后调用
 * - 收到 doc_saved（别的设备保存了）→ 回调
 * - 断线 3 秒自动重连
 */
export function useDraftSocket(
  docId: Ref<string | null>,
  onDocSaved: () => void,
) {
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function connect(id: string) {
    disconnect();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/${id}?device=${encodeURIComponent(getDeviceName())}`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "doc_saved") onDocSaved();
      } catch {
        /* 忽略坏消息 */
      }
    };
    ws.onclose = () => {
      // 文档还开着就重连
      if (docId.value === id) {
        reconnectTimer = setTimeout(() => connect(id), 3000);
      }
    };
  }

  function disconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    ws?.close();
    ws = null;
  }

  function sendDraft(content: string) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "draft", content }));
    }
  }

  watch(docId, (id) => {
    if (id) connect(id);
    else disconnect();
  }, { immediate: true });

  onUnmounted(disconnect);

  return { sendDraft };
}
