<script setup lang="ts">
import { createPoller } from "./polling";
// 服务器页：节点清单 + 添加节点（纳管）+ 移除
import { ref, onMounted, onUnmounted, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { machineTypeLabel, machineTypeTitle, listNodes, createNode, removeNode, getHost, installHost, prepareHost, getInstallCommand, requestUninstall, type Node, type HostInfo } from "../../api/servers";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import NodeComponents from "./NodeComponents.vue";
import AgentManager from './AgentManager.vue';
import {auth} from '../home/auth';
const showChannels = ref(false), managerVisited = ref(false);
const managedAgents = computed(()=>nodes.value.map(({id,name,status,agent_version,last_seen_at})=>({id,name,status,agent_version,last_seen_at})));

const nodes = ref<Node[]>([]);
const listPending = ref(true);
const listReady = ref(false);
const listError = ref(false);
const loading = ref(false);
const showAdd = ref(false);

const newName = ref("");
const newPlatform = ref("linux");

const statusPoll = createPoller(refreshStatus, 5000);
function refresh() { return statusPoll.run(); }
function onVisibility() { if (document.hidden) statusPoll.stop(); else statusPoll.start(); }

async function refreshStatus(signal: AbortSignal) {
  listPending.value = true;
  try {
    const rows = await listNodes(signal);
    if (!signal.aborted) { nodes.value = rows; listReady.value = true; listError.value = false; }
  } catch {
    if (!signal.aborted) listError.value = true;
  } finally {
    if (!signal.aborted) listPending.value = false;
  }
  if (!signal.aborted) await refreshHost();
}

// 宿主机「本机」检测 + 一键安装
const host = ref<HostInfo | null>(null);
const installing = ref(false);
const hostError = ref('');
const hostBusy = computed(() => installing.value || ['queued', 'installing'].includes(host.value?.installation?.status || ''));
function failureMessage(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown })?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String(detail.message);
  return error instanceof Error && !/^API \d+$/.test(error.message) ? error.message : fallback;
}

// All host readback entry points share this latest-request generation.
// getHost has no transport signal; fence both success and failure locally.
let hostRequest = 0;
let hostDisposed = false;
async function refreshHost() {
  if (hostDisposed) return;
  const request = ++hostRequest;
  try {
    const fresh = await getHost();
    if (!hostDisposed && request === hostRequest) host.value = fresh;
  } catch (error) {
    if (!hostDisposed && request === hostRequest) hostError.value = failureMessage(error, '宿主安装状态读取失败，请重试');
  }
}

async function doInstallHost() {
  installing.value = true; hostError.value = '';
  try {
    await installHost();
    toast('本站实例服务安装完成；等待 Agent 认证上报在线，不代表已正常接入');
  } catch (error) {
    hostError.value = failureMessage(error, '本站宿主安装失败，请检查权限与已应用安装地址');
    toast(hostError.value);
  } finally {
    await refresh(); await refreshHost(); installing.value = false;
  }
}
async function openHostAccess() {
  try {
    const node = await prepareHost();
    await refreshHost(); await refresh(); openAgent(node);
  } catch (error) { hostError.value = failureMessage(error, '宿主接入准备失败，请重试'); }
}

onMounted(() => {
  if (!document.hidden) statusPoll.start();
  document.addEventListener("visibilitychange", onVisibility);
  refreshHost();

});
onUnmounted(() => { hostDisposed = true; hostRequest++; statusPoll.stop(); document.removeEventListener("visibilitychange", onVisibility); });

const onlineCount = computed(() => nodes.value.filter((n) => n.status === "online").length);

async function addNode() {
  if (!newName.value.trim()) {
    toast("名称要填喵~");
    return;
  }
  loading.value = true;
  try {
    const node = await createNode({
      name: newName.value.trim(),
      platform: newPlatform.value,
      host: "",
    });
    toast(`已添加节点「${node.name}」，token 已生成`);
    showAdd.value = false;
    newName.value = "";
    // 显示安装命令
    await refresh();
    installTarget.value = node;
  } catch {
    toast("添加失败，稍后再试");
  } finally {
    loading.value = false;
  }
}

// 破坏性操作二次确认（卸载/移除）：用项目自己的 modal，不用浏览器原生 confirm
const confirmState = ref<{ type: "uninstall" | "remove"; node: Node; closeDialog?: boolean } | null>(null);

async function doRemove(n: Node) {
  try {
    await removeNode(n.id);
    toast(`已移除「${n.name}」`);
    await refresh();
    await refreshHost(); // 宿主机移除后 host.installed 变了，立即刷新让预设 host-card 出现
  } catch {
    toast("移除失败");
  }
}

async function doUninstall(n: Node, closeDialog = false) {
  try {
    await requestUninstall(n.id);
    toast("卸载指令已下发");
    if (closeDialog) installTarget.value = null;
    await refresh();
  } catch {
    toast("卸载发起失败");
  }
}

function askRemove(n: Node) {
  confirmState.value = { type: "remove", node: n };
}

function askUninstall(n: Node, closeDialog = false) {
  confirmState.value = { type: "uninstall", node: n, closeDialog };
}

async function confirmAction() {
  const s = confirmState.value;
  confirmState.value = null;
  if (!s) return;
  if (s.type === "uninstall") await doUninstall(s.node, s.closeDialog);
  else await doRemove(s.node);
}

// 节点能否直接移除：agent 没在运行（离线/未装）才能移除。检测走实时 status，不看历史 installed
function canRemove(n: Node): boolean {
  return n.status !== "online";
}

// 安装命令弹窗
const installTarget = ref<Node | null>(null);
const command = ref(''), commandError = ref(''), commandPending = ref(false);
let commandRequest: AbortController | undefined;
watch([installTarget, () => host.value?.installation_url], async ([target]) => {
  commandRequest?.abort(); command.value = ''; commandError.value = ''; commandPending.value = false;
  if (!target) return;
  if (!host.value?.installation_url) {
    commandError.value = host.value?.installation_address_error || '请先在设置中应用本站安装地址';
    return;
  }
  const request = new AbortController(); commandRequest = request; commandPending.value = true;
  try {
    const result = await getInstallCommand(target.id, request.signal);
    if (!request.signal.aborted && installTarget.value?.id === target.id) command.value = result.command;
  } catch (error) {
    if (!request.signal.aborted) commandError.value = failureMessage(error, '安装命令获取失败，请检查管理权限与已应用地址');
  } finally { if (!request.signal.aborted) commandPending.value = false; }
}, { flush: 'sync' });
onUnmounted(() => { commandRequest?.abort(); command.value = ''; });
function openAgent(n: Node) { installTarget.value = n; }
async function copyCmd() {
  if (!command.value || commandPending.value || commandError.value) return;
  try {
    await navigator.clipboard.writeText(command.value);
    toast('已复制'); installTarget.value = null;
  } catch { toast('复制失败，请手动复制'); }
}
function isHostNode(n: Node | null): boolean { return !!n && n.id === host.value?.node_id; }
async function doAutoInstall() { await doInstallHost(); }

const router = useRouter();
function goSettings() {
  installTarget.value = null;
  router.push("/settings?section=services");
}

// 点卡片 → 独立路由进详情（SPA 切换不刷新，刷新/后退行为正常）
function goDetail(n: Node) {
  if (n.status !== 'online') { toast('节点尚未正常在线，不能进入详情；请先完成 Agent 接入'); return; }
  router.push(`/status/${n.id}`);
}

const statusLabel: Record<string, string> = {
  online: "在线", offline: "离线", pending: "待报到", removed: "已移除",
};
const statusColor: Record<string, string> = {
  online: "var(--pink)", offline: "var(--text-faint)", pending: "var(--accent-dim)", removed: "var(--text-faint)",
};
const uninstallLabel: Record<string, string> = {
  pending: "下发中", running: "agent删除中", done: "已删除", failed: "卸载异常",
};
</script>

<template>
  <div class="nodes-view">
    <div class="head">
      <div>
        <h2>服务器</h2>
        <span v-if="listReady" class="sub">{{ nodes.length }} 台纳管 · {{ onlineCount }} 在线</span>
      </div>
      <div class="head-actions"><button class="add-btn" @click="managerVisited = true; showChannels = true">Agent 管理</button><button v-if="nodes.length" class="add-btn" @click="showAdd = true"><Icon name="plus" :size="14" /> 添加节点</button></div>
    </div>

    <AgentManager v-if="managerVisited" :key="auth.me?.id??'guest'" :open="showChannels" :nodes="managedAgents" @close="showChannels = false" />
    <!-- 节点卡片网格 -->
    <div v-if="listError" class="empty" role="alert">
      服务器加载失败{{ listReady ? '，保留上次结果' : '' }}
      <button class="add-btn" :disabled="listPending" @click="refresh">重试</button>
    </div>
    <div class="grid">
      <!-- 宿主机「本机」：未装 agent 时显示安装入口 -->
      <p v-if="hostError" class="hint warn" role="alert">{{ hostError }}</p>
      <div v-if="host" class="host-card">
        <div class="host-info">
          <span class="dot" :style="{background: host.node_status === 'online' ? 'var(--pink)' : 'var(--text-faint)'}" />
          <div>
            <div class="name">Stella（宿主机）</div>
            <div class="plat">{{ host.os || '宿主机系统待探测' }} · {{ host.node_status === 'online' ? '本站 Agent 已认证在线' : host.installation?.message || '尚未正常接入' }}</div>
            <div v-if="host.local_install_supported === false" class="hint">本站运行在容器内，不能代装宿主机；请在真实宿主机执行下方接入命令。</div>
            <div v-if="host.installation_address_error" class="hint warn">{{ host.installation_address_error }}</div>
          </div>
        </div>
        <button v-if="!host.installation_url" class="jump-settings" @click="goSettings">去设置安装地址</button>
        <button class="add-btn" :disabled="hostBusy" @click="openHostAccess">宿主机接入命令</button>
        <button v-if="host.local_install_supported !== false && host.node_status !== 'online'" class="install-btn" :disabled="hostBusy || !host.installation_url" @click="doInstallHost">
          <span v-if="hostBusy" class="spin" />{{ hostBusy ? '安装任务进行中…' : '安装本站宿主 Agent' }}
        </button>
      </div>
      <div v-for="n in nodes" :key="n.id" class="card" :aria-disabled="n.status !== 'online'" :title="n.status !== 'online' ? '节点正常在线后才可进入详情' : '节点详情'" @click="goDetail(n)">
        <div class="card-top">
          <span class="dot" :style="{ background: statusColor[n.status] }" />
          <span class="name">{{ n.name }}</span>
          <span class="machine-badge" :title="machineTypeTitle(n.sys_info?.hardware?.machine)">{{ machineTypeLabel(n.sys_info?.hardware?.machine) }}</span>
          <span class="plat">{{ n.os_name || n.platform }}</span>
          <span v-if="n.net_type === 'public'" class="pub-badge" title="公网节点：可作为打流服务端">公网</span>
          <span class="actions">
            <button title="agent" @click.stop="openAgent(n)"><Icon name="terminal" :size="14" /></button>
            <button title="移除" @click.stop="askRemove(n)"><Icon name="trash" :size="14" /></button>
          </span>
        </div>
        <div class="card-meta">
          <div class="row"><span class="k">状态</span><span class="v">{{ statusLabel[n.status] }}</span></div>
          <div class="row" v-if="n.arch"><span class="k">架构</span><span class="v">{{ n.arch }}</span></div>
          <div class="row" v-if="n.agent_version"><span class="k">agent</span><span class="v">v{{ n.agent_version }}</span></div>
          <div class="row" v-if="n.last_seen_at"><span class="k">心跳</span><span class="v">{{ new Date(n.last_seen_at).toLocaleString() }}</span></div>
        </div>
        <!-- 卸载区（仅显示进度/结果；发起卸载在 agent 弹窗里） -->
        <div v-if="n.uninstall_status" class="uninstall-zone">
          <div v-if="n.uninstall_status === 'pending' || n.uninstall_status === 'running'" class="uninstall-progress">
            <span class="uninstall-text">{{ uninstallLabel[n.uninstall_status] }}</span>
            <div class="progress-bar"><div class="progress-fill" /></div>
          </div>
          <div v-else-if="n.uninstall_status === 'done'" class="uninstall-done">
            <span class="uninstall-text done">{{ uninstallLabel[n.uninstall_status] }}</span>
          </div>
          <div v-else-if="n.uninstall_status === 'failed'" class="uninstall-failed">
            <span class="uninstall-text failed">卸载异常{{ n.uninstall_error ? '：' + n.uninstall_error : '' }}</span>
            <button class="uninstall-btn" @click="askUninstall(n)">重试</button>
          </div>
        </div>
      </div>
      <div v-if="!listReady && listPending" class="empty" role="status">正在加载服务器…</div>
      <div v-if="listReady && !listError && !nodes.length" class="empty">
        <p>还没有纳管其他服务器</p>
        <button class="add-btn" @click="showAdd = true"><Icon name="plus" :size="14" /> 添加第一台</button>
      </div>
    </div>

    <!-- 全量组件状态（打流页只显示 iperf3/speedtest） -->
    <NodeComponents v-if="nodes.length" class="comp-panel" :nodes="nodes" :comps="['iperf3', 'speedtest', 'ufw', 'docker', 'mtr']" @refresh="refresh" />

    <!-- 添加节点弹窗 -->
    <div v-if="showAdd" class="mask" @click.self="showAdd = false">
      <div class="dialog">
        <div class="d-head">添加节点</div>
        <div class="d-body">
          <label>名称</label>
          <input v-model="newName" placeholder="如 HK VPS" />
          <label>平台</label>
          <select v-model="newPlatform">
            <option value="linux">Linux</option>
            <option value="windows">Windows</option>
            <option value="fnos">飞牛OS</option>
          </select>
        </div>
        <div class="d-foot">
          <button class="cancel" @click="showAdd = false">取消</button>
          <button class="confirm" :disabled="loading" @click="addNode">添加</button>
        </div>
      </div>
    </div>

    <!-- 安装命令弹窗 -->
    <div v-if="installTarget" class="mask" @click.self="installTarget = null">
      <div class="dialog">
        <div class="d-head">agent — {{ installTarget.name }}</div>
        <div class="d-body">
          <p v-if="isHostNode(installTarget)" class="hint">本站明确绑定的宿主节点 · {{ statusLabel[installTarget.status] }}。服务安装完成后仍需等 Agent 认证在线。</p>
          <p v-if="commandPending" class="hint" role="status">正在向本站获取安装命令…</p>
          <p v-else-if="commandError" class="hint warn" role="alert">{{ commandError }}</p>
          <template v-else-if="command">
            <p class="hint">在目标服务器上以管理员执行（含节点凭证，请勿泄露）：</p>
            <pre class="cmd">{{ command }}</pre>
          </template>
        </div>
        <div class="d-foot">
          <div class="foot-actions">
            <button v-if="commandError || !host?.installation_url" class="jump-settings" @click="goSettings">去设置安装地址</button>
            <button v-if="host?.local_install_supported !== false && isHostNode(installTarget) && host?.installation_url" class="jump-settings" :disabled="hostBusy" @click="doAutoInstall">
              <span v-if="hostBusy" class="spin" />{{ hostBusy ? '安装任务进行中…' : installTarget.installed ? '重新安装' : '自动安装' }}
            </button>
            <button v-if="installTarget.installed && installTarget.status === 'online'" class="uninstall-btn danger" @click="askUninstall(installTarget, true)">卸载 agent</button>
            <button v-if="command && !commandError" class="confirm" :disabled="commandPending" @click="copyCmd">复制并关闭</button>
            <button class="cancel" @click="installTarget = null">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 破坏性操作二次确认（卸载/移除）：项目自己的 modal -->
    <div v-if="confirmState" class="mask" @click.self="confirmState = null">
      <div class="dialog">
        <div class="d-head danger-text">确认{{ confirmState.type === "uninstall" ? "卸载" : "移除" }}</div>
        <div class="d-body">
          <template v-if="confirmState.type === 'remove'">
            <p v-if="!canRemove(confirmState.node)" class="hint warn">该节点 agent 还在运行，请先到「agent」弹窗卸载后再移除喵~</p>
            <p class="hint">移除节点「{{ confirmState.node.name }}」？移除后 agent 无法再上报。</p>
          </template>
          <p v-else class="hint">卸载「{{ confirmState.node.name }}」的 agent？卸载后 agent 会删除自己，该节点停止上报。</p>
        </div>
        <div class="d-foot">
          <div class="foot-actions">
            <button class="cancel" @click="confirmState = null">取消</button>
            <button
              v-if="confirmState.type === 'uninstall'"
              class="danger"
              @click="confirmAction"
            >确认卸载</button>
            <button
              v-else
              class="danger"
              :disabled="!canRemove(confirmState.node)"
              @click="confirmAction"
            >{{ canRemove(confirmState.node) ? "确认移除" : "请先卸载 agent" }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.machine-badge { flex-shrink: 0; font-size: 10.5px; color: var(--accent); border: 1px solid var(--accent-dim); padding: 1px 7px; border-radius: 999px; }
.nodes-view {
  height: 100%;
  overflow-y: auto;
  padding: 22px 26px;
}
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.head-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}
h2 { font-size: 19px; font-weight: 600; letter-spacing: 1px; }
.sub { color: var(--text-faint); font-size: 12px; margin-left: 10px; }
.add-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border: 1px solid var(--accent-dim); border-radius: var(--radius-sm);
  background: transparent; color: var(--accent); font-size: 13px; cursor: pointer;
  transition: all var(--transition);
}
.add-btn:hover { background: var(--bg-raised); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr)); gap: 14px; }
.comp-panel { margin-top: 16px; background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.05); border-radius: var(--radius); }
.card {
  min-width: 0;
  background: var(--bg-raised);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius);
  padding: 14px 16px;
  transition: all var(--transition);
  cursor: pointer;
}
.card:hover { border-color: var(--accent-dim); transform: translateY(-2px); }
.card-top { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 9px; margin-bottom: 10px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.name { min-width: 0; overflow-wrap: anywhere; font-size: 15px; font-weight: 600; }
.plat { font-size: 10.5px; color: var(--text-faint); border: 1px solid var(--text-faint); padding: 1px 7px; border-radius: 999px; }
.pub-badge { font-size: 10.5px; color: var(--accent); border: 1px solid var(--accent-dim); padding: 1px 7px; border-radius: 999px; }
.actions { margin-left: auto; display: flex; gap: 4px; }
.actions button { border: none; background: transparent; color: var(--text-faint); cursor: pointer; padding: 4px; border-radius: 4px; }
.actions button:hover { color: var(--accent); background: var(--bg-panel); }
.card-meta .row { display: flex; justify-content: space-between; font-size: 12.5px; padding: 2px 0; }
.k { color: var(--text-faint); }
.v { color: var(--text-lo); }
.uninstall-zone { margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.05); }
.uninstall-btn {
  border: 1px solid var(--accent-dim); background: transparent; color: var(--accent);
  font-size: 12px; padding: 4px 14px; border-radius: 999px; cursor: pointer;
}
.uninstall-btn:hover { background: var(--bg-panel); }
.uninstall-btn.danger { border-color: var(--pink); color: var(--pink); }
.uninstall-progress { display: flex; flex-direction: column; gap: 6px; }
.uninstall-text { font-size: 12px; color: var(--text-lo); }
.uninstall-text.done { color: var(--text-faint); }
.uninstall-text.failed { color: var(--pink); }
.uninstall-done, .uninstall-failed { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.progress-bar { height: 4px; background: var(--bg-base); border-radius: 999px; overflow: hidden; position: relative; }
.progress-fill { height: 100%; width: 30%; background: var(--accent); border-radius: 999px; position: absolute; animation: uninstall-slide 1.2s ease-in-out infinite; }
@keyframes uninstall-slide {
  0% { left: 0; }
  50% { left: 60%; }
  100% { left: 0; }
}
.empty { grid-column: 1/-1; text-align: center; padding: 60px 0; color: var(--text-faint); }
.empty p { margin-bottom: 14px; }
.host-card {
  grid-column: 1/-1; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;
  background: var(--bg-raised); border: 1px dashed var(--accent-dim);
  border-radius: var(--radius); padding: 14px 16px;
}
.host-info { display: flex; align-items: center; gap: 9px; flex: 1 1 260px; min-width: 0; overflow-wrap: anywhere; }
.install-btn {
  border: 1px solid var(--accent-dim); background: transparent; color: var(--accent);
  font-size: 12px; padding: 6px 16px; border-radius: 999px; cursor: pointer;
}
.install-btn:hover { background: var(--bg-panel); }
.install-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.mask { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: grid; place-items: center; z-index: 100; }
.dialog { width: min(420px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); overflow-y: auto; overflow-wrap: anywhere; background: var(--bg-panel); border: 1px solid var(--bg-raised); border-radius: var(--radius); }
.dialog input, .dialog select { min-width: 0; }
.d-head { padding: 14px 18px; font-size: 14px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.05); }
.d-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 6px; }
.d-body label { font-size: 11.5px; color: var(--text-faint); margin-top: 4px; }
.d-body input, .d-body select {
  padding: 8px 12px; background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); font-size: 13px; outline: none;
}
.d-body input:focus { border-color: var(--accent-dim); }
.d-body .hint { font-size: 12px; color: var(--text-lo); }
.d-body .hint.warn { color: var(--pink); }
.cmd {
  background: var(--bg-base); padding: 12px; border-radius: var(--radius-sm);
  font-size: 11.5px; color: var(--accent); white-space: pre-wrap; word-break: break-all;
  font-family: var(--font-mono);
}
.d-foot { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 12px 18px 16px; }
.d-foot button { padding: 8px 18px; border-radius: var(--radius-sm); font-size: 13px; cursor: pointer; }
.d-foot .jump-settings { background: transparent; border: 1px solid var(--accent-dim); color: var(--accent); }
.d-foot .foot-actions { display: flex; gap: 8px; }
.d-foot .cancel { background: transparent; border: 1px solid var(--text-faint); color: var(--text-faint); }
.d-foot .confirm { background: var(--accent); border: none; color: var(--bg-base); font-weight: 600; }
.d-foot .confirm:disabled { opacity: 0.5; cursor: not-allowed; }
.d-foot .danger { background: transparent; border: 1px solid var(--pink); color: var(--pink); }
.d-foot .danger:disabled { opacity: 0.4; cursor: not-allowed; }
.d-head.danger-text { color: var(--pink); }
.spin {
  display: inline-block;
  width: 12px; height: 12px;
  border: 2px solid currentColor; border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: -2px; margin-right: 6px;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
