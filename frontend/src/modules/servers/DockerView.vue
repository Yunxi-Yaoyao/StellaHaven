<script setup lang="ts">
// Docker 独立面板（类比 1Panel 一期）：节点选择 → 容器竖向卡片（状态/镜像/端口/操作）
// + 日志查看（tail 150）+ 配置查看（inspect 摘要）。全部竖向布局，移动端不横拉。
// 惰性缓存：打开先读最近一次扫描快照，超过 10 分钟自动后台重扫。
import { computed, onMounted, ref, watch } from "vue";
import {
  listNodes, latestNetTask, scanDocker, getNetTask, ctlDocker, dockerLogs, dockerInspect,
  type NetTask, type Node,
} from "../../api/servers";
import { toast } from "../../composables/useToast";
import Dropdown from "../../shell/Dropdown.vue";
import Icon from "../../shell/Icon.vue";

interface DockerContainer {
  id: string; name: string; image: string; status: string; state: string; ports: string; created: string;
}

const CACHE_TTL = 10 * 60 * 1000; // 10 分钟

const nodes = ref<Node[]>([]);
const nodeId = ref<number | null>(null);
const containers = ref<DockerContainer[]>([]);
const scannedAt = ref<string>("");   // 快照时间
const loading = ref(false);          // 后台重扫中
const busy = ref<Record<string, boolean>>({});

// 日志/配置浮层
const logOpen = ref(false);
const logTitle = ref("");
const logText = ref("");
const logLoading = ref(false);
const inspOpen = ref(false);
const inspTitle = ref("");
const inspData = ref<Record<string, any> | null>(null);
const inspLoading = ref(false);

const dockerNodes = computed(() =>
  nodes.value.filter((n) => (n.components as any)?.docker?.installed === true));

async function refreshNodes() {
  nodes.value = await listNodes();
  if (!nodeId.value && dockerNodes.value.length) nodeId.value = dockerNodes.value[0].id;
  if (nodeId.value && !dockerNodes.value.some((n) => n.id === nodeId.value) && dockerNodes.value.length)
    nodeId.value = dockerNodes.value[0].id;
}

async function pollTask(tid: number, timeoutMs = 40000): Promise<NetTask | null> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const t = await getNetTask(tid);
    if (t.status === "done" || t.status === "failed") return t;
    await new Promise((r) => setTimeout(r, 2000));
  }
  return null;
}

/** 惰性加载：有快照先看快照，过期/没有就后台重扫 */
async function loadContainers(force = false) {
  if (!nodeId.value) return;
  loading.value = true;
  try {
    if (!force) {
      const latest = await latestNetTask(nodeId.value, "docker_scan");
      const rj = latest?.result_json as any;
      if (latest && rj?.containers) {
        containers.value = rj.containers;
        scannedAt.value = latest.created_at;
        const age = Date.now() - new Date(latest.created_at).getTime();
        if (age < CACHE_TTL) { loading.value = false; return; } // 新鲜，直接用
        // 过期：显示旧数据，后台重扫
      }
    }
    const t = await scanDocker(nodeId.value);
    const cur = await pollTask(t.id);
    const rj = cur?.result_json as any;
    if (cur?.status === "done" && rj?.containers) {
      containers.value = rj.containers;
      scannedAt.value = cur.created_at;
    } else if (cur?.status === "failed") {
      toast("Docker 扫描失败喵~");
    }
  } catch { toast("Docker 加载失败"); }
  loading.value = false;
}

async function ctl(ct: DockerContainer, action: "start" | "stop" | "restart") {
  if (!nodeId.value || busy.value[ct.name]) return;
  busy.value[ct.name] = true;
  try {
    const t = await ctlDocker(nodeId.value, action, ct.name);
    const cur = await pollTask(t.id, 70000);
    if (cur?.status === "done") {
      toast(`${ct.name} ${action === "start" ? "已启动" : action === "stop" ? "已停止" : "已重启"}喵~`);
      await loadContainers(true);
    } else {
      toast(`${action} 失败：${(cur?.result_json as any)?.error || "超时"}`);
    }
  } catch { toast("操作下发失败"); }
  busy.value[ct.name] = false;
}

async function viewLogs(ct: DockerContainer) {
  if (!nodeId.value) return;
  logOpen.value = true; logLoading.value = true; logTitle.value = ct.name; logText.value = "";
  try {
    const t = await dockerLogs(nodeId.value, ct.name, 150);
    const cur = await pollTask(t.id);
    const rj = cur?.result_json as any;
    logText.value = cur?.status === "done" ? (rj?.lines || "（无日志）") : `读取失败：${rj?.error || "超时"}`;
  } catch { logText.value = "读取失败"; }
  logLoading.value = false;
}

async function viewInspect(ct: DockerContainer) {
  if (!nodeId.value) return;
  inspOpen.value = true; inspLoading.value = true; inspTitle.value = ct.name; inspData.value = null;
  try {
    const t = await dockerInspect(nodeId.value, ct.name);
    const cur = await pollTask(t.id);
    const rj = cur?.result_json as any;
    if (cur?.status === "done" && rj && !rj.error) inspData.value = rj;
    else inspData.value = { error: rj?.error || "读取超时" };
  } catch { inspData.value = { error: "读取失败" }; }
  inspLoading.value = false;
}

const stateLabel = (s: string) => s === "running" ? "运行中" : s === "exited" ? "已退出" : s;
const fmtTime = (iso: string) => iso ? new Date(iso).toLocaleString("zh-CN", { hour12: false }) : "";

onMounted(async () => { await refreshNodes(); });
watch(nodeId, () => { containers.value = []; scannedAt.value = ""; loadContainers(); });
</script>

<template>
  <div class="dk-view">
    <div class="dk-head">
      <h2 class="dk-title">Docker</h2>
      <div class="dk-head-right">
        <Dropdown
          v-if="dockerNodes.length"
          v-model="nodeId"
          :options="dockerNodes.map((n) => ({ value: n.id, label: n.name }))"
        />
        <button class="ghost-btn" :disabled="loading" @click="loadContainers(true)">
          {{ loading ? "扫描中…" : "刷新" }}
        </button>
      </div>
    </div>
    <div v-if="scannedAt" class="dk-meta">数据来自 {{ fmtTime(scannedAt) }}{{ loading ? " · 更新中…" : "" }}</div>

    <div v-if="!dockerNodes.length" class="dk-empty">没有安装 Docker 的节点（可在服务器页组件区代装）</div>
    <div v-else-if="!containers.length && !loading" class="dk-empty">没有容器，或扫描还没数据</div>

    <!-- 容器竖向卡片：信息全部竖排，窄屏不横拉 -->
    <div class="dk-cards">
      <div v-for="ct in containers" :key="ct.id" class="dk-card">
        <div class="dk-card-head">
          <span class="dk-state" :class="ct.state" />
          <span class="dk-name">{{ ct.name }}</span>
          <span class="dk-state-text" :class="ct.state">{{ stateLabel(ct.state) }}</span>
        </div>
        <div class="dk-kv"><span class="k">镜像</span><span class="v mono">{{ ct.image }}</span></div>
        <div v-if="ct.ports" class="dk-kv"><span class="k">端口</span><span class="v mono">{{ ct.ports }}</span></div>
        <div class="dk-kv"><span class="k">状态</span><span class="v">{{ ct.status }}</span></div>
        <div class="dk-actions">
          <button class="ghost-btn sm" @click="viewLogs(ct)"><Icon name="text" :size="12" /> 日志</button>
          <button class="ghost-btn sm" @click="viewInspect(ct)"><Icon name="eye" :size="12" /> 配置</button>
          <template v-if="ct.state === 'running'">
            <button class="ghost-btn sm" :disabled="busy[ct.name]" @click="ctl(ct, 'restart')">重启</button>
            <button class="ghost-btn sm danger" :disabled="busy[ct.name]" @click="ctl(ct, 'stop')">停止</button>
          </template>
          <button v-else class="ghost-btn sm" :disabled="busy[ct.name]" @click="ctl(ct, 'start')">启动</button>
        </div>
      </div>
    </div>

    <!-- 日志浮层 -->
    <div v-if="logOpen" class="dk-mask" @click.self="logOpen = false">
      <div class="dk-modal">
        <div class="dk-modal-head">
          <span>日志 · {{ logTitle }}</span>
          <button class="ghost-btn sm" @click="logOpen = false">关闭</button>
        </div>
        <pre class="dk-log">{{ logLoading ? "读取中…" : logText }}</pre>
      </div>
    </div>

    <!-- 配置浮层（inspect 摘要，竖向键值） -->
    <div v-if="inspOpen" class="dk-mask" @click.self="inspOpen = false">
      <div class="dk-modal">
        <div class="dk-modal-head">
          <span>配置 · {{ inspTitle }}</span>
          <button class="ghost-btn sm" @click="inspOpen = false">关闭</button>
        </div>
        <div v-if="inspLoading" class="dk-empty">读取中…</div>
        <div v-else-if="inspData?.error" class="dk-empty">{{ inspData.error }}</div>
        <div v-else-if="inspData" class="dk-insp">
          <div class="dk-kv"><span class="k">镜像</span><span class="v mono">{{ inspData.image }}</span></div>
          <div class="dk-kv"><span class="k">状态</span><span class="v">{{ inspData.state }}</span></div>
          <div class="dk-kv"><span class="k">创建</span><span class="v">{{ fmtTime(inspData.created) }}</span></div>
          <div v-if="inspData.cmd" class="dk-kv"><span class="k">命令</span><span class="v mono">{{ inspData.cmd }}</span></div>
          <div v-if="inspData.entrypoint" class="dk-kv"><span class="k">入口</span><span class="v mono">{{ inspData.entrypoint }}</span></div>
          <div class="dk-kv"><span class="k">重启策略</span><span class="v">{{ inspData.restart_policy || "默认" }}</span></div>
          <div v-if="inspData.ports?.length" class="dk-kv">
            <span class="k">端口映射</span>
            <span class="v mono"><span v-for="(pt, i) in inspData.ports" :key="i" class="dk-tag">{{ pt.host }} → {{ pt.container }}</span></span>
          </div>
          <div v-if="inspData.mounts?.length" class="dk-kv">
            <span class="k">挂载</span>
            <span class="v mono"><span v-for="(m, i) in inspData.mounts" :key="i" class="dk-tag">{{ m.source }} → {{ m.target }}{{ m.rw ? "" : "（只读）" }}</span></span>
          </div>
          <div v-if="inspData.networks?.length" class="dk-kv"><span class="k">网络</span><span class="v">{{ inspData.networks.join("、") }}</span></div>
          <div v-if="inspData.env?.length" class="dk-kv env">
            <span class="k">环境变量</span>
            <span class="v mono env-list"><span v-for="(e, i) in inspData.env" :key="i">{{ e }}</span></span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dk-view { padding: 18px 20px; overflow-y: auto; width: 100%; }
.dk-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.dk-title { font-size: 18px; font-weight: 600; color: var(--text-hi); }
.dk-head-right { display: flex; align-items: center; gap: 8px; }
.dk-meta { font-size: 11.5px; color: var(--text-faint); margin: 6px 0 12px; }
.dk-empty { color: var(--text-faint); font-size: 12.5px; padding: 24px 0; text-align: center; }

.dk-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.dk-card {
  background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius); padding: 12px 14px; display: flex; flex-direction: column; gap: 6px;
}
.dk-card-head { display: flex; align-items: center; gap: 8px; }
.dk-state { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); flex-shrink: 0; }
.dk-state.running { background: #3ddc84; }
.dk-state.exited { background: #ff5d6c; }
.dk-name { font-size: 14px; font-weight: 600; color: var(--text-hi); word-break: break-all; }
.dk-state-text { margin-left: auto; font-size: 11px; color: var(--text-faint); flex-shrink: 0; }
.dk-state-text.running { color: #3ddc84; }
.dk-state-text.exited { color: #ff5d6c; }
.dk-kv { display: flex; gap: 8px; font-size: 12px; align-items: baseline; }
.dk-kv .k { color: var(--text-faint); flex-shrink: 0; min-width: 52px; }
.dk-kv .v { color: var(--text-lo); word-break: break-all; min-width: 0; }
.mono { font-family: var(--font-mono, monospace); font-size: 11.5px; }
.dk-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
.dk-actions .ghost-btn { display: inline-flex; align-items: center; gap: 4px; }

.dk-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 90; display: flex; align-items: center; justify-content: center; padding: 16px; }
.dk-modal {
  width: 680px; max-width: 100%; max-height: 84vh; overflow: hidden;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.09); border-radius: 14px;
  display: flex; flex-direction: column;
}
.dk-modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.06);
  color: var(--text-hi); font-size: 13.5px; font-weight: 600;
}
.dk-log {
  margin: 0; padding: 12px 16px; overflow-y: auto; font-size: 11.5px; line-height: 1.6;
  font-family: var(--font-mono, monospace); color: var(--text-lo); white-space: pre-wrap; word-break: break-all;
}
.dk-insp { padding: 12px 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.dk-tag {
  display: block; background: rgba(255,255,255,0.04); border-radius: 5px;
  padding: 2px 8px; margin: 2px 0; word-break: break-all;
}
.env-list { display: flex; flex-direction: column; gap: 2px; max-height: 200px; overflow-y: auto; }
.env-list span { word-break: break-all; }

@media (max-width: 768px) {
  .dk-view { padding: 12px; }
  .dk-cards { grid-template-columns: 1fr; }
  .dk-modal { max-height: 90vh; }
}
</style>
