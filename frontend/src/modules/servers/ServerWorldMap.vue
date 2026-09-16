<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import * as echarts from 'echarts';
import Icon from '../../shell/Icon.vue';
import { isAdmin } from '../home/auth';
import { getMapTopology, updateMapLocation, type MapTopology, type MapNode, type MapLinkState } from '../../api/serverMap';
import { escapeHtml, groupMapNodes, aggregateNodePairs, healthColors, healthLabels, linkHealth, parseLocationInput, mapReasonLabel } from './worldMapHelpers';

const router = useRouter();
const storageKey = 'stella_server_world_map_collapsed';
const collapsed = ref(false);
try { collapsed.value = localStorage.getItem(storageKey) === '1'; } catch { /* storage may be unavailable */ }
const topology = ref<MapTopology | null>(null);
const loading = ref(false);
const error = ref('');
const mapError = ref('');
const chartEl = ref<HTMLElement | null>(null);
const selectedIds = ref<number[]>([]);
const selectedId = ref<number | null>(null);
const panel = ref<'nodes' | 'links'>('nodes');
const selectedNodes = computed(() => topology.value?.nodes.filter(n => selectedIds.value.includes(n.id)) ?? []);
const selectedNode = computed(() => topology.value?.nodes.find(n => n.id === selectedId.value));
const grouped = computed(() => groupMapNodes(topology.value?.nodes ?? []));
const projected = computed(() => aggregateNodePairs(topology.value?.links ?? [], grouped.value.groups));
const visibleLinks = computed(() => (topology.value?.links ?? []).filter(l => selectedId.value === null || l.source === selectedId.value || l.target === selectedId.value).sort((a,b) => Number(a.target === null) - Number(b.target === null)));
const stateLabels: Record<MapLinkState, string> = { recent: '近期握手', stale: '握手过期', never: '从未握手', unknown: '握手未知' };
const sourceLabels = { manual: '人工位置', nat: '公网出口推断', unknown: '位置未知' };
const statusLabels: Record<string, string> = { online: '在线', offline: '离线', pending: '待报到', removed: '已移除' };
let chart: echarts.ECharts | undefined;
let observer: ResizeObserver | undefined;
let timer: ReturnType<typeof setInterval> | undefined;
let controller: AbortController | undefined;
const assetController = new AbortController();
let disposed = false;
let mapReady = false;
let requestVersion = 0;

function timestamp(value: string | number | null | undefined): string {
  if (!value) return '暂无记录';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '暂无记录';
}
function bytes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '未知';
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GiB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${value} B`;
}
function locationSourceLabel(node: MapNode): string { return node.location_source === 'nat' && node.location_provider === 'ip2location' ? '公网出口 · IP2Location' : sourceLabels[node.location_source]; }
function nodeName(id: number | null): string { return id === null ? '未识别对端' : topology.value?.nodes.find(n => n.id === id)?.name ?? `#${id}`; }
function unplacedReason(id: string): string { return projected.value.unplaced.find(p => p.links.some(l => l.id === id))?.display_reason ?? (projected.value.unmatched.some(l => l.id === id) ? '未识别对端，不计入隧道' : ''); }
function selectNode(node: MapNode) { selectedId.value = node.id; selectedIds.value = [node.id]; panel.value = 'nodes'; }
function latestHandshake(node: MapNode): string {
  // Handshakes describe configured WG peers, never ICMP latency or inferred reachability.
  const times = (topology.value?.links ?? []).filter(l => l.source === node.id).map(l => l.latest_handshake_at ?? 0);
  return timestamp(times.length ? Math.max(...times) : null);
}
function tooltip(params: unknown): string {
  const data = (params as { data?: { groupId?: string; linkId?: string } }).data;
  if (data?.groupId) {
    const group = grouped.value.groups.find(g => g.id === data.groupId);
    return group?.nodes.map(n => `${escapeHtml(n.name)} · ${escapeHtml(statusLabels[n.status] ?? n.status)}<br/>${escapeHtml(n.location_label || '未命名位置')} · ${escapeHtml(locationSourceLabel(n))}<br/>WG 最近握手：${escapeHtml(latestHandshake(n))}`).join('<br/><br/>') ?? '';
  }
  const pair = projected.value.pairs.find(p => p.id === data?.linkId);
  return pair ? `${escapeHtml(nodeName(pair.source))} ↔ ${escapeHtml(nodeName(pair.target))}<br/>${escapeHtml(healthLabels[pair.health])} · ${pair.links.length} 条隧道<br/>` + pair.links.map(link => `${escapeHtml(link.source_interface)} ↔ ${escapeHtml(link.target_interface ?? link.peer_label)}：${escapeHtml(healthLabels[linkHealth(link)])}<br/>${escapeHtml(stateLabels[link.state])} · ${escapeHtml(timestamp(link.latest_handshake_at))}`).join('<br/><br/>') : '';
}
function render() {
  if (!mapReady || !chartEl.value || collapsed.value || disposed) return;
  if (!chart) {
    chart = echarts.init(chartEl.value);
    chart.setOption({
      backgroundColor: '#14171f', animation: false,
      tooltip: { trigger: 'item', confine: true, backgroundColor: '#202531', borderColor: '#384052', textStyle: { color: '#c9d4e8', fontSize: 11 }, formatter: tooltip },
      geo: { map: 'stella-world', nameProperty: 'NAME', roam: true, zoom: 1.08, center: [12, 15], scaleLimit: { min: 0.8, max: 12 },
        itemStyle: { areaColor: '#252b38', borderColor: '#3c4558', borderWidth: 0.5 },
        emphasis: { disabled: true }, select: { disabled: true }, label: { show: false } },
    });
    chart.on('click', params => {
      const data = params.data as { groupId?: string; linkId?: string } | undefined;
      if (data?.groupId) {
        const group = grouped.value.groups.find(g => g.id === data.groupId);
        selectedIds.value = group?.nodes.map(n => n.id) ?? [];
        selectedId.value = selectedIds.value.length === 1 ? selectedIds.value[0] : null;
        panel.value = 'nodes';
      } else if (data?.linkId) {
        const link = projected.value.pairs.find(l => l.id === data.linkId);
        selectedId.value = link?.source ?? null;
        panel.value = 'links';
      }
    });
  }
  const series: echarts.SeriesOption[] = (['ok', 'degraded', 'failed', 'unknown'] as const).map(health => ({
    id: `wg-${health}`, type: 'lines', coordinateSystem: 'geo', z: 2,
    lineStyle: { color: healthColors[health], width: 1.5, opacity: 0.75, curveness: 0.16, type: health === 'unknown' ? 'dashed' : 'solid' },
    effect: { show: false }, emphasis: { lineStyle: { width: 2, opacity: 0.9 } },
    data: projected.value.drawable.filter(l => l.health === health).map(l => ({ coords: l.coords!, linkId: l.id })),
  }));
  series.push({ id: 'nodes', type: 'scatter', coordinateSystem: 'geo', z: 3,
    label: { show: true, position: 'right', color: '#c9d4e8', fontSize: 10, formatter: (p: unknown) => {
      const data = (p as { data: { count: number } }).data; return data.count > 1 ? String(data.count) : '';
    } },
    data: grouped.value.groups.map(g => ({ groupId: g.id, name: g.nodes[0].location_label ?? g.nodes[0].name, value: g.coordinate, count: g.nodes.length,
      symbolSize: g.nodes.length > 1 ? 10 : 7, itemStyle: { color: g.nodes.some(n => n.status === 'online') ? '#ff9ec7' : '#768091', borderColor: '#14171f', borderWidth: 1.5 } })),
  });
  // Only replace series. Never clear/recreate geo on a poll: preserve user pan and zoom.
  chart.setOption({ series }, { replaceMerge: ['series'] });
}
async function refresh(force = false): Promise<boolean> {
  if (disposed || document.hidden || (!force && loading.value)) return false;
  const version = ++requestVersion;
  controller?.abort(); controller = new AbortController();
  loading.value = true;
  try {
    const data = await getMapTopology(controller.signal);
    if (disposed || version !== requestVersion) return false;
    topology.value = data; error.value = '';
    if (selectedId.value !== null && !data.nodes.some(n => n.id === selectedId.value)) selectedId.value = null;
    render(); return true;
  } catch (e) {
    if (!disposed && version === requestVersion && !(e instanceof DOMException && e.name === 'AbortError')) error.value = topology.value ? '更新失败，暂保留上次拓扑' : '暂时无法读取拓扑，稍后重试喵';
    return false;
  } finally { if (version === requestVersion) loading.value = false; }
}
async function loadMap() {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}maps/world.geo.json`, { signal: assetController.signal });
    if (!response.ok) throw new Error('map asset unavailable');
    const geo = await response.json();
    if (disposed) return;
    if (geo.type !== 'FeatureCollection' || !Array.isArray(geo.features)) throw new Error('invalid map');
    echarts.registerMap('stella-world', geo); mapReady = true; mapError.value = ''; render();
  } catch { if (!disposed) mapError.value = '底图加载失败，节点与链路列表仍可用'; }
}
function visibilityChanged() {
  if (document.hidden) { controller?.abort(); return; }
  if (!collapsed.value) { void refresh(true); chart?.resize(); }
}
watch(collapsed, async value => {
  try { localStorage.setItem(storageKey, value ? '1' : '0'); } catch { /* optional preference */ }
  if (!value) { await nextTick(); render(); chart?.resize(); void refresh(); }
});

const editing = ref<MapNode | null>(null);
const modal = ref<HTMLDialogElement | null>(null);
const latitude = ref<string | number>('');
const longitude = ref<string | number>('');
const locationLabel = ref('');
const saving = ref(false);
const editError = ref('');
const notice = ref('');
async function openEdit(node: MapNode) {
  if (!isAdmin.value) return;
  editing.value = node; latitude.value = node.latitude?.toString() ?? ''; longitude.value = node.longitude?.toString() ?? '';
  locationLabel.value = node.location_label ?? ''; editError.value = ''; notice.value = '';
  await nextTick(); modal.value?.showModal();
}
function closeEdit() { if (saving.value) return; modal.value?.close(); editing.value = null; }
async function saveLocation(clear = false) {
  if (!editing.value || !isAdmin.value || saving.value) return;
  editError.value = '';
  let input;
  try { input = clear ? { latitude: null, longitude: null, label: null } : parseLocationInput(latitude.value, longitude.value, locationLabel.value); }
  catch (e) { editError.value = e instanceof Error ? e.message : '请检查经纬度'; return; }
  saving.value = true;
  try {
    await updateMapLocation(editing.value.id, input);
    const verified = await refresh(true);
    notice.value = verified ? (clear ? '已取消人工位置，恢复自动定位' : '人工位置已保存') : '位置已提交，但重新读取失败；请刷新确认';
    saving.value = false; closeEdit();
  } catch { editError.value = '保存失败，请检查权限或稍后重试'; }
  finally { saving.value = false; }
}
onMounted(() => {
  observer = new ResizeObserver(() => chart?.resize());
  if (chartEl.value) observer.observe(chartEl.value);
  void loadMap(); void refresh();
  timer = setInterval(() => { if (!collapsed.value && !document.hidden) void refresh(); }, 15000);
  document.addEventListener('visibilitychange', visibilityChanged);
});
onUnmounted(() => {
  disposed = true; controller?.abort(); assetController.abort(); observer?.disconnect(); chart?.dispose();
  if (timer) clearInterval(timer);
  document.removeEventListener('visibilitychange', visibilityChanged);
});
</script>

<template>
  <section class="world-map" aria-label="服务器世界地图">
    <header class="map-header">
      <button class="collapse-button" :aria-expanded="!collapsed" aria-controls="world-map-content" @click="collapsed = !collapsed">
        <Icon name="globe" :size="15" /><strong>节点足迹</strong><Icon :name="collapsed ? 'chevron' : 'chevron-down'" :size="12" />
      </button>
      <span class="map-counts">{{ projected.stats.nodePairs }}个节点连接 · {{ projected.stats.tunnels }}条隧道 · {{ projected.stats.unmatched }}个未识别peer</span>
      <button class="map-button refresh" :disabled="loading" @click="refresh(true)">{{ loading ? '读取中' : '刷新' }}</button>
    </header>
    <div v-show="!collapsed" id="world-map-content">
      <div class="map-body">
        <div class="map-canvas-wrap">
          <div ref="chartEl" class="map-canvas" role="img" aria-label="世界地图，节点和链路也可从右侧列表访问" />
          <div v-if="mapError || (!loading && !grouped.groups.length)" class="map-empty">{{ mapError || (topology?.nodes.length ? '还没有可定位的节点，可在列表中补充城市位置' : '还没有节点足迹，等第一台服务器报到喵') }}</div>
          <div class="map-legend"><span><i class="dot online" />在线</span><span><i class="dot" />离线</span><span v-for="health in (['ok', 'degraded', 'failed', 'unknown'] as const)" :key="health"><i class="line" :class="{ stale: health === 'unknown' }" :style="{ borderColor: healthColors[health] }" />{{ healthLabels[health] }}</span></div>
          <a class="map-attribution" href="/maps/LICENSE.txt" target="_blank" rel="noopener">Natural Earth · Public domain</a><span class="location-caveat">出口位置不等于机房位置</span>
        </div>
        <aside class="map-panel" aria-label="节点与配置链路">
          <nav class="panel-tabs" aria-label="拓扑列表">
            <button :class="{ active: panel === 'nodes' }" @click="panel = 'nodes'">节点</button>
            <button :class="{ active: panel === 'links' }" @click="panel = 'links'">WG 链路</button>
            <button v-if="selectedIds.length || selectedId !== null" class="all-button" @click="selectedIds = []; selectedId = null">全部</button>
          </nav>
          <div class="panel-scroll">
            <template v-if="panel === 'nodes'">
              <div v-if="selectedNodes.length > 1" class="panel-hint">同城 / 同坐标 · {{ selectedNodes.length }} 台</div>
              <div v-for="node in (selectedNodes.length ? selectedNodes : topology?.nodes ?? [])" :key="node.id" class="node-row" :class="{ selected: selectedId === node.id }">
                <button class="node-select" @click="selectNode(node)"><i class="dot" :class="{ online: node.status === 'online' }" /><span>{{ node.name }}</span><small>#{{ node.id }}</small></button>
                <div class="node-meta">{{ statusLabels[node.status] ?? node.status }} · {{ node.location_source === 'unknown' ? '位置未知' : `${node.location_label || '未命名位置'} · ${locationSourceLabel(node)}` }}</div>
                <div class="node-actions"><button class="map-button" @click="router.push(`/status/${node.id}`)">详情 <Icon name="chevron" :size="11" /></button><button v-if="isAdmin" class="map-button" @click="openEdit(node)"><Icon name="edit" :size="11" />位置</button></div>
              </div>
              <p v-if="!topology?.nodes.length" class="panel-hint">暂无节点</p>
              <div v-if="selectedNode" class="node-detail">
                <p>WG 最近握手：{{ latestHandshake(selectedNode) }}</p>
                <p>位置观测：{{ timestamp(selectedNode.location_observed_at) }}</p>
                <p v-if="selectedNode.location_reason">{{ mapReasonLabel(selectedNode.location_reason) }}</p>
                <button class="map-button" @click="panel = 'links'">查看配置链路 ({{ visibleLinks.length }})</button>
              </div>
            </template>
            <template v-else>
              <p class="panel-hint">{{ selectedId === null ? '全部配置链路' : nodeName(selectedId) }} · 握手不等于实测；ICMP成功不保证业务TCP可用</p>
              <article v-for="link in visibleLinks" :key="link.id" class="link-row">
                <div class="link-title">{{ nodeName(link.source) }} → {{ nodeName(link.target) }}</div>
                <div class="link-state" :class="link.state">{{ stateLabels[link.state] }}</div>
                <div class="link-state" :style="{ color: healthColors[linkHealth(link)] }">{{ healthLabels[linkHealth(link)] }}</div>
                <p>探测时间：{{ timestamp(link.health_checked_at) }}</p>
                <p v-if="link.health_reason">{{ mapReasonLabel(link.health_reason) }}</p>
                <div class="probe-details">
                  <p v-for="(observation, index) in link.observations ?? []" :key="index">{{ nodeName(observation.source) }} → {{ nodeName(observation.target) }} · {{ observation.interface }}<br/><template v-if="observation.probe">{{ healthLabels[observation.health ?? observation.probe.status] }} · {{ observation.probe.received }}/{{ observation.probe.sent }} 包 · 丢包 {{ observation.probe.loss_pct ?? '未知' }}% · RTT {{ observation.probe.rtt_ms ?? '未知' }} ms<br/>{{ timestamp(observation.probe.checked_at) }}<br/>{{ mapReasonLabel(observation.probe.reason) }}</template><template v-else>尚未收到该方向的探测报告</template></p>
                </div>
                <p>{{ link.source_interface }} → {{ link.target_interface || link.peer_label || '未知接口' }}</p>
                <p>最近握手：{{ timestamp(link.latest_handshake_at) }}</p>
                <p>接收 {{ bytes(link.rx_bytes) }} · 发送 {{ bytes(link.tx_bytes) }}</p>
                <p v-if="unplacedReason(link.id)" class="unplaced">{{ unplacedReason(link.id) }}</p>
                <p v-if="link.reason">{{ mapReasonLabel(link.reason) }}</p>
              </article>
              <p v-if="!visibleLinks.length" class="panel-hint">暂无配置链路，不推测节点间连接</p>
            </template>
          </div>
        </aside>
      </div>
      <footer class="map-footer">
        <div v-if="grouped.unknown.length" class="unknown-list"><span>位置未知</span><button v-for="node in grouped.unknown" :key="node.id" :title="mapReasonLabel(node.location_reason) || '未获取到城市位置'" @click="selectNode(node)"><i class="dot" :class="{ online: node.status === 'online' }" />{{ node.name }}</button></div>
        <span v-else class="map-note">城市级位置 · 公网出口可能不在设备所在地</span>
        <span class="updated" :title="timestamp(topology?.generated_at)">15s 更新</span>
      </footer>
      <div v-if="error || notice" class="map-message" role="status">{{ error || notice }}</div>
    </div>
    <Teleport to="body">
      <dialog v-if="editing" ref="modal" class="location-modal" aria-labelledby="location-modal-title" @cancel.prevent="closeEdit" @click="($event.target === modal) && closeEdit()">
        <form @submit.prevent="saveLocation()">
          <header><strong id="location-modal-title">{{ editing.name }} · 人工位置</strong><button type="button" :disabled="saving" aria-label="关闭" @click="closeEdit"><Icon name="x" :size="15" /></button></header>
          <p>只填写城市级位置即可。人工位置优先；取消人工设置后恢复自动定位。</p>
          <label>位置名称<input v-model="locationLabel" maxlength="160" placeholder="如：中国 · 香港" :disabled="saving" autofocus /></label>
          <div class="coordinate-fields"><label>纬度<input v-model="latitude" type="number" step="any" min="-90" max="90" required placeholder="-90 ～ 90" :disabled="saving" /></label><label>经度<input v-model="longitude" type="number" step="any" min="-180" max="180" required placeholder="-180 ～ 180" :disabled="saving" /></label></div>
          <p v-if="editError" class="edit-error" role="alert">{{ editError }}</p>
          <footer><button v-if="editing.location_source === 'manual'" type="button" class="clear-button" :disabled="saving" @click="saveLocation(true)">取消人工位置</button><span /><button type="button" :disabled="saving" @click="closeEdit">取消</button><button type="submit" class="save-button" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button></footer>
        </form>
      </dialog>
    </Teleport>
  </section>
</template>

<style scoped>
.world-map { margin-bottom: 24px; border: 1px solid #2c3341; border-radius: 10px; background: #14171f; color: #c9d4e8; font: 12px Inter, sans-serif; overflow: hidden; }
.world-map button, .location-modal button { font: inherit; color: inherit; cursor: pointer; white-space: nowrap; }
.world-map button:disabled, .location-modal button:disabled { opacity: .5; cursor: default; }
.world-map button:focus-visible, .location-modal button:focus-visible { outline: 2px solid #9eb7e5; outline-offset: -2px; }
.map-header { min-height: 42px; display: flex; align-items: center; gap: 12px; padding: 0 14px; border-bottom: 1px solid #262d3a; }
.collapse-button { display: flex; align-items: center; gap: 8px; border: 0; background: none; padding: 8px 0; }
.collapse-button strong { font-size: 13px; font-weight: 550; }
.map-counts { color: #8d9ab0; font-size: 11px; }
.map-button { display: inline-flex; align-items: center; gap: 4px; border: 1px solid #323b4b; border-radius: 5px; background: transparent; padding: 3px 7px; font-size: 11px !important; }
.map-button:hover { background: #262d3a; }
.refresh { margin-left: auto; }
.map-body { display: grid; grid-template-columns: minmax(0, 1fr) 255px; grid-template-rows: minmax(0, 1fr); height: 320px; }
.map-canvas-wrap { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
.map-canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.map-empty { position: absolute; left: 10%; right: 10%; top: 40%; padding: 10px; border-radius: 6px; text-align: center; background: #14171fe8; color: #a7b4c9; pointer-events: none; }
.map-legend { position: absolute; bottom: 19px; left: 12px; display: flex; flex-wrap: wrap; gap: 10px; pointer-events: none; font-size: 10px; color: #9caac0; }
.map-legend span { display: flex; align-items: center; gap: 4px; }
.dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #768091; flex-shrink: 0; }
.dot.online { background: #ff9ec7; }
.line { width: 14px; border-top: 1px solid #899dbb; }
.line.stale { border-top-style: dashed; }
.line.never { border-color: #505866; }
.map-attribution { position: absolute; bottom: 4px; left: 12px; font-size: 9px; color: #76849a; text-decoration: none; }
.location-caveat { position: absolute; right: 10px; bottom: 4px; font-size: 10px; color: #8d9ab0; pointer-events: none; }
.map-panel { min-width: 0; min-height: 0; border-left: 1px solid #2c3341; display: flex; flex-direction: column; background: #181d27; }
.panel-tabs { display: flex; gap: 4px; padding: 7px 9px; border-bottom: 1px solid #2c3341; }
.panel-tabs button { border: 0; background: transparent; color: #8d9ab0; padding: 3px 6px; font-size: 11px; border-radius: 4px; }
.panel-tabs button.active { background: #293243; color: #c9d4e8; }
.panel-tabs .all-button { margin-left: auto; }
.panel-scroll { overflow-y: auto; min-height: 0; padding: 0 10px 8px; scrollbar-width: thin; }
.node-row { position: relative; padding: 8px 0; border-bottom: 1px solid #29303e; }
.node-select { display: flex; align-items: center; gap: 6px; background: none; border: 0; width: 100%; padding: 0; text-align: left; }
.node-select span { overflow: hidden; text-overflow: ellipsis; }
.node-select small { margin-left: auto; color: #8d9ab0; }
.node-row.selected .node-select { color: #ffb6d6; }
.node-meta { color: #8d9ab0; font-size: 10px; margin-top: 4px; overflow-wrap: anywhere; }
.node-actions { display: flex; gap: 5px; margin-top: 5px; }
.panel-hint, .node-detail { color: #8d9ab0; font-size: 10px; line-height: 1.6; margin: 8px 0; overflow-wrap: anywhere; }
.node-detail p { margin: 4px 0; }
.link-row { padding: 9px 0; border-bottom: 1px solid #29303e; overflow-wrap: anywhere; }
.link-title { font-size: 11px; }
.link-state { font-size: 10px; color: #8b97aa; margin-top: 4px; }
.link-state.recent { color: #b4c5df; }
.link-state.stale { text-decoration: underline dashed; text-underline-offset: 3px; }
.link-row p { font-size: 10px; color: #8d9ab0; margin: 4px 0; line-height: 1.5; }
.link-row .unplaced { color: #b5aaba; }
.map-footer { display: flex; align-items: center; gap: 10px; min-height: 36px; padding: 6px 12px; border-top: 1px solid #262d3a; font-size: 10px; color: #8d9ab0; }
.unknown-list { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; max-height: 65px; overflow-y: auto; }
.unknown-list button { display: inline-flex; align-items: center; gap: 5px; border: 1px solid #323b4b; background: #202633; border-radius: 12px; padding: 3px 8px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.updated { margin-left: auto; white-space: nowrap; }
.map-message { padding: 6px 12px; color: #d1b5c5; font-size: 11px; border-top: 1px solid #262d3a; }
.location-modal { box-sizing: border-box; width: min(390px, calc(100vw - 28px)); margin: auto; padding: 18px; color: #c9d4e8; background: #1b202b; border: 1px solid #3a4458; border-radius: 10px; font: 12px Inter, sans-serif; }
.location-modal::backdrop { background: #090c14b8; }
.location-modal header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.location-modal header strong { overflow-wrap: anywhere; }
.location-modal button { border: 1px solid #3a4458; border-radius: 5px; background: transparent; padding: 6px 9px; }
.location-modal header button { border: 0; padding: 3px; }
.location-modal p { color: #96a4bb; font-size: 11px; line-height: 1.7; margin: 12px 0; }
.location-modal label { display: flex; flex-direction: column; gap: 6px; font-size: 11px; min-width: 0; }
.location-modal input { width: 100%; box-sizing: border-box; min-width: 0; padding: 8px 9px; background: #14171f; color: #c9d4e8; border: 1px solid #354056; border-radius: 5px; font: inherit; }
.location-modal input:focus { outline: 1px solid #9eb7e5; }
.coordinate-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.location-modal footer { margin-top: 18px; display: flex; align-items: center; gap: 7px; }
.location-modal footer span { flex: 1; }
.location-modal .save-button { background: #34435d; border-color: #596d8e; }
.location-modal .clear-button { color: #c7a9ba; padding-left: 0; border-color: transparent; }
.location-modal .edit-error { color: #ffb6d6; }
@media (max-width: 700px) {
  .map-header { gap: 7px; padding: 0 10px; flex-wrap: wrap; }
  .map-counts { font-size: 9px; }
  .map-body { height: auto; grid-template-columns: minmax(0, 1fr); grid-template-rows: 220px 170px; }
  .map-canvas-wrap { height: 220px; }
  .map-panel { height: 170px; border-left: 0; border-top: 1px solid #2c3341; }
  .node-row { padding-right: 0; min-height: 43px; }
  .node-actions { position: static; justify-content: flex-end; margin-top: 6px; }
  .map-legend { gap: 7px; font-size: 9px; }
  .map-note { max-width: 80%; }
}
/* Keep metadata readable at desktop and mobile sizes. */
.map-counts, .node-meta, .panel-hint, .node-detail, .link-state, .link-row p,
.map-footer, .map-message, .map-legend, .panel-tabs button, .location-modal label,
.location-modal p { font-size: 12px; }
.node-select, .link-title { font-size: 13px; }
.map-button { font-size: 12px !important; }
@media (prefers-reduced-motion: reduce) { .world-map * { transition: none !important; } }
</style>
