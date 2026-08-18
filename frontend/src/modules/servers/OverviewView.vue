<script setup lang="ts">
// 总览页：服务器卡（节点状态）+ 服务监控卡（可达性）
import { ref, onMounted, onUnmounted } from "vue";
import { listNodes, listMonitors, createMonitor, removeMonitor, type Node, type Monitor } from "../../api/servers";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";

const nodes = ref<Node[]>([]);
const monitors = ref<Monitor[]>([]);
const showAddMon = ref(false);
const monName = ref("");
const monType = ref<"ping" | "tcp" | "udp" | "http" | "https">("tcp");
const monTarget = ref("");
const monInterval = ref(60);
const monNodeId = ref<number | null>(null);

let timer: ReturnType<typeof setInterval> | null = null;

async function refresh() {
  try {
    [nodes.value, monitors.value] = await Promise.all([listNodes(), listMonitors()]);
  } catch { /* 后端未就绪静默 */ }
}
onMounted(() => { refresh(); timer = setInterval(refresh, 5000); });
onUnmounted(() => { if (timer) clearInterval(timer); });

function openAddMon() {
  if (!nodes.value.length) { toast("还没有纳管节点，先去「服务器」页添加一台喵~"); return; }
  monNodeId.value = nodes.value[0].id;
  showAddMon.value = true;
}

async function addMonitor() {
  if (!monName.value.trim() || !monTarget.value.trim()) { toast("名称和目标都要填喵~"); return; }
  if (monNodeId.value == null) { toast("要先选探测节点喵~"); return; }
  try {
    await createMonitor({ name: monName.value.trim(), type: monType.value, target: monTarget.value.trim(), interval: monInterval.value, node_id: monNodeId.value });
    toast("监控项已添加");
    showAddMon.value = false;
    monName.value = ""; monTarget.value = "";
    await refresh();
  } catch { toast("添加失败"); }
}

async function delMonitor(m: Monitor) {
  try { await removeMonitor(m.id); toast("已删除"); await refresh(); } catch { toast("删除失败"); }
}

const statusLabel: Record<string, string> = { online: "在线", offline: "离线", pending: "待报到", removed: "已移除" };
const statusColor: Record<string, string> = { online: "var(--pink)", offline: "var(--text-faint)", pending: "var(--accent-dim)", removed: "var(--text-faint)" };
const monStatusColor: Record<string, string> = { up: "var(--pink)", down: "var(--text-faint)", unknown: "var(--accent-dim)" };
</script>

<template>
  <div class="overview">
    <div class="head">
      <h2>总览</h2>
      <span class="sub">监控看板 · 5s 刷新</span>
    </div>

    <!-- 服务器卡 -->
    <section class="block">
      <div class="block-head">服务器</div>
      <div class="card-grid">
        <div v-for="n in nodes" :key="n.id" class="srv-card">
          <span class="dot" :style="{ background: statusColor[n.status] }" />
          <span class="name">{{ n.name }}</span>
          <span class="st">{{ statusLabel[n.status] }}</span>
        </div>
        <div v-if="!nodes.length" class="hint-empty">暂无节点，去「服务器」页添加</div>
      </div>
    </section>

    <!-- 服务监控卡 -->
    <section class="block">
      <div class="block-head">
        服务监控
        <button class="mini-btn" @click="openAddMon"><Icon name="plus" :size="12" /> 添加</button>
      </div>
      <div class="mon-grid">
        <div v-for="m in monitors" :key="m.id" class="mon-card">
          <span class="dot" :style="{ background: monStatusColor[m.status] }" />
          <div class="mon-info">
            <div class="mon-name">{{ m.name }}</div>
            <div class="mon-target">{{ m.type }} · {{ m.target }}</div>
          </div>
          <span class="mon-latency" v-if="m.last_latency_ms != null">{{ m.last_latency_ms.toFixed(1) }}ms</span>
          <button class="mon-del" @click="delMonitor(m)"><Icon name="trash" :size="13" /></button>
        </div>
        <div v-if="!monitors.length" class="hint-empty">暂无监控项，点「添加」创建一个 TCP/HTTP 探测</div>
      </div>
    </section>

    <!-- 添加监控项弹窗 -->
    <div v-if="showAddMon" class="mask" @click.self="showAddMon = false">
      <div class="dialog">
        <div class="d-head">添加服务监控</div>
        <div class="d-body">
          <label>名称</label>
          <input v-model="monName" placeholder="如 官网首页" />
          <label>类型</label>
          <select v-model="monType">
            <option value="tcp">TCP</option>
            <option value="http">HTTP</option>
            <option value="https">HTTPS</option>
            <option value="ping">Ping</option>
            <option value="udp">UDP</option>
          </select>
          <label>目标</label>
          <input v-model="monTarget" placeholder="如 example.com 或 1.2.3.4:443" />
          <label>探测节点</label>
          <select v-model="monNodeId">
            <option v-for="n in nodes" :key="n.id" :value="n.id">{{ n.name }}</option>
          </select>
          <label>探测间隔（秒）</label>
          <input v-model.number="monInterval" type="number" min="10" />
        </div>
        <div class="d-foot">
          <button class="cancel" @click="showAddMon = false">取消</button>
          <button class="confirm" @click="addMonitor">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview { height: 100%; overflow-y: auto; padding: 22px 26px; }
.head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 18px; }
h2 { font-size: 19px; font-weight: 600; letter-spacing: 1px; }
.sub { color: var(--text-faint); font-size: 12px; }
.block { margin-bottom: 24px; }
.block-head {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 13px; font-weight: 600; color: var(--text-lo);
  letter-spacing: 1px; margin-bottom: 10px;
}
.mini-btn {
  display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid var(--accent-dim); background: transparent; color: var(--accent);
  font-size: 12px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
}
.mini-btn:hover { background: var(--bg-raised); }
.card-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.srv-card {
  display: flex; align-items: center; gap: 9px;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius-sm); padding: 10px 14px; font-size: 13px;
}
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.name { font-weight: 600; }
.st { color: var(--text-faint); font-size: 11px; }
.mon-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.mon-card {
  display: flex; align-items: center; gap: 10px;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius-sm); padding: 10px 14px; min-width: 220px;
}
.mon-info { flex: 1; min-width: 0; }
.mon-name { font-size: 13px; font-weight: 600; }
.mon-target { font-size: 11px; color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mon-latency { font-size: 12px; color: var(--accent); }
.mon-del { border: none; background: transparent; color: var(--text-faint); cursor: pointer; padding: 3px; }
.mon-del:hover { color: var(--pink); }
.hint-empty { color: var(--text-faint); font-size: 12px; padding: 8px 0; }

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
.d-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px 16px; }
.d-foot button { padding: 8px 18px; border-radius: var(--radius-sm); font-size: 13px; cursor: pointer; }
.d-foot .cancel { background: transparent; border: 1px solid var(--text-faint); color: var(--text-faint); }
.d-foot .confirm { background: var(--accent); border: none; color: var(--bg-base); font-weight: 600; }
</style>
