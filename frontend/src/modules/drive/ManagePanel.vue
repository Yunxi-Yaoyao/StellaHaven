<script setup lang="ts">
// OpenList 管理浮窗：Docker 状态 + 镜像（检测更新/删除）+ 容器（启动/停止/重启/卸载）
import { ref, onMounted } from "vue";
import {
  getDriveStatus, startContainer, stopContainer, restartContainer,
  uninstallContainer, removeImage, checkUpdate, updateContainer,
  type DriveStatus, type CheckUpdateResult,
} from "../../api/drive";
import { toast } from "../../composables/useToast";
import Icon from "../../shell/Icon.vue";

const emit = defineEmits<{ done: []; cancel: [] }>();

const status = ref<DriveStatus | null>(null);
const loading = ref(true);
const busy = ref<string | null>(null);
const update = ref<CheckUpdateResult | null>(null);
const checking = ref(false);
const updating = ref(false);
const confirmUninstall = ref(false);
const confirmRemoveImage = ref(false);

async function refresh() {
  try { status.value = await getDriveStatus(); } catch { /* 静默 */ }
  loading.value = false;
}
onMounted(refresh);

async function act(name: string, fn: () => Promise<DriveStatus>, okMsg: string) {
  if (busy.value) return;
  busy.value = name;
  try {
    status.value = await fn();
    toast(okMsg);
  } catch (e: any) {
    toast("操作失败：" + (e?.detail || "请查看后端日志"));
  } finally {
    busy.value = null;
  }
}

function doStart() { act("start", startContainer, "已启动喵~"); }
function doStop() { act("stop", stopContainer, "已停止喵~"); }
function doRestart() { act("restart", restartContainer, "已重启喵~"); }

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

async function doUpdate() {
  if (updating.value) return;
  updating.value = true;
  try {
    status.value = await updateContainer();
    update.value = null;
    toast("已更新到最新版喵~");
  } catch (e: any) {
    toast("更新失败：" + (e?.detail || ""));
  } finally {
    updating.value = false;
  }
}

async function doRemoveImage() {
  if (busy.value) return;
  busy.value = "remove-image";
  try {
    status.value = await removeImage();
    confirmRemoveImage.value = false;
    toast("镜像已删除喵~");
    emit("done");
  } catch (e: any) {
    toast("删除失败：" + (e?.detail || ""));
  } finally {
    busy.value = null;
  }
}

async function doUninstall() {
  if (busy.value) return;
  busy.value = "uninstall";
  try {
    status.value = await uninstallContainer(false);
    confirmUninstall.value = false;
    toast("已卸载喵~");
    emit("done");
  } catch (e: any) {
    toast("卸载失败：" + (e?.detail || ""));
  } finally {
    busy.value = null;
  }
}

function openExternal() {
  window.open(`http://${location.hostname}:5244`, "_blank");
}
</script>

<template>
  <div class="mask" @click.self="emit('cancel')">
    <div class="dialog">
      <div class="head">
        <span>管理 OpenList 网盘</span>
        <button class="x" @click="emit('cancel')"><Icon name="plus" :size="14" class="rot" /></button>
      </div>

      <div class="body" v-if="loading">加载中…</div>
      <div class="body" v-else-if="status">
        <!-- Docker -->
        <div class="sec">
          <div class="sec-head"><span class="label">Docker 环境</span></div>
          <div class="row">
            <span class="state" :class="status.docker.installed ? 'ok' : 'bad'">
              <span class="dot"></span>
              {{ status.docker.installed ? `v${status.docker.version} · ${status.docker.running ? '运行中' : '未运行'}` : '未安装' }}
            </span>
          </div>
        </div>

        <!-- 镜像 -->
        <div class="sec">
          <div class="sec-head"><span class="label">OpenList 镜像</span></div>
          <div class="row">
            <span class="ver">{{ status.image_version || '未拉取' }}</span>
            <div class="acts">
              <button class="btn ghost sm" :disabled="checking" @click="doCheckUpdate">
                {{ checking ? '检测中…' : '检测更新' }}
              </button>
              <button v-if="status.image_exists" class="btn danger sm" @click="confirmRemoveImage = true">删除镜像</button>
            </div>
          </div>
          <div v-if="update" class="update-msg" :class="update.update_available ? 'has' : ''">
            <template v-if="update.error">检测失败：{{ update.error }}</template>
            <template v-else-if="update.update_available">
              <span>发现新版本 {{ update.latest_version }}（当前 {{ update.local_version }}）</span>
              <button class="btn primary sm" :disabled="updating" @click="doUpdate">
                {{ updating ? '更新中…' : `更新到 ${update.latest_version}` }}
              </button>
            </template>
            <template v-else>已是最新版本（{{ update.local_version }}）</template>
          </div>
          <div v-if="confirmRemoveImage" class="confirm">
            <span class="confirm-txt">删除镜像会同时移除容器（若在运行），确定？</span>
            <div class="confirm-acts">
              <button class="btn danger sm" :disabled="!!busy" @click="doRemoveImage">确认删除</button>
              <button class="btn ghost sm" @click="confirmRemoveImage = false">取消</button>
            </div>
          </div>
        </div>

        <!-- 容器 -->
        <div class="sec">
          <div class="sec-head"><span class="label">OpenList 容器</span></div>
          <div class="row">
            <span class="state" :class="status.container_running ? 'ok' : 'bad'">
              <span class="dot"></span>
              {{ status.container_running ? '运行中' : (status.container_exists ? '已停止' : '未安装') }}
            </span>
            <div class="acts" v-if="status.container_exists">
              <button v-if="!status.container_running" class="btn primary sm" :disabled="!!busy" @click="doStart">启动</button>
              <button v-else class="btn ghost sm" :disabled="!!busy" @click="doStop">停止</button>
              <button class="btn ghost sm" :disabled="!!busy" @click="doRestart">重启</button>
              <button class="btn danger sm" @click="confirmUninstall = true">卸载</button>
              <button class="btn ghost sm" @click="openExternal"><Icon name="move" :size="12" /> 新标签打开</button>
            </div>
          </div>
          <div v-if="confirmUninstall" class="confirm">
            <span class="confirm-txt">卸载容器（保留镜像与数据，可重新安装）？</span>
            <div class="confirm-acts">
              <button class="btn danger sm" :disabled="!!busy" @click="doUninstall">确认卸载</button>
              <button class="btn ghost sm" @click="confirmUninstall = false">取消</button>
            </div>
          </div>
        </div>
      </div>

      <div class="foot">
        <button class="btn ghost" @click="emit('cancel')">关闭</button>
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
  width: min(560px, calc(100vw - 32px));
  max-height: 86vh;
  display: flex; flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
}
.head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 15px 20px; font-size: 15px; font-weight: 600;
  border-bottom: 1px solid var(--bg-raised);
}
.x { background: none; border: none; color: var(--text-faint); cursor: pointer; padding: 4px; }
.x:hover { color: var(--text-hi); }
.rot { transform: rotate(45deg); }

.body { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 18px; }

.sec-head { margin-bottom: 8px; }
.label { font-size: 13px; color: var(--text-lo); }

.row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.state { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.state .dot { width: 7px; height: 7px; border-radius: 50%; }
.state.ok { color: var(--accent); }
.state.ok .dot { background: var(--accent); }
.state.bad { color: var(--text-lo); }
.state.bad .dot { background: var(--text-faint); }
.ver { font-family: var(--font-mono); font-size: 12.5px; color: var(--text-hi); }

.acts { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 14px; border-radius: var(--radius-sm);
  font-size: 12.5px; cursor: pointer; transition: all var(--transition);
  border: 1px solid transparent;
}
.btn.sm { padding: 5px 12px; font-size: 12px; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--bg-base); font-weight: 600; }
.btn.primary:hover { background: #dbe4f2; }
.btn.ghost { background: transparent; border-color: var(--text-faint); color: var(--text-lo); }
.btn.ghost:hover { color: var(--text-hi); border-color: var(--accent-dim); }
.btn.danger { background: transparent; border-color: var(--pink); color: var(--pink); }
.btn.danger:hover { background: rgba(232, 160, 191, 0.12); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }

.update-msg { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; color: var(--text-faint); margin-top: 6px; }
.update-msg.has { color: var(--pink); }

.confirm {
  margin-top: 8px; padding: 10px 12px;
  background: var(--bg-raised); border-radius: var(--radius-sm);
  display: flex; flex-direction: column; gap: 8px;
}
.confirm-txt { font-size: 12px; color: var(--text-lo); }
.confirm-acts { display: flex; gap: 8px; }

.foot { display: flex; justify-content: flex-end; padding: 14px 20px; border-top: 1px solid var(--bg-raised); }
</style>
