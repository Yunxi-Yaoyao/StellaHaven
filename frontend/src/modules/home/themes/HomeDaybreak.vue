<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";

/* ================= 文字内容 ================= */
const signature = computed(() => homeSettings.signature);

const daysTogether = computed(() => {
  const p = (homeSettings.meetDate || "2026-05-31").split("-").map(Number);
  const from = new Date(p[0], (p[1] || 1) - 1, p[2] || 1);
  return Math.max(1, Math.floor((Date.now() - from.getTime()) / 86400000) + 1);
});

/* ================= 心情便签：每天重置，默认「今天的心情是混沌喵~」 ================= */
const MOOD_DEFAULT = "今天的心情是混沌喵~";
const mood = ref("");
const moodEditing = ref(false);
const moodDraft = ref("");

function todayKey() { return new Date().toDateString(); }
onMounted(() => {
  if (localStorage.getItem("stella_mood_date") === todayKey()) {
    mood.value = localStorage.getItem("stella_mood") || "";
  } else {
    // 新的一天：重置便签
    localStorage.setItem("stella_mood_date", todayKey());
    localStorage.setItem("stella_mood", "");
    mood.value = "";
  }
});
function openMoodEditor() {
  moodDraft.value = mood.value;
  moodEditing.value = true;
}
function commitMood() {
  mood.value = moodDraft.value.trim();
  localStorage.setItem("stella_mood", mood.value);
  localStorage.setItem("stella_mood_date", todayKey());
  moodEditing.value = false;
}

/* ================= 设置 store（背景图/星空/主题都在设置面板里改） ================= */
import BgLayer from "../BgLayer.vue";
import { homeSettings, settingsOpen } from "../settings";
const bgImage = computed(() => homeSettings.bgImage);

/* ================= Live2D 挂件（Miku，戳她播报今日塔罗） ================= */
import Live2dWidget from "../Live2dWidget.vue";

const tarotBubble = ref(false);
let bubbleTimer: ReturnType<typeof setTimeout> | null = null;
function showTarotBubble() {
  tarotBubble.value = true;
  if (bubbleTimer) clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => (tarotBubble.value = false), 6000);
}
const MAJORS: [string, string][] = [
  ["愚者", "新的开始，别怕迈出第一步"], ["魔术师", "资源都在手上，今天适合开工"],
  ["女祭司", "直觉比逻辑先知道答案"], ["女皇", "值得被自己好好喂养的一天"],
  ["皇帝", "把混乱收进秩序里"], ["教皇", "老办法里有意外的稳"],
  ["恋人", "重要关系会有进展"], ["战车", "掌控节奏，别被拖着走"],
  ["力量", "温柔比硬扛更有力"], ["隐士", "独处会给你答案"],
  ["命运之轮", "转机正在转动，顺势而为"], ["正义", "该算的账算清楚，心就轻了"],
  ["倒吊人", "换个角度，卡住的事会松"], ["死神", "结束某个旧模式，正是新生"],
  ["节制", "慢慢来，比较快"], ["恶魔", "看见诱惑，就是自由的开始"],
  ["高塔", "塌掉的本就不稳，重建更牢"], ["星星", "希望不是幻觉，它在路上了"],
  ["月亮", "不安会散，别在夜里做决定"], ["太阳", "今天是发光的日子"],
  ["审判", "过去的努力要被看见了"], ["世界", "一个阶段圆满，下一个开始"],
];
const todayCard = computed(() => {
  const d = new Date();
  const seed = d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
  return MAJORS[seed % MAJORS.length];
});

/* ================= 主题切换逻辑已搬进设置面板（SideBar 入口） ================= */

/* ================= 粒子氛围（星空/浮尘/樱花，设置面板下拉切换） ================= */
import ParticleCanvas from "../ParticleCanvas.vue";
import TimeProgress from "../TimeProgress.vue";
const isNight = computed(() => homeSettings.theme === "nightfall");
const particleMode = computed(() =>
  homeSettings.particles === "off" ? "motes" : homeSettings.particles
);

/* ================= 日期时间 ================= */
const now = ref(new Date());
let clockTimer: ReturnType<typeof setInterval>;
onMounted(() => { clockTimer = setInterval(() => (now.value = new Date()), 30000); });
onUnmounted(() => clearInterval(clockTimer));
const dateLine = computed(() =>
  now.value.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" }) +
  " · " + now.value.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
);
</script>

<template>
  <div class="daybreak" :class="{ night: isNight }">
    <!-- 白昼云海底：背景图提权清晰显示 + 左白右透遮罩（参考图的那层白） -->
    <BgLayer v-if="bgImage" class="bg-img" :url="bgImage" :crop="homeSettings.bgCrop" />
    <div class="scrim" />
    <ParticleCanvas v-if="homeSettings.particles !== 'off'" :mode="particleMode" />

    <!-- ═══ 左：信息区（不是播放器） ═══ -->
    <section class="panel">
      <div class="brand">
        <div class="badge">云曦 · YUNXI'S</div>
        <div class="brand-rule" />
      </div>
      <h1 class="title">{{ homeSettings.siteTitle }}</h1>

      <!-- 波形装饰线 -->
      <div class="wave" aria-hidden="true">
        <i v-for="n in 36" :key="n" :style="{ height: 4 + Math.abs(Math.sin(n * 1.7)) * 14 + 'px', animationDelay: n * 0.09 + 's' }" />
      </div>

      <!-- 黑胶唱片（头像碟心，缓转） -->
      <div class="vinyl" title="云曦的唱片">
        <div class="grooves" />
        <div class="label"><img :src="homeSettings.avatar" alt="云曦" /></div>
        <div class="sheen" />
      </div>

      <!-- 歌词位：签名 / 心情 / 天数 -->
      <div class="lyrics">
        <p class="lyr-main">{{ signature }}</p>
        <p class="lyr-sub mood-line" @click="openMoodEditor" title="点我写一句今天的心情">{{ mood || MOOD_DEFAULT }}</p>
        <p class="lyr-sub">与娅娅相识的第 {{ daysTogether }} 天</p>

        <!-- 心情小浮窗：贴着便签正下方弹出 -->
        <Transition name="pop">
          <div v-if="moodEditing" class="mood-pop" @keydown.esc="moodEditing = false">
            <div class="mp-title">今天的心情便签</div>
            <input
              v-model="moodDraft"
              class="mp-input"
              :placeholder="MOOD_DEFAULT"
              maxlength="40"
              autofocus
              @keydown.enter="commitMood"
            />
            <div class="mp-actions">
              <button class="mp-btn ghost" @click="moodEditing = false">算了</button>
              <button class="mp-btn" @click="commitMood">收下</button>
            </div>
          </div>
        </Transition>
      </div>

      <!-- 时光进度条组（今天/本周/本月 + 今年小字） -->
      <div class="progress-wrap">
        <TimeProgress />
      </div>

      <!-- 底部功能图标行：塔罗 + 设置（换背景/切主题都在面板里） -->
      <div class="controls">
        <button class="ctl" title="今日塔罗" @click="showTarotBubble">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>
        </button>
        <button class="ctl" title="主页设置" @click="settingsOpen = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h9M17 8h3M4 16h3M11 16h9"/><circle cx="15" cy="8" r="2.2"/><circle cx="9" cy="16" r="2.2"/></svg>
        </button>
      </div>
    </section>

    <!-- ═══ 右：Miku（出血位贴右缘） ═══ -->
    <div class="shinano">
      <Live2dWidget v-if="homeSettings.live2d" :headroom="150" @poke="showTarotBubble" />
    </div>
    <Transition name="bubble">
      <div v-if="tarotBubble" class="tarot-bubble">
        <div class="tb-name">🃏 今日牌 · {{ todayCard[0] }}</div>
        <div class="tb-mean">{{ todayCard[1] }}</div>
      </div>
    </Transition>

    <div class="date-line">{{ dateLine }}</div>
  </div>
</template>

<style scoped>
.daybreak {
  position: relative;
  height: 100%;
  overflow: hidden;
  background: var(--bg-page);
}
/* ═══ 皮肤变量：默认=破晓（亮），.night=夜泊（暗） ═══ */
.daybreak {
  --bg-page: linear-gradient(168deg, #f7fafc 0%, #e8f1f7 46%, #d9e8f2 100%);
  --bg-opacity: 0.9;
  --bg-filter: brightness(1.05) saturate(0.95);
  --scrim: linear-gradient(to right, rgba(247,250,252,0.97) 0%, rgba(247,250,252,0.94) 30%, rgba(247,250,252,0.55) 46%, rgba(247,250,252,0) 62%);
  --t-text: #1c2b3a;
  --t-badge-bg: #16202c; --t-badge-fg: #f2f6fa;
  --t-rule: linear-gradient(to right, #16202c, rgba(22,32,44,0.12));
  --t-title: #5d93ad; --t-title-shadow: 0 2px 12px rgba(255,255,255,0.7);
  --t-wave: linear-gradient(180deg, #7fb3c8, #a8c9da);
  --t-lyr-main: #37536b; --t-lyr-sub: #7a8fa0; --t-lyr-hover: #5d93ad;
  --t-pop-bg: rgba(255,255,255,0.92); --t-pop-border: 1px solid rgba(93,147,173,0.25);
  --t-pop-shadow: 0 16px 40px rgba(44,90,117,0.22);
  --t-input-bg: rgba(255,255,255,0.8); --t-input-fg: #2c4a5e;
  --t-input-border: 1px solid rgba(93,147,173,0.35); --t-input-focus: #5d93ad;
  --t-btn-bg: #5d93ad; --t-btn-fg: #fff; --t-btn-hover: #4a7d97;
  --t-ctl-border: 1px solid rgba(93,147,173,0.35); --t-ctl-bg: rgba(255,255,255,0.55); --t-ctl-fg: #4d7186;
  --t-ctl-hover-bg: #ffffff; --t-ctl-hover-fg: #2c5a75; --t-ctl-hover-shadow: 0 6px 16px rgba(44,90,117,0.22);
  --t-bubble-bg: rgba(255,255,255,0.82); --t-bubble-border: 1px solid rgba(93,147,173,0.3);
  --t-bubble-shadow: 0 12px 32px rgba(44,90,117,0.18);
  --t-bubble-name: #b06084; --t-bubble-mean: #55707f;
  --t-date: #8ba0b0;
  --prog-track: rgba(93,147,173,0.18); --prog-from: #7fb3c8; --prog-to: #5d93ad;
  --prog-label: #7a8fa0; --prog-cap: #9aabba;
}
.daybreak.night {
  --bg-page: linear-gradient(168deg, #12151e 0%, #0d1017 46%, #090c12 100%);
  --bg-opacity: 0.55;
  --bg-filter: brightness(0.8) saturate(0.9);
  --scrim: linear-gradient(to right, rgba(14,17,25,0.97) 0%, rgba(14,17,25,0.93) 30%, rgba(14,17,25,0.55) 46%, rgba(14,17,25,0) 62%);
  --t-text: #e8ecf4;
  --t-badge-bg: rgba(201,212,232,0.92); --t-badge-fg: #16202c;
  --t-rule: linear-gradient(to right, rgba(201,212,232,0.85), rgba(201,212,232,0.1));
  --t-title: #c9d4e8; --t-title-shadow: 0 2px 16px rgba(201,212,232,0.25);
  --t-wave: linear-gradient(180deg, #8a94ab, #c9d4e8);
  --t-lyr-main: #c9d4e8; --t-lyr-sub: #8a94ab; --t-lyr-hover: #c9d4e8;
  --t-pop-bg: rgba(27,31,42,0.94); --t-pop-border: 1px solid rgba(201,212,232,0.18);
  --t-pop-shadow: 0 16px 40px rgba(0,0,0,0.5);
  --t-input-bg: rgba(13,16,23,0.6); --t-input-fg: #e8ecf4;
  --t-input-border: 1px solid rgba(201,212,232,0.25); --t-input-focus: #8a94ab;
  --t-btn-bg: #8a94ab; --t-btn-fg: #141824; --t-btn-hover: #c9d4e8;
  --t-ctl-border: 1px solid rgba(201,212,232,0.25); --t-ctl-bg: rgba(27,31,42,0.55); --t-ctl-fg: #9aa3b5;
  --t-ctl-hover-bg: rgba(40,48,64,0.9); --t-ctl-hover-fg: #c9d4e8; --t-ctl-hover-shadow: 0 6px 16px rgba(0,0,0,0.4);
  --t-bubble-bg: rgba(27,31,42,0.85); --t-bubble-border: 1px solid rgba(201,212,232,0.2);
  --t-bubble-shadow: 0 12px 32px rgba(0,0,0,0.45);
  --t-bubble-name: #e8a0bf; --t-bubble-mean: #9aa3b5;
  --t-date: #5c6474;
  --prog-track: rgba(201,212,232,0.14); --prog-from: #8a94ab; --prog-to: #c9d4e8;
  --prog-label: #8a94ab; --prog-cap: #5c6474;
}
.bg-img {
  position: absolute; inset: 0;
  background-size: cover; background-position: center;
  opacity: var(--bg-opacity); pointer-events: none;
  filter: var(--bg-filter);
}
/* 左白右透遮罩：参考图的真正机制——左边纯白不透明给文字托底，中间渐隐到全透 */
.scrim {
  position: absolute; inset: 0; pointer-events: none;
  background: var(--scrim);
}
.motes { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }

/* ── 左：信息区（上内容+下锚定，下半身不空） ── */
.panel {
  position: absolute;
  left: 6%; top: 9%; bottom: 7%;
  width: 480px;
  z-index: 5;
  color: var(--t-text);
  display: flex;
  flex-direction: column;
}
.panel > * { flex-shrink: 0; } /* flex 列布局默认压缩子项——唱片曾被压成 259×92 的椭圆 */
.brand { display: inline-flex; flex-direction: column; align-items: flex-start; align-self: flex-start; /* 不被 flex 父级拉宽，包住徽章即可 */ }
.badge {
  display: inline-block;
  padding: 5px 11px 5px 14px; /* 右 padding 吃掉 letter-spacing 的尾部空隙，刚好包住字 */
  background: var(--t-badge-bg);
  color: var(--t-badge-fg);
  font-size: 11px;
  letter-spacing: 3.5px;
  border-radius: 3px;
}
.brand-rule {
  margin-top: 8px;
  height: 1px;
  width: 100%; /* 与徽章同宽 */
  background: var(--t-rule);
}
.title {
  margin: 16px 0 0;
  font-family: "Playfair Display", Georgia, "Times New Roman", serif;
  font-size: 64px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--t-title);
  line-height: 1.05;
  text-shadow: var(--t-title-shadow);
}

/* 波形装饰 */
.wave {
  margin-top: 18px;
  display: flex;
  align-items: center;
  gap: 4px;
  height: 20px;
}
.wave i {
  width: 3px;
  border-radius: 2px;
  background: var(--t-wave);
  animation: wave-pulse 2.4s ease-in-out infinite;
  opacity: 0.85;
}
@keyframes wave-pulse {
  0%, 100% { transform: scaleY(0.6); }
  50% { transform: scaleY(1.15); }
}

/* 黑胶唱片（1.2 倍体型 + 右移 0.3 身位≈78px） */
.vinyl {
  position: relative;
  margin-top: 26px;
  margin-left: 78px;
  width: 259px;
  height: 259px;
  border-radius: 50%;
  animation: spin 9s linear infinite;
  box-shadow: 0 14px 34px rgba(28, 43, 58, 0.35), 0 2px 8px rgba(28, 43, 58, 0.25);
}
.grooves {
  position: absolute; inset: 0;
  border-radius: 50%;
  background:
    repeating-radial-gradient(circle at 50% 50%, #11161d 0px, #11161d 1.6px, #1d2530 1.6px, #1d2530 3.1px);
}
.sheen {
  position: absolute; inset: 0;
  border-radius: 50%;
  background: conic-gradient(from 210deg, transparent 0deg, rgba(255,255,255,0.16) 18deg, transparent 42deg, transparent 180deg, rgba(255,255,255,0.1) 200deg, transparent 228deg);
  pointer-events: none;
}
.label {
  position: absolute;
  left: 50%; top: 50%;
  width: 101px; height: 101px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  overflow: hidden;
  border: 3px solid #2a3442;
  box-shadow: 0 0 0 2px rgba(255,255,255,0.12);
}
.label img { width: 100%; height: 100%; object-fit: cover; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 歌词位 */
.lyrics { margin-top: 24px; position: relative; }
.lyr-main {
  font-size: 16px;
  color: var(--t-lyr-main);
  letter-spacing: 2px;
  font-weight: 500;
}
.lyr-sub {
  margin-top: 9px;
  font-size: 13px;
  color: var(--t-lyr-sub);
  letter-spacing: 1px;
}
.lyr-sub[title] { cursor: pointer; }
.lyr-sub[title]:hover { color: var(--t-lyr-hover); }

/* 心情小浮窗 */
.mood-pop {
  position: absolute;
  left: 0;
  top: 100%; /* 贴便签正下方 */
  margin-top: 8px;
  width: 300px;
  padding: 16px 18px 14px;
  background: var(--t-pop-bg);
  backdrop-filter: blur(14px);
  border: var(--t-pop-border);
  border-radius: 14px;
  box-shadow: var(--t-pop-shadow);
  z-index: 40;
}
.mp-title { font-size: 12px; color: var(--t-lyr-sub); letter-spacing: 2px; margin-bottom: 10px; }
.mp-input {
  width: 100%;
  padding: 9px 12px;
  border-radius: 9px;
  border: var(--t-input-border);
  background: var(--t-input-bg);
  color: var(--t-input-fg);
  font-size: 13.5px;
  font-family: inherit;
  outline: none;
  transition: border-color 200ms;
}
.mp-input:focus { border-color: var(--t-input-focus); }
.mp-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.mp-btn {
  padding: 6px 16px;
  border-radius: 9px;
  border: none;
  background: var(--t-btn-bg);
  color: var(--t-btn-fg);
  font-size: 12.5px;
  cursor: pointer;
  font-family: inherit;
  transition: all 200ms;
}
.mp-btn:hover { background: var(--t-btn-hover); }
.mp-btn.ghost { background: transparent; color: var(--t-lyr-sub); }
.mp-btn.ghost:hover { background: rgba(93, 147, 173, 0.12); }
.pop-enter-active, .pop-leave-active { transition: all 240ms cubic-bezier(0.22, 1, 0.36, 1); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(8px) scale(0.97); }

/* 时光进度条组（margin-top:auto 压到底部；--prog-* 主题色变量在 .daybreak 根上） */
.progress-wrap {
  margin-top: auto;
  padding-top: 22px;
}

/* 底部图标行 */
.controls {
  margin-top: 20px;
  display: flex;
  gap: 14px;
}
.ctl {
  width: 40px; height: 40px;
  border-radius: 50%;
  border: var(--t-ctl-border);
  background: var(--t-ctl-bg);
  color: var(--t-ctl-fg);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 220ms;
  backdrop-filter: blur(6px);
}
.ctl svg { width: 19px; height: 19px; }
.ctl:hover {
  background: var(--t-ctl-hover-bg);
  color: var(--t-ctl-hover-fg);
  transform: translateY(-2px);
  box-shadow: var(--t-ctl-hover-shadow);
}

/* ── 右：Miku（0.75 体型 + 画布向上延伸 80px 头部空间；热区锚内容盒自动跟随） ── */
.shinano {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 322px;
  height: 600px;
  z-index: 8;
}
@media (max-width: 768px) {
  .panel { left: 5%; width: 88%; }
  .title { font-size: 42px; }
  .vinyl { width: 150px; height: 150px; }
  .label { width: 60px; height: 60px; }
  .shinano { width: 58vw; height: 42%; right: -4%; }
}

/* 塔罗气泡 */
.tarot-bubble {
  position: absolute;
  right: 334px; top: 10%;
  max-width: 250px; padding: 14px 18px;
  background: var(--t-bubble-bg);
  backdrop-filter: blur(14px);
  border: var(--t-bubble-border);
  border-radius: 14px 14px 4px 14px;
  box-shadow: var(--t-bubble-shadow);
  z-index: 30; pointer-events: none;
}
.bubble-enter-active, .bubble-leave-active { transition: all 350ms cubic-bezier(0.22, 1, 0.36, 1); }
.bubble-enter-from, .bubble-leave-to { opacity: 0; transform: translateY(10px) scale(0.96); }
.tb-name { font-size: 14px; font-weight: 600; color: var(--t-bubble-name); letter-spacing: 1px; }
.tb-mean { margin-top: 6px; font-size: 13px; color: var(--t-bubble-mean); line-height: 1.6; }

.date-line {
  position: absolute;
  left: 22px; bottom: 18px;
  font-size: 12.5px;
  color: var(--t-date);
  letter-spacing: 1px;
  pointer-events: none;
  z-index: 5;
}
</style>
