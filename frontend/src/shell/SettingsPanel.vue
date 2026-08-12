<script setup lang="ts">
// 设置面板：右侧滑出。第一批设置项 = 主页主题 / 粒子氛围 / 背景图（附件系统）
import { ref, computed, watch } from "vue";
import { settingsOpen, bgManagerOpen, homeSettings, DEFAULT_HOME_BG } from "../modules/home/settings";

const themes = [
  { key: "daybreak", name: "破晓", desc: "白天云海 · 黑胶唱片 · 衬线标题" },
  { key: "nightfall", name: "夜泊", desc: "破晓同款暗色版 · 月光银 · 夜色玻璃" },
  { key: "coastline", name: "海岸线", desc: "航拍海岸 · 木质栈台 · 信纸水洼" },
  { key: "classic", name: "经典", desc: "夜色星空 · 签名卡 · 初版主页" },
];

/* 背景图：当前项的名字 + 预览 */
interface BgEntry { id: string; name: string; ext: string; url: string; isDefault: boolean; }
const bgList = ref<BgEntry[]>([]);
async function loadBgList() {
  try {
    const r = await fetch("/homebg/");
    bgList.value = await r.json();
  } catch { /* 后端没起就静默 */ }
}
watch(settingsOpen, (v) => { if (v) loadBgList(); });
watch(bgManagerOpen, (v) => { if (!v) loadBgList(); }); // 管理窗关掉后刷新名字

const currentBg = computed(() => bgList.value.find((e) => e.url === homeSettings.bgImage));
const bgName = computed(() => {
  if (currentBg.value) return currentBg.value.name;
  const seg = homeSettings.bgImage.split("/").pop() ?? "";
  return seg.replace(/\.[^.]+$/, "") || "无背景";
});
const bgIsVideo = computed(() => homeSettings.bgImage.toLowerCase().endsWith(".mp4"));

function resetBg() { homeSettings.bgImage = DEFAULT_HOME_BG; }

/* 自绘下拉（原生 select 的选中蓝样式管不了，老婆实锤刺眼） */
const selOpen = ref(false);
const particleOptions = [
  { value: "stars", label: "星空点点" },
  { value: "motes", label: "浮尘微粒" },
  { value: "sakura", label: "樱花飘落" },
  { value: "off", label: "关闭" },
] as const;
const particleLabel = computed(() =>
  particleOptions.find((o) => o.value === homeSettings.particles)?.label ?? "星空点点"
);
function pickParticle(v: string) {
  (homeSettings as any).particles = v;
  selOpen.value = false;
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="settingsOpen" class="mask" @click="settingsOpen = false" />
    </Transition>
    <Transition name="slide">
      <aside v-if="settingsOpen" class="panel">
        <div class="p-head">
          <div class="p-title">主页设置</div>
          <button class="p-close" title="关闭" @click="settingsOpen = false">✕</button>
        </div>

        <section class="sec">
          <div class="sec-t">主页主题</div>
          <button
            v-for="t in themes"
            :key="t.key"
            class="theme-row"
            :class="{ on: homeSettings.theme === t.key }"
            @click="homeSettings.theme = t.key"
          >
            <span class="t-name">{{ t.name }}</span>
            <span class="t-desc">{{ t.desc }}</span>
            <span class="t-check">{{ homeSettings.theme === t.key ? "●" : "○" }}</span>
          </button>
        </section>

        <section class="sec">
          <div class="sec-t">氛围粒子</div>
          <div class="sel">
            <button class="sel-btn" @click="selOpen = !selOpen">
              <span>{{ particleLabel }}</span>
              <span class="sel-arrow" :class="{ up: selOpen }">▾</span>
            </button>
            <Transition name="drop">
              <div v-if="selOpen" class="sel-list">
                <button
                  v-for="o in particleOptions"
                  :key="o.value"
                  class="sel-opt"
                  :class="{ on: homeSettings.particles === o.value }"
                  @click="pickParticle(o.value)"
                >
                  <span>{{ o.label }}</span>
                  <span class="tick">{{ homeSettings.particles === o.value ? "●" : "" }}</span>
                </button>
              </div>
            </Transition>
            <div v-if="selOpen" class="sel-mask" @click="selOpen = false" />
          </div>
        </section>

        <section class="sec">
          <div class="sec-t">站点</div>
          <div class="field">
            <span class="f-label">大标题</span>
            <input v-model="homeSettings.siteTitle" class="bg-input" placeholder="StellaHaven" />
          </div>
          <div class="field">
            <span class="f-label">签名</span>
            <input v-model="homeSettings.signature" class="bg-input" placeholder="夜有星辰，晨有曦光。" />
          </div>
          <div class="field">
            <span class="f-label">相识起点</span>
            <input v-model="homeSettings.meetDate" class="bg-input" type="date" />
          </div>
          <div class="row">
            <span class="r-text">Live2D 挂件（Miku）</span>
            <button
              class="switch"
              :class="{ on: homeSettings.live2d }"
              role="switch"
              :aria-checked="homeSettings.live2d"
              @click="homeSettings.live2d = !homeSettings.live2d"
            ><i /></button>
          </div>
        </section>

        <section class="sec">
          <div class="sec-t">背景图</div>
          <div class="bg-now">
            <div class="bg-preview">
              <video v-if="bgIsVideo" :src="homeSettings.bgImage" muted preload="metadata" />
              <img v-else-if="homeSettings.bgImage" :src="homeSettings.bgImage" alt="当前背景" />
              <div v-else class="bg-none">无背景</div>
            </div>
            <div class="bg-name" :title="bgName">{{ bgName }}</div>
          </div>
          <div class="bg-actions">
            <button class="mini-btn" @click="resetBg">恢复默认</button>
            <button class="mini-btn" @click="bgManagerOpen = true">更换背景</button>
          </div>
        </section>

        <div class="p-foot">更多设置施工中 · Stella</div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.mask {
  position: fixed; inset: 0; z-index: 90;
  background: rgba(6, 10, 16, 0.45);
}
.panel {
  position: fixed; top: 0; right: 0; bottom: 0; z-index: 95;
  width: 320px;
  background: color-mix(in srgb, var(--bg-panel) 92%, transparent);
  backdrop-filter: var(--blur);
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: -18px 0 48px rgba(0, 0, 0, 0.45);
  padding: 22px 20px;
  overflow-y: auto;
}
.p-head { display: flex; align-items: center; justify-content: space-between; }
.p-title { font-size: 17px; font-weight: 600; color: var(--text-hi); letter-spacing: 2px; }
.p-close {
  width: 30px; height: 30px; border-radius: 8px;
  border: none; background: transparent; color: var(--text-lo);
  cursor: pointer; font-size: 13px; transition: all 200ms;
}
.p-close:hover { background: rgba(255, 255, 255, 0.06); color: var(--text-hi); }

.sec { margin-top: 26px; }
.sec-t {
  font-size: 12px; color: var(--text-faint); letter-spacing: 2px;
  margin-bottom: 10px;
}

.theme-row {
  width: 100%;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: baseline;
  gap: 10px;
  padding: 11px 13px;
  margin-bottom: 8px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  transition: all 220ms;
  text-align: left;
  font-family: inherit;
}
.theme-row:hover { background: rgba(255, 255, 255, 0.06); }
.theme-row.on {
  border-color: var(--accent-dim);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.t-name { font-size: 14px; color: var(--text-hi); font-weight: 600; letter-spacing: 1px; }
.t-desc { font-size: 11.5px; color: var(--text-faint); }
.t-check { font-size: 12px; color: var(--accent); }

.row { display: flex; align-items: center; justify-content: space-between; padding: 4px 2px; }
.r-text { font-size: 13.5px; color: var(--text-lo); }
.switch {
  width: 40px; height: 22px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer;
  position: relative;
  transition: all 220ms;
  padding: 0;
}
.switch i {
  position: absolute; left: 2px; top: 2px;
  width: 16px; height: 16px; border-radius: 50%;
  background: var(--text-lo);
  transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1);
}
.switch.on { background: color-mix(in srgb, var(--accent) 55%, transparent); border-color: var(--accent-dim); }
.switch.on i { left: 20px; background: #fff; }

.bg-input {
  width: 100%;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-hi);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 200ms;
}
.bg-input:focus { border-color: var(--accent-dim); }
.bg-now { display: flex; align-items: center; gap: 12px; }
.field { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.f-label { font-size: 12.5px; color: var(--text-lo); width: 60px; flex-shrink: 0; letter-spacing: 1px; }
.field .bg-input { flex: 1; }
.bg-preview {
  width: 108px; height: 64px;
  border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  flex-shrink: 0;
}
.bg-preview img, .bg-preview video { width: 100%; height: 100%; object-fit: cover; display: block; }
.bg-none {
  width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11.5px; color: var(--text-faint);
}
.bg-name {
  font-size: 13.5px; color: var(--text-hi); letter-spacing: 0.5px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.avatar-preview {
  width: 34px; height: 34px; border-radius: 50%;
  object-fit: cover; flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.12);
}
/* 自绘下拉：和面板同质感（隐边按钮 + 深色浮层列表，无原生蓝） */
.sel { position: relative; }
.sel-btn {
  width: 100%;
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 13px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-hi);
  font-size: 13.5px; font-family: inherit;
  cursor: pointer;
  transition: all 220ms;
}
.sel-btn:hover { background: rgba(255, 255, 255, 0.06); }
.sel-arrow { font-size: 11px; color: var(--text-lo); transition: transform 220ms; }
.sel-arrow.up { transform: rotate(180deg); }
.sel-mask { position: fixed; inset: 0; z-index: 96; }
.sel-list {
  position: absolute; left: 0; right: 0; top: calc(100% + 6px);
  z-index: 97;
  background: var(--bg-panel);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 12px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
  padding: 5px;
  overflow: hidden;
}
.sel-opt {
  width: 100%;
  display: flex; align-items: center; justify-content: space-between;
  padding: 9px 11px;
  border: none; border-radius: 8px;
  background: transparent;
  color: var(--text-lo);
  font-size: 13px; font-family: inherit;
  cursor: pointer;
  transition: all 180ms;
}
.sel-opt:hover { background: rgba(255, 255, 255, 0.06); color: var(--text-hi); }
.sel-opt.on { color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
.tick { font-size: 10px; }
.drop-enter-active, .drop-leave-active { transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1); }
.drop-enter-from, .drop-leave-to { opacity: 0; transform: translateY(-6px); }
.bg-actions { display: flex; gap: 8px; margin-top: 10px; }
.mini-btn {
  padding: 6px 14px;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-lo);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 200ms;
  font-family: inherit;
}
.mini-btn:hover { color: var(--text-hi); background: rgba(255, 255, 255, 0.08); }

.p-foot {
  margin-top: 40px;
  font-size: 11.5px;
  color: var(--text-faint);
  text-align: center;
  letter-spacing: 1px;
}

.fade-enter-active, .fade-leave-active { transition: opacity 280ms; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.slide-enter-active, .slide-leave-active { transition: transform 320ms cubic-bezier(0.22, 1, 0.36, 1); }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }
</style>
