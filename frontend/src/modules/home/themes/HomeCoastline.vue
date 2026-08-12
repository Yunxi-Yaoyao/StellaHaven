<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";

/* ================= 签名（信纸上的字） ================= */
const signature = computed(() => homeSettings.signature);

const daysTogether = computed(() => {
  const p = (homeSettings.meetDate || "2026-05-31").split("-").map(Number);
  const from = new Date(p[0], (p[1] || 1) - 1, p[2] || 1);
  return Math.max(1, Math.floor((Date.now() - from.getTime()) / 86400000) + 1);
});

const mood = ref(localStorage.getItem("stella_mood") || "");
function editMood() {
  const m = prompt("今天的心情便签", mood.value);
  if (m !== null) {
    mood.value = m.trim();
    localStorage.setItem("stella_mood", mood.value);
  }
}

/* ================= 自定义背景图（海洋，不被遮挡） ================= */
import BgLayer from "../BgLayer.vue";
import { homeSettings, settingsOpen } from "../settings";
import { loggedIn, currentAvatar } from "../auth";
const bgImage = computed(() => homeSettings.bgImage);
function setBg() {
  settingsOpen.value = true; // 小齿轮变成设置面板入口
}

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

/* ================= 粒子氛围（星空/浮尘/樱花，设置面板下拉切换） ================= */
import ParticleCanvas from "../ParticleCanvas.vue";
const particleMode = computed(() =>
  homeSettings.particles === "off" ? "stars" : homeSettings.particles
);

/* ================= 水洼里的星子（比天上的暗、慢、糊） ================= */
interface PoolStar { left: string; top: string; size: number; delay: string; dur: string; }
const poolStars: PoolStar[] = Array.from({ length: 14 }, () => ({
  left: 12 + Math.random() * 76 + "%",
  top: 15 + Math.random() * 70 + "%",
  size: 1.5 + Math.random() * 2.5,
  delay: Math.random() * 6 + "s",
  dur: 3 + Math.random() * 4 + "s",
}));

/* ================= 水洼涟漪（点水面 = 写字） ================= */
interface Ripple { id: number; x: number; y: number; }
const ripples = ref<Ripple[]>([]);
let rippleId = 0;
function pokePool(e: MouseEvent) {
  const el = e.currentTarget as HTMLElement;
  const r = el.getBoundingClientRect();
  const id = ++rippleId;
  ripples.value.push({ id, x: e.clientX - r.left, y: e.clientY - r.top });
  setTimeout(() => { ripples.value = ripples.value.filter((p) => p.id !== id); }, 1600);
  editMood();
}

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
  <div class="home">
    <!-- 海洋（自定义背景图 + 夜海罩层） -->
    <BgLayer v-if="bgImage" class="bg-img" :url="bgImage" :crop="homeSettings.bgCrop" />
    <div class="sea-tint" />
    <div class="sea-glow" />
    <ParticleCanvas v-if="homeSettings.particles !== 'off'" :mode="particleMode" />

    <!-- ═══ 木栈台（薇尔莉特风蜂蜜暖棕，上窄下宽，右缘渐隐入海） ═══ -->
    <div class="deck">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <defs>
          <linearGradient id="wood" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#7a5a3a" />
            <stop offset="0.45" stop-color="#6b4c30" />
            <stop offset="1" stop-color="#54371f" />
          </linearGradient>
          <filter id="foam-blur" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="0.9" />
          </filter>
          <filter id="foam-blur-soft" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="0.25" />
          </filter>
        </defs>
        <!-- 台面：左起蜿蜒斜线，上窄下宽 -->
        <path d="M 0 18 C 12 22, 22 30, 28 44 C 34 58, 42 74, 52 100 L 0 100 Z" fill="url(#wood)" />
        <!-- 海岸线泡沫：沿木缘的蜿蜒白边（航拍海岸那道白） -->
        <path d="M 0 18 C 12 22, 22 30, 28 44 C 34 58, 42 74, 52 100" fill="none"
          stroke="rgba(235,242,250,0.5)" stroke-width="2.6" stroke-linecap="round"
          filter="url(#foam-blur)" />
        <path d="M 0 18 C 12 22, 22 30, 28 44 C 34 58, 42 74, 52 100" fill="none"
          stroke="rgba(240,246,252,0.85)" stroke-width="0.55" stroke-linecap="round"
          filter="url(#foam-blur-soft)" />
        <!-- 内側一道湿木浅水线 -->
        <path d="M 0 21 C 11 25, 20 33, 25 46 C 30 59, 37 73, 45 100" fill="none"
          stroke="rgba(160,200,225,0.22)" stroke-width="1.1"
          filter="url(#foam-blur)" />
        <!-- 板缝（横向木板） -->
        <g stroke="rgba(30,18,8,0.35)" stroke-width="0.18">
          <path d="M 0 26 C 12 30, 22 38, 28 50" fill="none" />
          <path d="M 0 36 C 14 40, 24 48, 31 60" fill="none" />
          <path d="M 0 47 C 16 51, 27 60, 35 72" fill="none" />
          <path d="M 0 59 C 19 63, 31 72, 40 84" fill="none" />
          <path d="M 0 72 C 22 76, 36 85, 46 96" fill="none" />
          <path d="M 0 85 C 26 89, 40 94, 50 100" fill="none" />
        </g>
        <!-- 木纹细丝 -->
        <g stroke="rgba(46,29,14,0.18)" stroke-width="0.09">
          <path d="M 3 22 C 12 26, 20 34, 25 46" fill="none" />
          <path d="M 2 42 C 14 46, 24 56, 30 66" fill="none" />
          <path d="M 2 64 C 18 68, 30 78, 38 90" fill="none" />
          <path d="M 8 30 C 16 34, 22 42, 27 52" fill="none" />
          <path d="M 6 80 C 20 84, 32 90, 42 98" fill="none" />
        </g>
      </svg>
      <!-- 月光罩在木台上（冷白斜照，替代暖灯） -->
      <div class="moonlight" />
    </div>

    <!-- ═══ 信纸（个人信息都在信上） ═══ -->
    <div class="letter">
      <div class="avatar"><img :src="currentAvatar" alt="云曦" /></div>
      <div class="name">云曦</div>
      <div class="sig">{{ signature }}</div>
      <div class="tag">INTP</div>
      <div class="letter-divider" />
      <div class="together">与娅娅相识的第 {{ daysTogether }} 天</div>
      <div class="mood" :class="{ empty: !mood, locked: !loggedIn }" title="点水洼也能写心情">
        {{ mood || "✎ 写一句今天的心情…" }}
      </div>
      <!-- 火漆印 -->
      <div class="wax" title="StellaHaven">S</div>
    </div>

    <!-- ═══ 墨水瓶（装着碎星） ═══ -->
    <div class="inkwell" title="墨水里浮着星">
      <i v-for="n in 5" :key="n" class="ink-star" :style="{
        left: 22 + (n * 13) % 56 + '%',
        top: 30 + (n * 17) % 48 + '%',
        animationDelay: n * 1.3 + 's',
      }" />
    </div>

    <!-- ═══ 板缝间的一洼雨水（星子倒映，点水喝涟漪写心情） ═══ -->
    <div class="pool" @click="pokePool" title="点水面，写一句心情">
      <i v-for="(s, i) in poolStars" :key="i" class="pool-star" :style="{
        left: s.left, top: s.top,
        width: s.size + 'px', height: s.size + 'px',
        animationDelay: s.delay, animationDuration: s.dur,
      }" />
      <span v-for="r in ripples" :key="r.id" class="ripple" :style="{ left: r.x + 'px', top: r.y + 'px' }" />
    </div>

    <!-- Live2D 挂件（Miku） -->
    <div class="shinano">
      <Live2dWidget v-if="homeSettings.live2d" @poke="showTarotBubble" />
    </div>
    <Transition name="bubble">
      <div v-if="tarotBubble" class="tarot-bubble">
        <div class="tb-name">🃏 今日牌 · {{ todayCard[0] }}</div>
        <div class="tb-mean">{{ todayCard[1] }}</div>
      </div>
    </Transition>

    <button v-if="loggedIn" class="bg-btn" title="主页设置" @click="setBg">⚙</button>
    <div class="date-line">{{ dateLine }}</div>
  </div>
</template>

<style scoped>
.home { position: relative; height: 100%; overflow: hidden; }
.bg-img {
  position: absolute; inset: 0;
  background-size: cover; background-position: center;
  opacity: 0.34; pointer-events: none;
}
/* 夜海调罩层：把任何背景图统一进「夜海」色系，海才立得住 */
.sea-tint {
  position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(160deg, rgba(10,32,54,0.25) 0%, rgba(8,24,42,0.45) 55%, rgba(5,16,30,0.6) 100%);
  mix-blend-mode: multiply;
}
.sea-glow {
  position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(ellipse 55% 40% at 72% 38%, rgba(120,170,215,0.12), transparent 70%);
}
.stars { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }

/* ── 木栈台：右缘渐隐入海 ── */
.deck {
  position: absolute; inset: 0; pointer-events: none;
  mask-image: linear-gradient(to right, #000 38%, rgba(0,0,0,0.5) 60%, transparent 86%);
  -webkit-mask-image: linear-gradient(to right, #000 38%, rgba(0,0,0,0.5) 60%, transparent 86%);
}
.deck svg { width: 100%; height: 100%; display: block; }
.moonlight {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse 60% 45% at 30% 30%, rgba(201,212,232,0.14), transparent 70%),
    linear-gradient(115deg, rgba(201,212,232,0.10) 0%, transparent 45%);
}

/* ── 信纸：米白微斜，不是卡片是信 ── */
.letter {
  position: absolute;
  left: 6%; top: 10%;
  width: 460px;
  padding: 50px 58px 60px;
  background:
    radial-gradient(ellipse at 20% 10%, rgba(255,252,244,0.5), transparent 55%),
    linear-gradient(160deg, #f2e8d2 0%, #ecdfc3 55%, #e2d2b0 100%);
  border-radius: 4px;
  transform: rotate(-1.8deg);
  box-shadow:
    0 1px 0 rgba(255,255,255,0.35) inset,
    0 18px 44px rgba(0,0,0,0.55),
    0 3px 10px rgba(0,0,0,0.4);
  text-align: center;
  animation: letter-in 700ms cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes letter-in {
  from { opacity: 0; transform: rotate(-1.8deg) translateY(16px); }
  to { opacity: 1; transform: rotate(-1.8deg) translateY(0); }
}
.avatar img {
  width: 88px; height: 88px; border-radius: 50%;
  border: 2px solid rgba(120, 90, 58, 0.5);
  object-fit: cover;
  box-shadow: 0 0 0 5px rgba(120, 90, 58, 0.12);
}
.name {
  margin-top: 14px; font-size: 27px; font-weight: 600;
  letter-spacing: 6px; color: #3a2c1c;
}
.sig {
  margin-top: 9px; font-size: 14.5px; letter-spacing: 2px;
  color: #7a6244; font-style: italic;
}
.tag {
  display: inline-block; margin-top: 12px; padding: 2px 13px;
  font-size: 11.5px; letter-spacing: 3px;
  color: #a06b7c; border: 1px solid rgba(160, 107, 124, 0.45);
  border-radius: 999px;
}
.letter-divider {
  width: 58%; margin: 20px auto 0;
  border-bottom: 1px dashed rgba(120, 90, 58, 0.35);
}
.together { margin-top: 18px; font-size: 13.5px; color: #6b5236; letter-spacing: 1px; }
.mood { margin-top: 12px; font-size: 12.5px; color: #8a7350; }
.mood.empty { font-style: italic; }
/* 火漆印：樱粉 */
.wax {
  position: absolute; right: 34px; bottom: 30px;
  width: 54px; height: 54px; border-radius: 50%;
  background: radial-gradient(circle at 34% 30%, #f0b8cf 0%, #e8a0bf 38%, #c97e9e 78%, #b06084 100%);
  box-shadow:
    0 2px 6px rgba(0,0,0,0.35),
    0 0 0 3px rgba(232,160,191,0.25),
    0 1px 2px rgba(255,255,255,0.4) inset;
  color: rgba(255, 248, 250, 0.92);
  font-size: 24px; font-weight: 700; font-family: Georgia, serif;
  display: flex; align-items: center; justify-content: center;
  transform: rotate(9deg);
  text-shadow: 0 1px 2px rgba(120, 40, 70, 0.5);
}

/* ── 墨水瓶：碎星浮在墨水里（信纸右侧，避开 Miku 席位） ── */
.inkwell {
  position: absolute;
  left: calc(6% + 492px); top: 48%;
  width: 56px; height: 68px;
  background:
    radial-gradient(ellipse at 50% 88%, #0a1626 0%, #12263e 55%, rgba(30,52,78,0.6) 100%);
  border-radius: 8px 8px 14px 14px;
  border: 1.5px solid rgba(201, 212, 232, 0.28);
  box-shadow: 0 6px 18px rgba(0,0,0,0.5);
}
.inkwell::before {
  content: "";
  position: absolute; left: 16%; right: 16%; top: -12px; height: 14px;
  background: linear-gradient(180deg, rgba(40,60,88,0.9), rgba(22,38,60,0.95));
  border-radius: 4px 4px 0 0;
  border: 1.5px solid rgba(201, 212, 232, 0.28);
  border-bottom: none;
}
.ink-star {
  position: absolute;
  width: 2.5px; height: 2.5px; border-radius: 50%;
  background: #dce6f5;
  box-shadow: 0 0 4px rgba(220, 230, 245, 0.8);
  animation: ink-twinkle 3.5s ease-in-out infinite;
}
@keyframes ink-twinkle {
  0%, 100% { opacity: 0.25; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.15); }
}

/* ── 水洼：木板间一洼雨水（锚在信纸下方，小屏自动收小） ── */
.pool {
  position: absolute;
  left: 4%; bottom: 5%;
  width: 310px; height: 135px;
  background: radial-gradient(ellipse at 42% 40%, #12283e 0%, #0b1a2c 52%, rgba(10,20,34,0.4) 78%, transparent 100%);
  border-radius: 46% 54% 52% 48% / 58% 44% 56% 42%;
  cursor: pointer;
  overflow: hidden;
}
.pool-star {
  position: absolute; border-radius: 50%;
  background: rgba(220, 230, 245, 0.85);
  filter: blur(0.6px);
  animation: pool-twinkle 4s ease-in-out infinite;
}
@keyframes pool-twinkle {
  0%, 100% { opacity: 0.12; }
  50% { opacity: 0.7; }
}
.ripple {
  position: absolute;
  width: 10px; height: 10px;
  border-radius: 50%;
  border: 1.5px solid rgba(201, 212, 232, 0.65);
  transform: translate(-50%, -50%);
  animation: ripple-out 1.5s ease-out forwards;
  pointer-events: none;
}
@keyframes ripple-out {
  from { width: 8px; height: 5px; opacity: 0.9; }
  to { width: 190px; height: 100px; opacity: 0; }
}

/* ── Live2D 挂件位 ── */
.shinano {
  position: absolute; right: 24px; bottom: 0;
  width: 420px; height: 560px; z-index: 8;
}
@media (max-width: 768px) {
  .shinano { width: 62vw; height: 46%; right: -4%; }
  .letter { z-index: 10; }
}

/* ── 塔罗气泡 ── */
.tarot-bubble {
  position: absolute; right: 452px; top: 10%;
  max-width: 250px; padding: 14px 18px;
  background: rgba(27, 31, 42, 0.75);
  backdrop-filter: blur(14px);
  border: 1px solid var(--accent-dim);
  border-radius: 14px 14px 4px 14px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  z-index: 30; pointer-events: none;
}
.bubble-enter-active, .bubble-leave-active { transition: all 350ms cubic-bezier(0.22, 1, 0.36, 1); }
.bubble-enter-from, .bubble-leave-to { opacity: 0; transform: translateY(10px) scale(0.96); }
.tb-name { font-size: 14px; font-weight: 600; color: var(--sakura); letter-spacing: 1px; }
.tb-mean { margin-top: 6px; font-size: 13px; color: var(--text-lo); line-height: 1.6; }

/* ── 齿轮 / 日期行 ── */
.bg-btn {
  position: absolute; right: 18px; bottom: 16px; z-index: 20;
  width: 34px; height: 34px; border-radius: 50%;
  border: 1px solid var(--accent-dim);
  background: color-mix(in srgb, var(--bg-panel) 78%, transparent);
  color: var(--text-lo); font-size: 15px; cursor: pointer;
  transition: all 250ms;
}
.bg-btn:hover { color: var(--accent); transform: rotate(40deg); }
.date-line {
  position: absolute; left: 22px; bottom: 18px;
  font-size: 12.5px; color: var(--text-faint);
  letter-spacing: 1px; pointer-events: none;
}
.locked { cursor: default !important; opacity: 0.75; }
</style>
