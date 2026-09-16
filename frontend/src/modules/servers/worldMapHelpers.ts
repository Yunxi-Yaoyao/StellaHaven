import type { MapNode, MapLink, MapLocationInput, MapLinkHealth } from '../../api/serverMap';

export const healthLabels: Record<MapLinkHealth, string> = { ok: 'ICMP探测成功', degraded: 'ICMP探测丢包', failed: 'ICMP探测未响应', unknown: '未探测 / 探测未知' };
export const healthColors: Record<MapLinkHealth, string> = { ok: '#45c9b0', degraded: '#efa653', failed: '#ed6876', unknown: '#768091' };
export function linkHealth(link: MapLink): MapLinkHealth {
  return link.observations?.some(o => o.probe) ? link.health ?? 'unknown' : 'unknown';
}
export interface NodePair {
  id: string; source: number; target: number; links: MapLink[]; health: MapLinkHealth;
  coords?: [number, number][]; display_reason?: string;
}
/** Canonical node pairs; tunnel IDs are backend-deduplicated interface pairs. */
export function aggregateNodePairs(links: MapLink[], groups: MapNodeGroup[]) {
  const byNode = new Map(groups.flatMap(g => g.nodes.map(n => [n.id, g] as const)));
  const pairsById = new Map<string, NodePair>();
  const unmatched: MapLink[] = [];
  const seen = new Set<string>();
  const rank: Record<MapLinkHealth, number> = { ok: 0, unknown: 1, degraded: 2, failed: 3 };
  for (const link of links) {
    if (seen.has(link.id)) continue;
    seen.add(link.id);
    if (link.target === null || link.source === link.target) { unmatched.push(link); continue; }
    const [source, target] = [link.source, link.target].sort((a, b) => a - b);
    const id = `${source}:${target}`;
    let pair = pairsById.get(id);
    if (!pair) {
      pair = { id, source, target, links: [], health: 'ok' };
      const a = byNode.get(source), b = byNode.get(target);
      if (!a || !b) pair.display_reason = '端点位置未知';
      else if (a.id === b.id) pair.display_reason = '同城 / 同坐标，见链路详情';
      else pair.coords = [a.coordinate, b.coordinate];
      pairsById.set(id, pair);
    }
    pair.links.push(link);
    const health = linkHealth(link);
    if (rank[health] > rank[pair.health]) pair.health = health;
  }
  const pairs = [...pairsById.values()].sort((a, b) => a.source - b.source || a.target - b.target);
  return { pairs, unmatched, drawable: pairs.filter(p => p.coords), unplaced: pairs.filter(p => !p.coords),
    stats: { nodePairs: pairs.length, tunnels: pairs.reduce((sum, p) => sum + p.links.length, 0), unmatched: unmatched.length } };
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));
}
export function parseLocationInput(latitude: string | number, longitude: string | number, label: string): MapLocationInput {
  // Vue number inputs emit numbers for valid values and an empty string when cleared.
  const input = { latitude: Number(latitude), longitude: Number(longitude), label: label.trim() || null };
  if (!String(latitude).trim() || !String(longitude).trim() || !hasCoordinates(input)) throw new Error('经纬度须成对填写：纬度 -90～90，经度 -180～180');
  return input;
}
export function mapReasonLabel(reason: string | null | undefined): string {
  if (!reason) return '';
  const labels: Record<string, string> = {
    no_snapshot: '尚未收到位置采集报告',
    icmp_packet_loss: 'ICMP 探测观察到丢包',
    icmp_no_response: '本轮 ICMP 探测没有回复',
    missing_or_expired_direction: '有方向尚未上报或探测已过期',
    missing_or_expired_probe: '探测未上报或已过期',
    ping_unavailable: '未安装 ping 或无法执行',
    ping_failed_or_unparseable: '探测执行或结果解析失败',
    probe_budget_exhausted: '本轮探测时间预算耗尽',
    internal_requires_manual_location: '内网节点需要人工设置城市位置',
    manual_ip_requires_location: '手工填写的 IP 需要人工设置城市位置',
    nat_location_unavailable: '暂时无法获取公网出口位置',
    physical_interface_unverified: '无法确认物理出口网卡',
    binding_unavailable: '物理出口绑定不可用',
    bound_geo_request_failed: '通过物理出口查询位置失败',
    binding_source_mismatch: '位置查询的来源地址与物理出口不符',
    ambiguous_peer_key: '多个节点匹配此对端，无法确定连接目标',
    unmatched_peer: '对端尚未匹配到已登记节点',
    self_peer: '对端指向本节点，未绘制连接',
    offline_or_expired_report: '节点离线或采集报告已过期',
    future_handshake: '握手时间异常，请检查节点时钟',
  };
  return labels[reason] ?? '原因未知';
}

export function projectMapLinks(links: MapLink[], groups: MapNodeGroup[]) {
  const byNode = new Map(groups.flatMap(g => g.nodes.map(n => [n.id, g] as const)));
  const drawable: (MapLink & { coords: [number, number][] })[] = [];
  const unplaced: (MapLink & { display_reason: string })[] = [];
  for (const link of links) {
    const source = byNode.get(link.source);
    const target = link.target === null ? undefined : byNode.get(link.target);
    if (!source || !target) unplaced.push({ ...link, display_reason: link.target === null ? '未识别对端，不推测位置' : '端点位置未知' });
    else if (source.id === target.id) unplaced.push({ ...link, display_reason: '同城 / 同坐标，见链路详情' });
    else drawable.push({ ...link, coords: [source.coordinate, target.coordinate] });
  }
  return { drawable, unplaced };
}

export interface MapNodeGroup { id: string; coordinate: [number, number]; nodes: MapNode[] }
export function hasCoordinates(node: Pick<MapNode, 'latitude' | 'longitude'>): boolean {
  return typeof node.latitude === 'number' && Number.isFinite(node.latitude) && Math.abs(node.latitude) <= 90
    && typeof node.longitude === 'number' && Number.isFinite(node.longitude) && Math.abs(node.longitude) <= 180;
}

/** Display one existing city-level coordinate, never jitter/average nodes to invent locations. */
export function groupMapNodes(nodes: MapNode[]): { groups: MapNodeGroup[]; unknown: MapNode[] } {
  const located = nodes.filter(hasCoordinates).sort((a, b) => a.id - b.id);
  const groups: MapNodeGroup[] = [];
  for (const node of located) {
    const matches = groups.filter(g => g.nodes.some(other =>
      (node.latitude === other.latitude && node.longitude === other.longitude)
      || (!!node.location_label?.trim() && node.location_label.trim().toLowerCase() === other.location_label?.trim().toLowerCase()
        // A label alone is not a globally unique city identifier; avoid merging names across countries.
        && Math.abs(node.latitude! - other.latitude!) <= 1 && Math.abs(node.longitude! - other.longitude!) <= 1)));
    if (!matches.length) groups.push({ id: String(node.id), coordinate: [node.longitude!, node.latitude!], nodes: [node] });
    else {
      const first = matches[0];
      first.nodes.push(node);
      for (const extra of matches.slice(1)) { first.nodes.push(...extra.nodes); groups.splice(groups.indexOf(extra), 1); }
      first.nodes.sort((a, b) => a.id - b.id);
    }
  }
  return { groups, unknown: nodes.filter(n => !hasCoordinates(n)) };
}
