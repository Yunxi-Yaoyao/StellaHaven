<script setup lang="ts">
// 服务器页：节点清单 + 添加节点（纳管）+ 移除
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useRouter } from "vue-router";
import { listNodes, createNode, removeNode, getHost, installHost, getPublicHost, requestUninstall, type Node, type HostInfo } from "../../api/servers";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import NodeComponents from "./NodeComponents.vue";

const nodes = ref<Node[]>([]);
const loading = ref(false);
const showAdd = ref(false);

const newName = ref("");
const newPlatform = ref("linux");

let timer: ReturnType<typeof setInterval> | null = null;

async function refresh() {
  try {
    nodes.value = await listNodes();
  } catch {
    /* 后端未就绪时静默 */
  }
}

// 宿主机「本机」检测 + 一键安装
const host = ref<HostInfo | null>(null);
const installing = ref(false);
const publicHost = ref("");

async function refreshHost() {
  try { host.value = await getHost(); } catch { /* 静默 */ }
}

async function loadPublicHost() {
  try { publicHost.value = (await getPublicHost()).value; } catch { /* 静默 */ }
}

async function doInstallHost() {
  installing.value = true;
  try {
    const node = await installHost();
    toast(`本机 agent 已装好，节点「${node.name}」纳管成功`);
    await refresh();
    await refreshHost();
  } catch { toast("安装失败喵~"); }
  finally { installing.value = false; }
}

onMounted(() => {
  refresh();
  refreshHost();
  loadPublicHost();
  timer = setInterval(refresh, 5000); // 5s 刷新（心跳状态实时）
});
onUnmounted(() => { if (timer) clearInterval(timer); });

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

function openAgent(n: Node) {
  installTarget.value = n;
}
function installCmd(n: Node): string {
  const raw = publicHost.value || location.origin;
  const url = raw.includes("://") ? raw : `https://${raw}`;
  if (n.platform === "windows") {
    return `iwr ${url}/agent/install.ps1 -UseBasicParsing | iex`;
  }
  return `curl -sSL ${url}/agent/install.sh | sudo bash -s -- --url ${url} --token ${n.token}`;
}
async function copyCmd(n: Node) {
  try {
    await navigator.clipboard.writeText(installCmd(n));
    toast("已复制");
  } catch {
    toast("复制失败，请手动复制");
  }
  installTarget.value = null;
}

function isHostNode(n: Node | null): boolean {
  return !!n && (n.name === "Stella" || ["127.0.0.1", "localhost"].includes(n.host));
}

async function doAutoInstall() {
  installing.value = true;
  try {
    await installHost();
    toast("本机 agent 已装好");
    installTarget.value = null;
    await refresh();
    await refreshHost();
  } catch {
    toast("自动安装失败喵~");
  } finally {
    installing.value = false;
  }
}

const router = useRouter();
function goSettings() {
  installTarget.value = null;
  router.push("/settings?tab=misc");
}

// 点卡片 → 独立路由进详情（SPA 切换不刷新，刷新/后退行为正常）
function goDetail(n: Node) {
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
        <span class="sub">{{ nodes.length }} 台纳管 · {{ onlineCount }} 在线</span>
      </div>
      <button v-if="nodes.length" class="add-btn" @click="showAdd = true"><Icon name="plus" :size="14" /> 添加节点</button>
    </div>

    <!-- 节点卡片网格 -->
    <div class="grid">
      <!-- 宿主机「本机」：未装 agent 时显示安装入口 -->
      <div v-if="host && !host.installed" class="host-card">
        <div class="host-info">
          <span class="dot" style="background: var(--text-faint)" />
          <div>
            <div class="name">Stella（宿主机）</div>
            <div class="plat">{{ host.os }} · 未安装 agent</div>
          </div>
        </div>
        <button class="install-btn" :disabled="installing" @click="doInstallHost">
          <span v-if="installing" class="spin" />{{ installing ? "安装中…" : "安装" }}
        </button>
      </div>
      <div v-for="n in nodes" :key="n.id" class="card" @click="goDetail(n)">
        <div class="card-top">
          <span class="dot" :style="{ background: statusColor[n.status] }" />
          <span class="name">{{ n.name }}</span>
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
      <div v-if="!nodes.length" class="empty">
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
          <template v-if="isHostNode(installTarget) && installTarget.installed">
            <p class="hint">该节点已托管 · {{ statusLabel[installTarget.status] }}{{ installTarget.agent_version ? ' · v' + installTarget.agent_version : '' }}</p>
          </template>
          <template v-else>
            <p v-if="!isHostNode(installTarget) && !publicHost" class="hint warn">⚠️ 还没设置公网 IP/域名，远程节点连不上中心喵~</p>
            <p class="hint">在目标服务器上执行（token 已内嵌，不要泄露）：</p>
            <pre class="cmd">{{ installCmd(installTarget) }}</pre>
          </template>
        </div>
        <div class="d-foot">
          <div class="foot-actions">
            <template v-if="isHostNode(installTarget) && installTarget.installed">
              <button class="jump-settings" :disabled="installing" @click="doAutoInstall()">
                <span v-if="installing" class="spin" />{{ installing ? "重新安装中…" : "重新安装" }}
              </button>
              <button v-if="installTarget.status === 'online'" class="uninstall-btn danger" @click="askUninstall(installTarget, true)">卸载 agent</button>
              <button class="cancel" @click="installTarget = null">关闭</button>
            </template>
            <template v-else>
              <button v-if="!isHostNode(installTarget) && !publicHost" class="jump-settings" @click="goSettings">去设置公网地址</button>
              <button v-if="isHostNode(installTarget)" class="confirm" :disabled="installing" @click="doAutoInstall">
                <span v-if="installing" class="spin" />{{ installing ? "安装中…" : "自动安装" }}
              </button>
              <button v-if="installTarget.installed && installTarget.status === 'online'" class="uninstall-btn danger" @click="askUninstall(installTarget, true)">卸载 agent</button>
              <button class="confirm" @click="copyCmd(installTarget)">复制并关闭</button>
            </template>
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
.nodes-view {
  height: 100%;
  overflow-y: auto;
  padding: 22px 26px;
}
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
h2 { font-size: 19px; font-weight: 600; letter-spacing: 1px; }
.sub { color: var(--text-faint); font-size: 12px; margin-left: 10px; }
.add-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border: 1px solid var(--accent-dim); border-radius: var(--radius-sm);
  background: transparent; color: var(--accent); font-size: 13px; cursor: pointer;
  transition: all var(--transition);
}
.add-btn:hover { background: var(--bg-raised); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.comp-panel { margin-top: 16px; background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.05); border-radius: var(--radius); }
.card {
  background: var(--bg-raised);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius);
  padding: 14px 16px;
  transition: all var(--transition);
  cursor: pointer;
}
.card:hover { border-color: var(--accent-dim); transform: translateY(-2px); }
.card-top { display: flex; align-items: center; gap: 9px; margin-bottom: 10px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.name { font-size: 15px; font-weight: 600; }
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
  display: flex; align-items: center; justify-content: space-between;
  background: var(--bg-raised); border: 1px dashed var(--accent-dim);
  border-radius: var(--radius); padding: 14px 16px;
}
.host-info { display: flex; align-items: center; gap: 9px; }
.install-btn {
  border: 1px solid var(--accent-dim); background: transparent; color: var(--accent);
  font-size: 12px; padding: 6px 16px; border-radius: 999px; cursor: pointer;
}
.install-btn:hover { background: var(--bg-panel); }
.install-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.mask { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: grid; place-items: center; z-index: 100; }
.dialog { width: 420px; background: var(--bg-panel); border: 1px solid var(--bg-raised); border-radius: var(--radius); overflow: hidden; }
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
