// 任务记录共享格式化 helper：打流/MTR/命令 历史行与记录页共用。
import type { IperfTask } from "../../api/servers";

// 时间戳：今天内 HH:mm，跨天 MM-DD HH:mm
export function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`;
  if (d.toDateString() === now.toDateString()) return hm;
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}`;
}

export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "-";
  if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b >= 1e3) return (b / 1e3).toFixed(1) + " KB";
  return b.toFixed(0) + " B";
}

export function fmtBandwidth(t: IperfTask): string {
  const r = t.result_json as any;
  if (t.status !== "done") return "-";
  // 优先摘要列（后端 done 时落列；iperf=接收均值，speedtest=下载），老数据回退解析 result_json
  if (t.avg_mbps != null) return t.avg_mbps.toFixed(1) + " Mbps";
  if (!r) return "-";
  if (r.suspicious) return "数据异常";
  if (t.mode === "speedtest") {
    const srv = r?.servers?.[0] || {};
    const dl = srv.dl_speed != null ? srv.dl_speed : (r?.download?.bandwidth ?? null);
    return dl != null ? (dl * 8 / 1e6).toFixed(1) + " Mbps" : "-";
  }
  if (r?.avg_bitrate != null) {
    return (r.avg_bitrate / 1e6).toFixed(1) + " Mbps";
  }
  const bps = r?.end?.sum_received?.bits_per_second || r?.end?.sum_sent?.bits_per_second || r?.sum_sent?.bits_per_second;
  if (!bps) return "-";
  return (bps / 1e6).toFixed(1) + " Mbps";
}

export function fmtParams(t: IperfTask): string {
  const parts: string[] = [];
  parts.push(t.udp ? "UDP" : "TCP");
  if (t.bytes) parts.push(`数据量 ${t.bytes}`);
  else parts.push(`${t.duration}s`);
  if (t.parallel > 1) parts.push(`${t.parallel}流`);
  if (t.direction === "reverse") parts.push("反向");
  if (t.udp && t.bitrate) parts.push(`@${t.bitrate}`);
  return parts.join(" · ");
}

// 打流结果指标卡片（speedtest-go / ookla 双格式兼容）
export function resultMetrics(t: IperfTask): { label: string; value: string }[] {
  const r = t.result_json as any;
  if (!r || t.status !== "done") return [];
  if (r.suspicious) return [{ label: "提示", value: "数据异常（iperf3 统计虚高，请重测）" }];
  if (t.mode === "speedtest") {
    const srv = r?.servers?.[0] || {};
    let dl: number | null = srv.dl_speed ?? null;
    let ul: number | null = srv.ul_speed ?? null;
    let lat: number | null = srv.latency ?? null;
    let jit: number | null = srv.jitter ?? null;
    let name: string = srv.name || "";
    let country: string = srv.country || "";
    // speedtest-go：server 条目里 latency/jitter 是纳秒（Go time.Duration 序列化），有 dl_speed 即为该格式
    if (srv.dl_speed != null) {
      if (lat != null) lat = lat / 1e6;
      if (jit != null) jit = jit / 1e6;
    }
    if (dl == null && r?.download?.bandwidth != null) dl = r.download.bandwidth as number;
    if (ul == null && r?.upload?.bandwidth != null) ul = r.upload.bandwidth as number;
    if (lat == null && r?.ping?.latency != null) lat = r.ping.latency as number;  // ookla/librespeed：ms
    if (jit == null && r?.ping?.jitter != null) jit = r.ping.jitter as number;    // ookla/librespeed：ms
    if (!name && r?.server?.name) { name = r.server.name as string; country = (r.server.country as string) || ""; }
    const m: { label: string; value: string }[] = [];
    if (dl != null) m.push({ label: "下载", value: (dl * 8 / 1e6).toFixed(1) + " Mbps" });
    if (ul != null) m.push({ label: "上传", value: (ul * 8 / 1e6).toFixed(1) + " Mbps" });
    if (lat != null) m.push({ label: "延迟", value: lat.toFixed(1) + " ms" });
    if (jit != null) m.push({ label: "抖动", value: jit.toFixed(2) + " ms" });
    if (name) m.push({ label: "服务器", value: `${name}${country ? " · " + country : ""}` });
    return m;
  }
  const m: { label: string; value: string }[] = [];
  const isBytes = !!t.bytes;
  if (isBytes && r.total_bytes != null) m.push({ label: "数据量", value: fmtBytes(r.total_bytes) });
  if (r.avg_bitrate != null) m.push({ label: "接收速率", value: (r.avg_bitrate / 1e6).toFixed(1) + " Mbps" });
  if (r.send_avg_bitrate != null) m.push({ label: "发送速率", value: (r.send_avg_bitrate / 1e6).toFixed(1) + " Mbps" });
  if (r.peak_bitrate != null) m.push({ label: "峰值速率", value: (r.peak_bitrate / 1e6).toFixed(1) + " Mbps" });
  if (!isBytes && r.total_bytes != null) m.push({ label: "总数据量", value: fmtBytes(r.total_bytes) });
  if (r.lost_pct != null) m.push({ label: "丢包率", value: r.lost_pct + "%" });
  if (r.jitter_ms != null) m.push({ label: "抖动", value: (r.jitter_ms as number).toFixed(2) + " ms" });
  return m;
}

export const TASK_STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: "排队中", cls: "st-pending" },
  running: { label: "进行中", cls: "st-running" },
  done: { label: "完成", cls: "st-done" },
  failed: { label: "失败", cls: "st-failed" },
  cancelled: { label: "已中止", cls: "st-cancelled" },
};
