<script setup lang="ts">
// OpenList 安装浮窗：拉镜像（进度条）→ 配存储目录（增删改）→ 创建容器
import { ref, computed, onMounted, onUnmounted } from "vue";
import {
  getDriveStatus, pullImage, getPullProgress, installContainer,
  checkUpdate, pullLatest, removeImage, setProxy,
  type StorageItem, type PullProgress, type CheckUpdateResult, type DriveSettings,
} from "../../api/drive";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";
import Dropdown from "../../shell/Dropdown.vue";

const emit = defineEmits<{ done: []; cancel: [] }>();

const pull = ref<PullProgress>({ status: "idle", layers: [], current: 0, total: 0, percent: 0, error: null });
const storages = ref<StorageItem[]>([]);
const installing = ref(false);
const installed = ref(false);
const checking = ref(false);
const updating = ref(false);
const update = ref<CheckUpdateResult | null>(null);
const confirmRemoveImage = ref(false);
const removingImage = ref(false);
const proxyAddr = ref("");
const applyingProxy = ref(false);
const proxyOpen = ref(false);
const settingsOpen = ref(false);
const imageVersion = ref<string | null>(null);
const settings = ref<DriveSettings>({
  port: 5244, mem_limit: "", cpus: "", tz: "Asia/Shanghai", restart_policy: "unless-stopped",
});
const restartOptions = [
  { value: "unless-stopped", label: "unless-stopped", desc: "推荐" },
  { value: "always", label: "always" },
  { value: "on-failure", label: "on-failure" },
  { value: "no", label: "no（不自动重启）" },
];

let pollTimer: ReturnType<typeof setInterval> | null = null;

const imageReady = computed(() => pull.value.status === "done");
const pullLabel = computed(() => {
  switch (pull.value.status) {
    case "pulling": return "拉取镜像中";
    case "done": return "镜像已就绪";
    case "failed": return "拉取失败";
    default: return "准备拉取";
  }
});

function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

async function refreshImageVersion() {
  try {
    const st = await getDriveStatus();
    imageVersion.value = st.image_version;
  } catch { /* 静默 */ }
}

async function startPull() {
  try {
    await pullImage();
    pollTimer = setInterval(async () => {
      try {
        const p = await getPullProgress();
        pull.value = p;
        if (p.status === "done" || p.status === "failed") {
          stopPoll();
          if (p.status === "done") await refreshImageVersion();
        }
      } catch { /* 静默 */ }
    }, 700);
  } catch {
    toast("拉取镜像失败喵~");
  }
}

function addStorage() {
  storages.value.push({ name: "", host_path: "", mount_path: "/data/" });
}
function removeStorage(i: number) {
  storages.value.splice(i, 1);
}

async function doCheckUpdate() {
  if (checking.value) return;
  checking.value = true;
  update.value = null;
  try {
    update.value = await checkUpdate();
  } catch (e: any) {
    toast("检测失败：" + (e?.detail || ""));
  } finally {
    checking.value = false;
  }
}

async function doPullLatest() {
  if (updating.value) return;
  updating.value = true;
  try {
    await pullLatest();
    update.value = null;
    pull.value = { ...pull.value, status: "done", percent: 100 };
    toast("已拉取最新镜像喵~");
  } catch (e: any) {
    toast("更新失败：" + (e?.detail || ""));
  } finally {
    updating.value = false;
  }
}

async function doRemoveImage() {
  if (removingImage.value) return;
  removingImage.value = true;
  try {
    await removeImage();
    confirmRemoveImage.value = false;
    pull.value = { ...pull.value, status: "idle", percent: 0 };
    toast("镜像已删除喵~");
  } catch (e: any) {
    toast("删除失败：" + (e?.detail || ""));
  } finally {
    removingImage.value = false;
  }
}

async function doApplyProxy() {
  if (applyingProxy.value) return;
  applyingProxy.value = true;
  try {
    await setProxy(proxyAddr.value.trim());
    toast(proxyAddr.value.trim() ? "代理已应用喵~" : "已取消代理，走宿主机默认喵~");
  } catch (e: any) {
    toast("应用代理失败：" + (e?.detail || ""));
  } finally {
    applyingProxy.value = false;
  }
}

async function doInstall() {
  if (installing.value) return;
  const valid = storages.value
    .map((s) => ({ name: s.name.trim(), host_path: s.host_path.trim(), mount_path: s.mount_path.trim() }))
    .filter((s) => s.host_path && s.mount_path);
  if (!valid.length) { toast("至少配置一个存储目录喵~"); return; }
  installing.value = true;
  try {
    await installContainer(valid, { ...settings.value, port: Number(settings.value.port) || 5244 });
    installed.value = true;
    toast("OpenList 安装完成喵~");
  } catch (e: any) {
    toast("安装失败：" + (e?.detail || "请查看后端日志"));
  } finally {
    installing.value = false;
  }
}

onMounted(async () => {
  try {
    const st = await getDriveStatus();
    // 回显当前代理配置
    proxyAddr.value = st.proxy || "";
    // 存储：已有配置回显，否则用默认一条
    storages.value = st.storages.length
      ? st.storages.map((s) => ({ ...s }))
      : [{ ...st.default_storage }];
    // 高级设置：回显已保存的
    settings.value = { ...settings.value, ...st.settings };
    // 镜像：已就绪 / 正在拉（接上轮询）/ 未拉（开拉）
    if (st.image_exists || st.pull.status === "done") {
      pull.value = { ...pull.value, status: "done", percent: 100 };
      imageVersion.value = st.image_version;
    } else if (st.pull.status === "pulling") {
      pull.value = st.pull;
      pollTimer = setInterval(async () => {
        try {
          const p = await getPullProgress();
          pull.value = p;
          if (p.status === "done" || p.status === "failed") {
            stopPoll();
            if (p.status === "done") await refreshImageVersion();
          }
        } catch { /* 静默 */ }
      }, 700);
    } else {
      await startPull();
    }
  } catch {
    toast("加载失败喵~");
  }
});

onUnmounted(stopPoll);
</script>

<template>
  <div class="mask" @click.self="emit('cancel')">
    <div class="dialog">
      <div class="head">
        <span>安装 OpenList 网盘</span>
        <button class="x" @click="emit('cancel')"><Icon name="plus" :size="14" class="rot" /></button>
      </div>

      <div class="body">
        <div v-if="installed" class="done-block">
          <div class="done-main">
            <span class="done-title">OpenList 安装完成</span>
            <span class="done-tip">已自动配置免登录——打开网盘时由 Stella 代签，无需记密码喵~</span>
          </div>
        </div>
        <!-- 镜像 -->
        <div class="sec">
          <div class="sec-head">
            <span class="label">镜像</span>
            <span class="pull-label" :class="pull.status">{{ pullLabel }}</span>
          </div>
          <button class="proxy-toggle" type="button" @click="proxyOpen = !proxyOpen">
            <Icon name="chevron" :size="12" :class="{ rot: proxyOpen }" />
            <span>代理设置</span>
            <span class="proxy-hint">拉镜像走梯子可在此配置</span>
          </button>
          <div v-if="proxyOpen" class="proxy-box">
            <div class="proxy-row">
              <input v-model="proxyAddr" class="in" type="text" placeholder="如 http://127.0.0.1:1081（留空走宿主机默认）" />
              <button class="btn ghost sm" :disabled="applyingProxy" @click="doApplyProxy">
                {{ applyingProxy ? '应用中…' : '应用代理' }}
              </button>
            </div>
            <p class="hint">留空走宿主机默认网络；拉镜像被墙卡住时，填本地梯子的 HTTP 代理地址</p>
          </div>
          <div class="bar">
            <div class="fill" :class="{ done: imageReady }" :style="{ width: pull.percent + '%' }"></div>
          </div>
          <div class="pull-meta">
            <span v-if="pull.status === 'pulling'">{{ pull.percent.toFixed(1) }}%</span>
            <span v-else-if="pull.status === 'done'" class="ver">openlistteam/openlist:{{ imageVersion || '…' }}</span>
            <span v-else-if="pull.status === 'failed'" class="err">{{ pull.error }}</span>
            <span v-else>等待中</span>
            <button v-if="pull.status === 'failed'" class="link" @click="startPull">重试</button>
          </div>
          <!-- 镜像管理：检查更新 / 更新 / 删除 -->
          <div class="image-acts">
            <button class="link" :disabled="checking" @click="doCheckUpdate">
              {{ checking ? '检测中…' : '检查更新' }}
            </button>
            <button v-if="update && update.update_available" class="link" :disabled="updating" @click="doPullLatest">
              {{ updating ? '更新中…' : `更新到 ${update.latest_version}` }}
            </button>
            <button v-if="imageReady" class="link danger" @click="confirmRemoveImage = true">删除镜像</button>
          </div>
          <div v-if="update" class="update-msg" :class="update.update_available ? 'has' : ''">
            <template v-if="update.error">检测失败：{{ update.error }}</template>
            <template v-else-if="update.update_available">
              发现新版本 {{ update.latest_version }}（当前 {{ update.local_version }}）
            </template>
            <template v-else>已是最新版本（{{ update.local_version }}）</template>
          </div>
          <div v-if="confirmRemoveImage" class="confirm">
            <span class="confirm-txt">删除已拉取的镜像？</span>
            <div class="confirm-acts">
              <button class="btn danger sm" :disabled="removingImage" @click="doRemoveImage">确认删除</button>
              <button class="btn ghost sm" @click="confirmRemoveImage = false">取消</button>
            </div>
          </div>
        </div>

        <!-- 存储目录 -->
        <div class="sec">
          <div class="sec-head">
            <span class="label">存储目录</span>
            <button class="link" @click="addStorage"><Icon name="plus" :size="13" /> 添加</button>
          </div>
          <p class="hint">宿主目录挂进容器，装好后在 OpenList 里填「容器内路径」即可访问</p>

          <div class="storage-list">
            <div v-for="(s, i) in storages" :key="i" class="storage-row">
              <input v-model="s.name" class="in name" placeholder="名称" />
              <input v-model="s.host_path" class="in host" placeholder="宿主目录（绝对路径）" />
              <input v-model="s.mount_path" class="in mount" placeholder="容器内路径" />
              <button class="del" @click="removeStorage(i)"><Icon name="trash" :size="14" /></button>
            </div>
            <p v-if="!storages.length" class="empty">还没有存储目录，点「添加」新建喵~</p>
          </div>
        </div>

        <!-- 高级设置 -->
        <div class="sec">
          <button class="proxy-toggle" type="button" @click="settingsOpen = !settingsOpen">
            <Icon name="chevron" :size="12" :class="{ rot: settingsOpen }" />
            <span>高级设置</span>
            <span class="proxy-hint">端口 / 内存 / CPU / 时区 / 重启策略</span>
          </button>
          <div v-if="settingsOpen" class="settings-box">
            <div class="settings-grid">
              <label class="field">
                <span class="f-label">端口</span>
                <input v-model.number="settings.port" class="in" type="number" placeholder="5244" />
              </label>
              <label class="field">
                <span class="f-label">内存限制</span>
                <input v-model="settings.mem_limit" class="in" type="text" placeholder="如 512m，留空不限" />
              </label>
              <label class="field">
                <span class="f-label">CPU 核数</span>
                <input v-model="settings.cpus" class="in" type="text" placeholder="如 1.5，留空不限" />
              </label>
              <label class="field">
                <span class="f-label">时区</span>
                <input v-model="settings.tz" class="in" type="text" placeholder="Asia/Shanghai" />
              </label>
              <label class="field">
                <span class="f-label">重启策略</span>
                <Dropdown v-model="settings.restart_policy" :options="restartOptions" />
              </label>
            </div>
            <p class="hint">默认值通常够用；改动会随重装/更新沿用喵~</p>
          </div>
        </div>
      </div>

      <div class="foot">
        <button class="btn ghost" @click="emit('cancel')">取消</button>
        <button v-if="!installed" class="btn primary" :disabled="!imageReady || installing" @click="doInstall">
          {{ installing ? "安装中…" : "安装" }}
        </button>
        <button v-else class="btn primary" @click="emit('done')">完成</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid; place-items: center;
  z-index: 100;
}
.dialog {
  width: min(620px, calc(100vw - 32px));
  max-height: 86vh;
  display: flex; flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
}
.head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 15px 20px;
  font-size: 15px; font-weight: 600;
  border-bottom: 1px solid var(--bg-raised);
}
.x { background: none; border: none; color: var(--text-faint); cursor: pointer; padding: 4px; }
.x:hover { color: var(--text-hi); }
.rot { transform: rotate(45deg); }

.body { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 20px; }

.sec-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.label { font-size: 13px; color: var(--text-lo); }
.pull-label { font-size: 12px; color: var(--text-faint); }
.pull-label.pulling { color: var(--pink); }
.pull-label.done { color: var(--accent); }
.pull-label.failed { color: var(--pink); }

.bar {
  height: 6px; border-radius: 3px;
  background: var(--bg-raised);
  overflow: hidden;
}
.fill {
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--accent-dim), var(--pink));
  transition: width 0.3s ease;
}
.fill.done { background: var(--accent); }

.pull-meta { display: flex; align-items: center; gap: 10px; margin-top: 6px; font-size: 12px; color: var(--text-faint); }
.pull-meta .err { color: var(--pink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
.link { background: none; border: none; color: var(--accent); font-size: 12px; cursor: pointer; padding: 0; display: inline-flex; align-items: center; gap: 3px; }
.link:hover { color: var(--pink); }

.hint { font-size: 12px; color: var(--text-faint); margin-bottom: 10px; }

.storage-list { display: flex; flex-direction: column; gap: 8px; }
.storage-row {
  display: grid; grid-template-columns: 96px 1fr 128px 30px; gap: 6px; align-items: center;
}
.in {
  background: var(--bg-raised);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm);
  color: var(--text-hi);
  padding: 7px 10px; font-size: 12.5px;
  transition: border-color var(--transition);
}
.in:focus { outline: none; border-color: var(--accent-dim); }
.in::placeholder { color: var(--text-faint); }
.in.name { font-weight: 500; }
.in.host { font-family: var(--font-mono); font-size: 11.5px; }
.in.mount { font-family: var(--font-mono); font-size: 11.5px; }
.in.full { width: 100%; margin-top: 2px; }
.del {
  background: none; border: none; color: var(--text-faint); cursor: pointer;
  padding: 6px; border-radius: var(--radius-sm);
}
.del:hover { color: var(--pink); background: var(--bg-raised); }
.empty { font-size: 12px; color: var(--text-faint); text-align: center; padding: 12px; }

.foot {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 20px; border-top: 1px solid var(--bg-raised);
}
.btn {
  padding: 7px 20px; border-radius: var(--radius-sm);
  font-size: 13px; cursor: pointer; transition: all var(--transition);
}
.btn.ghost { background: transparent; border: 1px solid var(--text-faint); color: var(--text-lo); }
.btn.ghost:hover { color: var(--text-hi); border-color: var(--accent-dim); }
.btn.primary {
  background: var(--accent); border: 1px solid var(--accent); color: var(--bg-base); font-weight: 600;
}
.btn.primary:hover { background: #dbe4f2; }
.btn.primary:disabled { opacity: 0.4; cursor: not-allowed; }

.done-block {
  padding: 14px 16px;
  background: rgba(201, 212, 232, 0.08);
  border: 1px solid var(--accent-dim);
  border-radius: var(--radius-sm);
  margin-bottom: 4px;
}
.done-title { display: block; font-size: 14px; font-weight: 600; color: var(--text-hi); margin-bottom: 6px; }
.done-pwd { font-size: 13px; color: var(--text-lo); margin-bottom: 4px; }
.done-pwd code {
  font-family: var(--font-mono); font-size: 13px; color: var(--pink);
  background: var(--bg-base); padding: 2px 8px; border-radius: 4px; margin-left: 4px;
}
.done-tip { font-size: 11.5px; color: var(--text-faint); }

.image-acts { display: flex; align-items: center; gap: 14px; margin-top: 8px; flex-wrap: wrap; }
.link.danger { color: var(--pink); }
.link:disabled { opacity: 0.4; cursor: not-allowed; }
.update-msg { font-size: 12px; color: var(--text-faint); margin-top: 6px; }
.update-msg.has { color: var(--pink); }
.confirm {
  margin-top: 8px; padding: 10px 12px;
  background: var(--bg-raised); border-radius: var(--radius-sm);
  display: flex; flex-direction: column; gap: 8px;
}
.confirm-txt { font-size: 12px; color: var(--text-lo); }
.confirm-acts { display: flex; gap: 8px; }
.btn.sm { padding: 5px 12px; font-size: 12px; }
.btn.danger { background: transparent; border: 1px solid var(--pink); color: var(--pink); }
.btn.danger:hover { background: rgba(232, 160, 191, 0.12); }
.proxy-toggle {
  display: flex; align-items: center; gap: 6px;
  background: none; border: none; cursor: pointer;
  color: var(--text-faint); font-size: 12px; padding: 4px 0;
  transition: color var(--transition);
}
.proxy-toggle:hover { color: var(--text-lo); }
.proxy-toggle :deep(.icon) { transition: transform 0.2s; }
.proxy-toggle .rot { transform: rotate(90deg); }
.proxy-hint { color: var(--text-faint); font-size: 11.5px; }
.proxy-box {
  margin-top: 6px; padding: 10px;
  background: var(--bg-raised); border-radius: var(--radius-sm);
}
.proxy-row { display: flex; align-items: center; gap: 8px; }
.proxy-row .in { flex: 1; }
.proxy-box .hint { font-size: 11.5px; color: var(--text-faint); margin-top: 6px; }
.ver { font-family: var(--font-mono); font-size: 12px; color: var(--text-hi); }

.settings-box {
  margin-top: 6px; padding: 12px;
  background: var(--bg-raised); border-radius: var(--radius-sm);
}
.settings-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 14px;
}
.field { display: flex; flex-direction: column; gap: 5px; }
.f-label { font-size: 11.5px; color: var(--text-lo); }
.settings-box .hint { font-size: 11.5px; color: var(--text-faint); margin-top: 10px; }
.settings-box .in { width: 100%; }
</style>
