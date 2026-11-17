<script setup lang="ts">
// The settings-page compatibility slot is a link, not a second editor/store.
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import { useRouter, useRoute } from "vue-router";
import { loginPrompt } from "../modules/auth/loginPrompt";

const props = defineProps<{embedded?:boolean}>();
const router = useRouter();
const route = useRoute();
import { settingsOpen, bgManagerOpen, homeSettings, DEFAULT_HOME_BG, homeSaveErrors, homeSaved, retryHomeSave } from "../modules/home/settings";
import { auth, displayBg, loggedIn } from "../modules/home/auth";
const panel = ref<HTMLElement>();
const eligible = computed(() => !props.embedded && route.name === 'home' && loggedIn.value && !loginPrompt.requested);
const visible = computed(() => eligible.value && settingsOpen.value && !bgManagerOpen.value);
async function returnHome() { await router.push('/'); if (loggedIn.value) settingsOpen.value = true; }
function close() { settingsOpen.value = false; }
function restoreFocus() {
  if (eligible.value) document.querySelector<HTMLButtonElement>('.home-settings-trigger')?.focus({ preventScroll:true });
}
function trap(event:KeyboardEvent) {
  if (!eligible.value || !settingsOpen.value) return;
  // The background delete confirmation owns its own Escape/Tab trap.
  // Do not let the drawer's capture handler close the gallery underneath it.
  const deletion = bgManagerOpen.value ? document.querySelector<HTMLElement>('.bgm-delete') : null;
  if (deletion) {
    if (!deletion.contains(event.target as Node)) { event.preventDefault(); deletion.focus(); }
    return;
  }
  const crop = bgManagerOpen.value ? document.querySelector<HTMLElement>('.crop-wrap') : null;
  const activePanel = bgManagerOpen.value ? crop || document.querySelector<HTMLElement>('.bgm') : panel.value;
  if (!activePanel) return;
  if (event.key === 'Escape') {
    event.preventDefault(); event.stopImmediatePropagation();
    if (crop) {
      crop.querySelector<HTMLButtonElement>('.crop-actions .ghost')?.click();
      void nextTick(() => { if (eligible.value && bgManagerOpen.value) document.querySelector<HTMLButtonElement>('.bgm .x')?.focus(); });
    }
    else if (bgManagerOpen.value) bgManagerOpen.value = false;
    else close();
    return;
  }
  if (event.key !== 'Tab') return;
  const nodes = Array.from(activePanel.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),a[href],[tabindex="0"]')).filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const first = nodes[0], last = nodes[nodes.length-1];
  if (!activePanel.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
watch(eligible, ready => { if (!props.embedded && !ready) { settingsOpen.value = false; bgManagerOpen.value = false; } }, {flush:'sync'});
watch(visible, async open => {
  await nextTick();
  if (open && visible.value) panel.value?.querySelector<HTMLButtonElement>('.p-close')?.focus();
  else if (!settingsOpen.value) restoreFocus();
}, {immediate:true});
onMounted(() => { if (!props.embedded) document.addEventListener('keydown', trap, true); });
onBeforeUnmount(() => { document.removeEventListener('keydown', trap, true); void nextTick(restoreFocus); });
import Dropdown from "./Dropdown.vue";

import { backgroundEntries, loadBackgroundEntries, useBackgroundMedia, backgroundThumbnail, qualityOptions, setBackgroundQuality, optimizeBackground, QUALITY_KEY } from "../modules/home/backgroundMedia";

const themes = [
  { key: "daybreak", name: "破晓", desc: "白天云海 · 黑胶唱片 · 衬线标题" },
  { key: "nightfall", name: "夜泊", desc: "破晓同款暗色版 · 月光银 · 夜色玻璃" },
  { key: "classic", name: "经典", desc: "夜色星空 · 墨紫星光 · 签名卡" },
];

/* 背景图：当前项的名字 + 预览 */
const bgList = backgroundEntries;
const { media, quality, status } = useBackgroundMedia(computed(() => visible.value ? displayBg.value : ""));
function pickQuality(value:unknown) {
  setBackgroundQuality(value);
  try {
    localStorage.setItem(QUALITY_KEY, quality.value);
    if (localStorage.getItem(QUALITY_KEY) !== quality.value) throw new Error('readback mismatch');
    delete homeSaveErrors.quality; homeSaved.value = true;
  } catch { homeSaveErrors.quality = '画质未保存到当前设备，选择已保留。请检查浏览器存储后重试。'; }
}
function retryLocalSave() { retryHomeSave(); if (homeSaveErrors.quality) pickQuality(quality.value); }
async function loadBgList() {
  try { await loadBackgroundEntries(); } catch { /* no notification spam */ }
}
watch(visible, (v) => { if (v) void loadBgList(); }, { immediate: true });
const currentBg = computed(() => bgList.value.find((e) => e.url === displayBg.value));
const bgName = computed(() => currentBg.value?.name || displayBg.value.split("/").pop()?.replace(/\.[^.]+$/, "") || "无背景");
const thumbnail = computed(() => backgroundThumbnail(displayBg.value));
const resetting = ref(false);
const resetError = ref('');
const resetSaved = ref(false);
let alive = true;
onBeforeUnmount(() => { alive = false; });
async function resetBg() {
  if (resetting.value || !eligible.value) return;
  const owner = auth.me?.id, generation = auth.sessionGeneration, epoch = auth.requestEpoch;
  const current = () => alive && eligible.value && owner === auth.me?.id && generation === auth.sessionGeneration && epoch === auth.requestEpoch;
  resetting.value = true;
  resetSaved.value = false;
  try {
    const r = await fetch("/auth/me", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home_bg: DEFAULT_HOME_BG }),
    });
    if (!current()) return;
    if (!r.ok) throw new Error(`恢复默认失败 (${r.status})，原背景已保留。`);
    const updated = await r.json();
    if (updated.home_bg !== DEFAULT_HOME_BG) throw new Error("服务器未保存默认背景");
    const read = await fetch('/auth/me');
    if (!current()) return;
    if (!read.ok) throw new Error('恢复默认未确认，请重试读取。');
    const confirmed = await read.json();
    if (!current()) return;
    if (confirmed.id !== owner || confirmed.home_bg !== DEFAULT_HOME_BG) throw new Error('服务器背景读回不一致，请重试。');
    auth.me = confirmed;
    resetError.value = ''; resetSaved.value = true;
  } catch (e) { if (current()) resetError.value = e instanceof Error ? e.message : '恢复默认失败，原背景已保留。'; }
  finally { resetting.value = false; }
}

const particleOptions = [
  { value: "stars", label: "星空点点" },
  { value: "motes", label: "浮尘微粒" },
  { value: "sakura", label: "樱花飘落" },
  { value: "off", label: "关闭" },
];
function pickParticle(v: string | number | boolean) {
  if (v === "stars" || v === "motes" || v === "sakura" || v === "off") homeSettings.particles = v;
}
</script>

<template>
  <button v-if="embedded" class="mini-btn" @click="returnHome">到主页调整外观</button>
  <Teleport v-else to="body">
    <div v-if="visible" class="mask" @click.self="close">
      <aside ref="panel" class="panel" :data-home-theme="homeSettings.theme" role="dialog" aria-modal="true" aria-label="主页设置" tabindex="-1">
        <header class="p-head"><h2 class="p-title">主页设置</h2><button class="p-close" aria-label="关闭主页设置" @click="close">×</button></header>
        <div class="save-state">
          <template v-if="Object.keys(homeSaveErrors).length">
            <p v-for="(message, field) in homeSaveErrors" :key="field" role="alert">{{ message }}</p>
            <button class="mini-btn" @click="retryLocalSave">重试本地保存</button>
          </template>
          <p v-else role="status">{{ homeSaved ? '已保存在当前设备' : '外观修改自动保存在当前设备' }}</p>
        </div>
        <section class="sec">
          <div class="sec-t">主页主题</div>
          <button
            v-for="t in themes"
            :key="t.key"
            class="theme-row"
            :aria-pressed="homeSettings.theme === t.key"
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
          <Dropdown :model-value="homeSettings.particles" :options="particleOptions" @update:model-value="pickParticle" />
        </section>

        <section class="sec">
          <div class="sec-t">站点</div>
          <div class="field">
            <label class="f-label" for="home-title">大标题</label>
            <input id="home-title" v-model="homeSettings.siteTitle" class="bg-input" placeholder="StellaHaven" />
          </div>
          <div class="field">
            <label class="f-label" for="home-signature">签名</label>
            <input id="home-signature" v-model="homeSettings.signature" class="bg-input" placeholder="夜有星辰，晨有曦光。" />
          </div>
          <div class="field">
            <label class="f-label" for="home-meet-date">相识起点</label>
            <input id="home-meet-date" v-model="homeSettings.meetDate" class="bg-input" type="date" />
          </div>
          <div class="row">
            <span class="r-text">Live2D 挂件（Miku）</span>
            <button
              class="switch"
              :class="{ on: homeSettings.live2d }"
              role="switch"
              aria-label="Live2D 挂件（Miku）"
              :aria-checked="homeSettings.live2d"
              @click="homeSettings.live2d = !homeSettings.live2d"
            ><i /></button>
          </div>
        </section>

        <section class="sec">
          <div class="sec-t">背景图</div>
          <div class="bg-now">
            <div class="bg-preview">
              <img v-if="thumbnail" :src="thumbnail" alt="当前背景" loading="lazy" />
              <div v-else class="bg-none">暂无缩略图</div>
            </div>
            <div class="bg-name" :title="bgName">{{ bgName }}</div>
          </div>
          <div class="field" style="margin-top: 14px">
            <span class="f-label">显示画质</span>
            <Dropdown :model-value="quality" :options="qualityOptions" @update:model-value="pickQuality" />
          </div>
          <div class="bg-none" style="height: auto">仅保存在当前设备 · 未就绪时使用原画</div>
          <p v-if="status === 'queued' || status === 'processing'" role="status">背景处理中…</p>
          <p v-if="media?.error && status === 'ready'" role="status">{{ media.error }}</p>
          <p v-if="status === 'error'" role="alert">{{ media?.error || '背景处理失败' }}
            <button v-if="auth.me" class="mini-btn" @click="optimizeBackground(displayBg)">重试</button>
          </p>
          <div class="bg-actions">
            <button class="mini-btn" :disabled="resetting || !loggedIn" @click="resetBg">{{ resetting ? '正在恢复…' : '恢复默认' }}</button>
            <button class="mini-btn" :disabled="resetting" @click="bgManagerOpen = true">更换背景</button>
          </div>
          <p v-if="resetError" role="alert" class="background-error">{{ resetError }} <button class="mini-btn" :disabled="resetting" @click="resetBg">重试恢复默认</button></p>
          <p v-else-if="resetSaved" role="status">账号背景已保存</p>
        </section>

      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.mask {
  position: fixed; inset: 0; z-index: 90;
  background: rgba(6, 10, 16, 0.45);
}
.mask { display:flex; justify-content:flex-end; }
.panel {
  font-family:"Inter", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", "WenQuanYi Micro Hei", system-ui, sans-serif;
  color-scheme:dark;
  width:min(440px,100%); height:100%; max-height:100dvh; overflow-y:auto; overscroll-behavior:contain;
  background:var(--bg-panel); color:var(--text-hi); border-left:1px solid var(--accent-dim);
  padding:20px 24px max(24px,env(safe-area-inset-bottom)); box-shadow:-18px 0 48px #0005;
}
.panel :is(button,input) { min-height:40px; }
.panel :is(button,input):focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.panel .field > * { min-width:0; }
.panel .bg-name { min-width:0; }
.save-state { font-size:13px; color:var(--text-lo); margin-top:8px; }
.save-state [role="alert"] { color:#f1c27b; }
.background-error { color:#f1c27b; margin-top:12px; font-size:13px; }
.p-head { display:flex; align-items:center; justify-content:space-between; position:sticky; top:-20px; z-index:2; background:var(--bg-panel); padding:12px 0; margin-top:-12px; }
@media(max-width:768px) { .p-head { top:-16px; } }
.p-title { font-size: 17px; font-weight: 600; color: var(--text-hi); letter-spacing: 2px; }
.p-close {
  width: 44px; height: 44px; border-radius: 8px;
  border: none; background: transparent; color: var(--text-lo);
  cursor: pointer; font-size: 24px; transition: all 200ms;
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
  width:48px; height:44px; flex-shrink:0;
  border:0; background:transparent;
  cursor: pointer;
  position: relative;
  transition: all 220ms;
  padding: 0;
}
.switch::before { content:''; position:absolute; width:40px; height:22px; left:4px; top:11px; border-radius:999px; border:1px solid var(--text-lo); background:var(--bg-raised); }
.switch i {
  position: absolute; left:7px; top:14px;
  width: 16px; height: 16px; border-radius: 50%;
  background: var(--text-lo);
  transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1);
}
.switch.on::before { background:var(--accent); border-color:var(--accent); }
.switch.on i { left:25px; background:var(--bg-panel); }

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
.bg-input::placeholder { color:var(--text-faint); opacity:1; }
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
.bg-preview img { width: 100%; height: 100%; object-fit: cover; display: block; }
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
@media(max-width:768px) {
  .panel { width:min(440px,100%); padding:16px 18px max(18px,env(safe-area-inset-bottom)); }
  .panel :is(button,input) { min-height:44px; }
  .theme-row { grid-template-columns:1fr auto; }
  .t-desc { grid-row:2; grid-column:1/-1; font-size:12px; }
  .field { flex-wrap:wrap; }
  .field .bg-input { flex-basis:180px; }
}
</style>
