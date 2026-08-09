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

// ── 公网 IP + 地区：问外部 IP 服务，缓存 24h（家宽重播 IP 会变）──
interface IpInfo {
  ip: string;
  region: string;
  at: number; // 缓存时间戳
}

const IP_CACHE_KEY = "stella_ipinfo";
const IP_CACHE_TTL = 24 * 3600 * 1000;

export async function getIpInfo(): Promise<IpInfo | null> {
  try {
    const cached = JSON.parse(localStorage.getItem(IP_CACHE_KEY) || "null") as IpInfo | null;
    if (cached && Date.now() - cached.at < IP_CACHE_TTL) return cached;
  } catch {
    /* 缓存坏了就重查 */
  }

  // 主：ipinfo.io；备：api.ip.sb
  for (const url of ["https://ipinfo.io/json", "https://api.ip.sb/geoip"]) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(4000) });
      const d = await resp.json();
      // region == city 时去重（直辖市常见：Shanghai Shanghai → Shanghai）
      const region = d.region === d.city
        ? d.region
        : [d.region, d.city].filter(Boolean).join(" ") || d.country || "";
      if (d.ip) {
        const info: IpInfo = { ip: d.ip, region, at: Date.now() };
        localStorage.setItem(IP_CACHE_KEY, JSON.stringify(info));
        return info;
      }
    } catch {
      /* 换下一个源 */
    }
  }
  return null; // 都挂了就只显示设备名
}

/**
 * 草稿上行管道 composable：
 * - 打开文档时连 WS，切换/关闭时断开
 * - device 由调用方组合（设备名 · 公网IP · 地区）
 * - sendDraft() 由调用方 debounce 后调用
 * - 收到 doc_saved（别的设备保存了）→ 回调
 * - 断线 3 秒自动重连
 */
export function useDraftSocket(
  docId: Ref<string | null>,
  device: Ref<string>,
  onDocSaved: () => void,
) {
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function connect(id: string) {
    disconnect();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/${id}?device=${encodeURIComponent(device.value)}`);
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
