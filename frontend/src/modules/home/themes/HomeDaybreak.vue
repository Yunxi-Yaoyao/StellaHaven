<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";

/* ================= 文字内容 ================= */
const signature = "夜有星辰，晨有曦光。";

const daysTogether = computed(() => {
  const from = new Date(2026, 4, 31);
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

/* ================= 时光进度条（绑 now 响应式，30s 一跳） ================= */
const yearProgress = computed(() => {
  const d = now.value; // 响应式依赖！之前用 new Date() 是冻住的（老婆抓的 bug）
  const start = new Date(d.getFullYear(), 0, 1).getTime();
  const end = new Date(d.getFullYear() + 1, 0, 1).getTime();
  return ((d.getTime() - start) / (end - start)) * 100;
});
// 今日进度：肉眼可见地走
const dayProgress = computed(() => {
  const d = now.value;
  return ((d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400) * 100;
});

/* ================= 主题切换逻辑已搬进设置面板（SideBar 入口） ================= */

/* ================= 粒子氛围（星空/浮尘/樱花，设置面板下拉切换） ================= */
import ParticleCanvas from "../ParticleCanvas.vue";
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
  <div class="daybreak">
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
      <h1 class="title">StellaHaven</h1>

      <!-- 波形装饰线 -->
      <div class="wave" aria-hidden="true">
        <i v-for="n in 36" :key="n" :style="{ height: 4 + Math.abs(Math.sin(n * 1.7)) * 14 + 'px', animationDelay: n * 0.09 + 's' }" />
      </div>

      <!-- 黑胶唱片（头像碟心，缓转） -->
      <div class="vinyl" title="云曦的唱片">
        <div class="grooves" />
        <div class="label"><img src="/avatar.png" alt="云曦" /></div>
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

      <!-- 时光进度条：今日可见地走 + 今年慢变量 -->
      <div class="progress-row">
        <div class="track"><div class="fill" :style="{ width: dayProgress + '%' }" /></div>
        <span class="pct">{{ dayProgress.toFixed(1) }}%</span>
      </div>
      <div class="progress-cap">今天 {{ dayProgress.toFixed(1) }}% · 今年 {{ yearProgress.toFixed(1) }}%</div>

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
      <Live2dWidget :headroom="150" @poke="showTarotBubble" />
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
  background: linear-gradient(168deg, #f7fafc 0%, #e8f1f7 46%, #d9e8f2 100%);
}
.bg-img {
  position: absolute; inset: 0;
  background-size: cover; background-position: center;
  opacity: 0.9; pointer-events: none;
  filter: brightness(1.05) saturate(0.95);
}
/* 左白右透遮罩：参考图的真正机制——左边纯白不透明给文字托底，中间渐隐到全透 */
.scrim {
  position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(to right,
    rgba(247, 250, 252, 0.97) 0%,
    rgba(247, 250, 252, 0.94) 30%,
    rgba(247, 250, 252, 0.55) 46%,
    rgba(247, 250, 252, 0) 62%);
}
.motes { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }

/* ── 左：信息区（上内容+下锚定，下半身不空） ── */
.panel {
  position: absolute;
  left: 6%; top: 9%; bottom: 7%;
  width: 480px;
  z-index: 5;
  color: #1c2b3a;
  display: flex;
  flex-direction: column;
}
.panel > * { flex-shrink: 0; } /* flex 列布局默认压缩子项——唱片曾被压成 259×92 的椭圆 */
.brand { display: inline-flex; flex-direction: column; align-items: flex-start; align-self: flex-start; /* 不被 flex 父级拉宽，包住徽章即可 */ }
.badge {
  display: inline-block;
  padding: 5px 11px 5px 14px; /* 右 padding 吃掉 letter-spacing 的尾部空隙，刚好包住字 */
  background: #16202c;
  color: #f2f6fa;
  font-size: 11px;
  letter-spacing: 3.5px;
  border-radius: 3px;
}
.brand-rule {
  margin-top: 8px;
  height: 1px;
  width: 100%; /* 与徽章同宽 */
  background: linear-gradient(to right, #16202c, rgba(22, 32, 44, 0.12));
}
.title {
  margin: 16px 0 0;
  font-family: "Playfair Display", Georgia, "Times New Roman", serif;
  font-size: 64px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #5d93ad;
  line-height: 1.05;
  text-shadow: 0 2px 12px rgba(255, 255, 255, 0.7);
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
  background: linear-gradient(180deg, #7fb3c8, #a8c9da);
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
  color: #37536b;
  letter-spacing: 2px;
  font-weight: 500;
}
.lyr-sub {
  margin-top: 9px;
  font-size: 13px;
  color: #7a8fa0;
  letter-spacing: 1px;
}
.lyr-sub[title] { cursor: pointer; }
.lyr-sub[title]:hover { color: #5d93ad; }

/* 心情小浮窗 */
.mood-pop {
  position: absolute;
  left: 0;
  top: 100%; /* 贴便签正下方 */
  margin-top: 8px;
  width: 300px;
  padding: 16px 18px 14px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(93, 147, 173, 0.25);
  border-radius: 14px;
  box-shadow: 0 16px 40px rgba(44, 90, 117, 0.22);
  z-index: 40;
}
.mp-title { font-size: 12px; color: #7a8fa0; letter-spacing: 2px; margin-bottom: 10px; }
.mp-input {
  width: 100%;
  padding: 9px 12px;
  border-radius: 9px;
  border: 1px solid rgba(93, 147, 173, 0.35);
  background: rgba(255, 255, 255, 0.8);
  color: #2c4a5e;
  font-size: 13.5px;
  font-family: inherit;
  outline: none;
  transition: border-color 200ms;
}
.mp-input:focus { border-color: #5d93ad; }
.mp-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.mp-btn {
  padding: 6px 16px;
  border-radius: 9px;
  border: none;
  background: #5d93ad;
  color: #fff;
  font-size: 12.5px;
  cursor: pointer;
  font-family: inherit;
  transition: all 200ms;
}
.mp-btn:hover { background: #4a7d97; }
.mp-btn.ghost { background: transparent; color: #7a8fa0; }
.mp-btn.ghost:hover { background: rgba(93, 147, 173, 0.12); }
.pop-enter-active, .pop-leave-active { transition: all 240ms cubic-bezier(0.22, 1, 0.36, 1); }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(8px) scale(0.97); }

/* 时光进度条（margin-top:auto 把它和下面的塔罗签/按钮一起压到底部） */
.progress-row {
  margin-top: auto;
  padding-top: 22px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.track {
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: rgba(93, 147, 173, 0.18);
  overflow: hidden;
}
.fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #7fb3c8, #5d93ad);
}
.pct { font-size: 12px; color: #7a8fa0; letter-spacing: 1px; }
.progress-cap {
  margin-top: 8px;
  font-size: 12px;
  color: #9aabba;
  letter-spacing: 1px;
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
  border: 1px solid rgba(93, 147, 173, 0.35);
  background: rgba(255, 255, 255, 0.55);
  color: #4d7186;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 220ms;
  backdrop-filter: blur(6px);
}
.ctl svg { width: 19px; height: 19px; }
.ctl:hover {
  background: #ffffff;
  color: #2c5a75;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(44, 90, 117, 0.22);
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
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(93, 147, 173, 0.3);
  border-radius: 14px 14px 4px 14px;
  box-shadow: 0 12px 32px rgba(44, 90, 117, 0.18);
  z-index: 30; pointer-events: none;
}
.bubble-enter-active, .bubble-leave-active { transition: all 350ms cubic-bezier(0.22, 1, 0.36, 1); }
.bubble-enter-from, .bubble-leave-to { opacity: 0; transform: translateY(10px) scale(0.96); }
.tb-name { font-size: 14px; font-weight: 600; color: #b06084; letter-spacing: 1px; }
.tb-mean { margin-top: 6px; font-size: 13px; color: #55707f; line-height: 1.6; }

.date-line {
  position: absolute;
  left: 22px; bottom: 18px;
  font-size: 12.5px;
  color: #8ba0b0;
  letter-spacing: 1px;
  pointer-events: none;
  z-index: 5;
}
</style>
