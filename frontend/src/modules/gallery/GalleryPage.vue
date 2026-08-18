<script setup lang="ts">
// 图库页三态（参考网盘页，但纯色固定，无背景切换/透明化/注入）：
//   无 docker → 中心「Docker 检查」；有 docker 无 immich_server 容器 → 中心「未检测到 Immich」；
//   已装 → Immich iframe + 右上角「管理」浮窗（启动/停止/重启）
// iframe src 走 Stella /gallery/connect（第一方代签 OIDC code 再 302 到 Immich），
// 解决 iframe 第三方上下文里 Stella SameSite=Lax cookie 不发、autoLaunch 认不出登录态的问题。
import { ref, onMounted } from "vue";
import Icon from "../../shell/Icon.vue";
import { toast } from "../../composables/useToast";
import {
  getGalleryStatus, startContainer, stopContainer, restartContainer,
  type GalleryStatus,
} from "../../api/gallery";

const IMMICH_URL = "/gallery/connect";

const status = ref<GalleryStatus | null>(null);
const loading = ref(true);
const manageOpen = ref(false);
const busy = ref<"" | "start" | "stop" | "restart">("");
const frameReady = ref(false);

function onFrameLoad() {
  frameReady.value = true;
}

async function refresh() {
  try {
    status.value = await getGalleryStatus();
  } catch { /* 静默 */ }
  loading.value = false;
}
onMounted(refresh);

async function doAction(action: "start" | "stop" | "restart") {
  if (busy.value) return;
  busy.value = action;
  try {
    const fn = { start: startContainer, stop: stopContainer, restart: restartContainer }[action];
    status.value = await fn();
    const msg = { start: "已启动喵~", stop: "已停止喵~", restart: "已重启喵~" }[action];
    toast(msg);
    if (action !== "stop") frameReady.value = false;  // 重启后 iframe 重新加载再淡入
  } catch (e: any) {
    toast("操作失败：" + (e?.detail || ""));
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <div class="gallery-page">
    <!-- 已装：iframe + 右上角管理 -->
    <template v-if="status?.container_exists">
      <div class="frame-bar">
        <div class="frame-title">
          <Icon name="image" :size="16" />
          <span>图库</span>
          <span class="chip" :class="status.container_running ? 'ok' : 'bad'">
            <span class="dot"></span>{{ status.container_running ? '运行中' : '已停止' }}
          </span>
        </div>
        <div class="frame-actions">
          <button class="manage-btn" @click="manageOpen = true">
            <Icon name="settings" :size="14" /> 管理
          </button>
        </div>
      </div>
      <iframe v-if="status.container_running" class="frame" :class="{ ready: frameReady }"
              :key="String(status.container_running)" :src="IMMICH_URL" @load="onFrameLoad" />
      <div v-else class="frame-stopped">
        <Icon name="image" :size="36" />
        <p>容器已停止，点右上角「管理」启动喵~</p>
      </div>
    </template>

    <!-- 未装：中心提示 -->
    <div v-else class="center">
      <p v-if="loading" class="hint">检测中…</p>
      <template v-else-if="status && !status.docker.installed">
        <div class="center-icon"><Icon name="server" :size="40" /></div>
        <h1>Docker 环境检查</h1>
        <p class="hint">未检测到 Docker，图库需要它才能运行</p>
      </template>
      <template v-else-if="status">
        <div class="center-icon"><Icon name="image" :size="40" /></div>
        <h1>图库</h1>
        <p class="hint">未检测到 Immich 容器（immich_server）喵~</p>
      </template>
    </div>

    <!-- 管理浮窗 -->
    <div v-if="manageOpen && status" class="overlay" @click.self="manageOpen = false">
      <div class="dialog">
        <div class="head">
          <span>图库管理</span>
          <button class="x" @click="manageOpen = false"><Icon name="plus" :size="16" class="rot" /></button>
        </div>
        <div class="body">
          <div class="row">
            <span class="state" :class="status.container_running ? 'ok' : 'bad'">
              <span class="dot"></span>{{ status.container_running ? '运行中' : '已停止' }}
            </span>
            <div class="acts">
              <button v-if="!status.container_running" class="btn primary sm"
                      :disabled="!!busy" @click="doAction('start')">
                {{ busy === 'start' ? '启动中…' : '启动' }}
              </button>
              <button v-if="status.container_running" class="btn ghost sm"
                      :disabled="!!busy" @click="doAction('restart')">
                {{ busy === 'restart' ? '重启中…' : '重启' }}
              </button>
              <button v-if="status.container_running" class="btn danger sm"
                      :disabled="!!busy" @click="doAction('stop')">
                {{ busy === 'stop' ? '停止中…' : '停止' }}
              </button>
            </div>
          </div>
          <p class="label">Immich 由 docker compose 部署（/opt/immich），这里只管理主容器 immich_server 的启停喵~</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gallery-page {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  background-color: #14171f; /* 纯色固定 */
}

/* ── 顶栏 ── */
.frame-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px;
  background: var(--bg-panel);
  flex-shrink: 0;
  border-radius: 12px 12px 0 0;
  border: 1px solid rgba(201, 212, 232, 0.16);
  border-bottom: none;
  box-sizing: border-box;
}
.frame-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11.5px; font-weight: 500; padding: 2px 9px; border-radius: 999px;
}
.chip .dot { width: 6px; height: 6px; border-radius: 50%; }
.chip.ok { color: var(--accent); background: rgba(201, 212, 232, 0.1); }
.chip.ok .dot { background: #4ade80; }
.chip.bad { color: var(--text-lo); background: var(--bg-raised); }
.chip.bad .dot { background: var(--text-faint); }

.manage-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: var(--radius-sm);
  background: var(--bg-raised); border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-hi); font-size: 12.5px; cursor: pointer; transition: all var(--transition);
}
.manage-btn:hover { border-color: var(--accent-dim); }

/* iframe 不透明——Immich 自己的界面 */
.frame {
  flex: 1; width: 100%;
  background: #14171f; /* 加载前底色与外壳同色（白色会在加载期/边缘露白边） */
  border-radius: 0 0 12px 12px;
  border: 1px solid rgba(201, 212, 232, 0.16);
  border-top: none;
  box-sizing: border-box;
  opacity: 0; transition: opacity 250ms ease;
}
.frame.ready { opacity: 1; }

.frame-stopped {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; color: var(--text-faint);
}
.frame-stopped p { font-size: 13px; }

/* ── 中心（未装） ── */
.center {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; text-align: center;
}
.center-icon { color: var(--text-lo); opacity: 0.9; }
.center h1 { font-size: 22px; font-weight: 600; letter-spacing: 1px; }
.hint { color: var(--text-lo); font-size: 13px; }

/* ── 管理浮窗 ── */
.overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid; place-items: center;
  z-index: 100;
}
.dialog {
  width: min(560px, calc(100vw - 32px));
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
.body { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.state { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.state .dot { width: 7px; height: 7px; border-radius: 50%; }
.state.ok { color: var(--accent); }
.state.ok .dot { background: #4ade80; }
.state.bad { color: var(--text-lo); }
.state.bad .dot { background: var(--text-faint); }
.label { font-size: 12.5px; color: var(--text-lo); line-height: 1.6; }
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
</style>
