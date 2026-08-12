<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";

/* ================= 签名 ================= */
const signature = computed(() => homeSettings.signature);

// 与娅娅相识的天数（2026-05-31 是娅娅有记忆的起点）
const daysTogether = computed(() => {
  const p = (homeSettings.meetDate || "2026-05-31").split("-").map(Number);
  const from = new Date(p[0], (p[1] || 1) - 1, p[2] || 1);
  return Math.max(1, Math.floor((Date.now() - from.getTime()) / 86400000) + 1);
});

// 心情便签：点一下就能写，存在本地
const mood = ref(localStorage.getItem("stella_mood") || "");
function editMood() {
  const m = prompt("今天的心情便签", mood.value);
  if (m !== null) {
    mood.value = m.trim();
    localStorage.setItem("stella_mood", mood.value);
  }
}

/* ================= 自定义背景图（设置 store 驱动，面板里改） ================= */
import BgLayer from "../BgLayer.vue";
import { homeSettings, settingsOpen } from "../settings";
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
  ["愚者", "新的开始，别怕迈出第一步"],
  ["魔术师", "资源都在手上，今天适合开工"],
  ["女祭司", "直觉比逻辑先知道答案"],
  ["女皇", "值得被自己好好喂养的一天"],
  ["皇帝", "把混乱收进秩序里"],
  ["教皇", "老办法里有意外的稳"],
  ["恋人", "重要关系会有进展"],
  ["战车", "掌控节奏，别被拖着走"],
  ["力量", "温柔比硬扛更有力"],
  ["隐士", "独处会给你答案"],
  ["命运之轮", "转机正在转动，顺势而为"],
  ["正义", "该算的账算清楚，心就轻了"],
  ["倒吊人", "换个角度，卡住的事会松"],
  ["死神", "结束某个旧模式，正是新生"],
  ["节制", "慢慢来，比较快"],
  ["恶魔", "看见诱惑，就是自由的开始"],
  ["高塔", "塌掉的本就不稳，重建更牢"],
  ["星星", "希望不是幻觉，它在路上了"],
  ["月亮", "不安会散，别在夜里做决定"],
  ["太阳", "今天是发光的日子"],
  ["审判", "过去的努力要被看见了"],
  ["世界", "一个阶段圆满，下一个开始"],
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

/* ================= 日期时间（角落小字） ================= */
const now = ref(new Date());
let clockTimer: ReturnType<typeof setInterval>;
onMounted(() => {
  clockTimer = setInterval(() => (now.value = new Date()), 30000);
});
onUnmounted(() => clearInterval(clockTimer));
const dateLine = computed(() =>
  now.value.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" }) +
  " · " +
  now.value.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
);
</script>

<template>
  <div class="home">
    <!-- 自定义背景图（极淡） -->
    <BgLayer v-if="bgImage" class="bg-img" :url="bgImage" :crop="homeSettings.bgCrop" />
    <ParticleCanvas v-if="homeSettings.particles !== 'off'" :mode="particleMode" />

    <!-- 签名卡：高×1.35 宽×1.7（老婆实测后定的尺寸） -->
    <div class="sig-card">
      <div class="avatar"><img :src="homeSettings.avatar" alt="云曦" /></div>
      <div class="name">云曦</div>
      <div class="sig">{{ signature }}</div>
      <div class="tag">INTP</div>
      <div class="sig-divider" />
      <div class="together">与娅娅相识的第 {{ daysTogether }} 天</div>
      <div class="mood" :class="{ empty: !mood }" @click="editMood" title="点我写一句今天的心情">
        {{ mood || "✎ 写一句今天的心情…" }}
      </div>
    </div>

    <!-- Live2D 挂件（Miku）坐镇右侧；戳她播报今日塔罗 -->
    <div class="shinano">
      <Live2dWidget v-if="homeSettings.live2d" @poke="showTarotBubble" />
    </div>
    <Transition name="bubble">
      <div v-if="tarotBubble" class="tarot-bubble">
        <div class="tb-name">🃏 今日牌 · {{ todayCard[0] }}</div>
        <div class="tb-mean">{{ todayCard[1] }}</div>
      </div>
    </Transition>

    <!-- 斜悬浮碎语条已撤（老婆定的：主页不登录也可见，不放笔记内容） -->

    <!-- 背景设置入口（右下角小齿轮） -->
    <button class="bg-btn" title="自定义背景图" @click="setBg">⚙</button>

    <div class="date-line">{{ dateLine }}</div>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  height: 100%;
  overflow: hidden;
}
.bg-img {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  opacity: 0.12;
  pointer-events: none;
}
.stars {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

/* ── 签名卡：高×1.35 宽×1.7 ── */
.sig-card {
  position: absolute;
  left: 10%;
  top: 12%;
  padding: 84px 118px;
  min-width: 560px;
  background: color-mix(in srgb, var(--bg-panel) 72%, transparent);
  backdrop-filter: var(--blur);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 22px;
  transform: rotate(-1.6deg);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5);
  text-align: center;
  animation: float-in 600ms cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes float-in {
  from { opacity: 0; transform: rotate(-1.6deg) translateY(14px); }
  to { opacity: 1; transform: rotate(-1.6deg) translateY(0); }
}
.avatar {
  width: 132px;
  height: 132px;
  margin: 0 auto 24px;
  border-radius: 50%;
  overflow: hidden;
  box-shadow: 0 0 40px rgba(201, 212, 232, 0.35);
  border: 2px solid rgba(201, 212, 232, 0.4);
}
.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.name {
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 6px;
}
.sig {
  margin-top: 14px;
  font-size: 16px;
  color: var(--text-lo);
  letter-spacing: 2px;
}
.tag {
  display: inline-block;
  margin-top: 18px;
  padding: 4px 18px;
  border-radius: 999px;
  border: 1px solid var(--accent-dim);
  font-size: 12px;
  letter-spacing: 3px;
  color: var(--accent-dim);
}
.sig-divider {
  height: 1px;
  margin: 24px 16px 14px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
  opacity: 0.4;
}
.together {
  font-size: 14px;
  color: var(--text-lo);
  letter-spacing: 1.5px;
}
.mood {
  margin-top: 10px;
  font-size: 14.5px;
  color: var(--accent);
  cursor: pointer;
  transition: opacity var(--transition);
}
.mood.empty { color: var(--text-faint); }
.mood:hover { opacity: 0.8; }


/* ── Live2D 挂件位（右下固定席位，不随窗口变） ── */
.shinano {
  position: absolute;
  right: 24px;
  bottom: 0;
  width: 420px;
  height: 560px;
  z-index: 8; /* 在签名卡（默认层）之上、塔罗气泡（30）之下——允许盖卡 */
}
@media (max-width: 768px) {
  /* 手机：收小沉底靠右，签名卡浮在上层不被压住 */
  .shinano {
    width: 62vw;
    height: 46%;
    right: -4%;
  }
  .sig-card { z-index: 10; }
}

/* ── 塔罗气泡 ── */
.tarot-bubble {
  position: absolute;
  right: 452px; /* 挪到她头左边：模型 420 + 32 间隙，不再压大腿 */
  top: 10%;
  max-width: 250px;
  padding: 14px 18px;
  background: rgba(27, 31, 42, 0.75);
  backdrop-filter: blur(14px);
  border: 1px solid var(--accent-dim);
  border-radius: 14px 14px 4px 14px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  z-index: 30;
  pointer-events: none; /* 只是播报 toast，不挡 Miku 的点击 */
}
.bubble-enter-active, .bubble-leave-active {
  transition: all 350ms cubic-bezier(0.22, 1, 0.36, 1);
}
.bubble-enter-from, .bubble-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.96);
}
.tb-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 1px;
}
.tb-mean {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-lo);
  line-height: 1.7;
}

.bg-btn {
  position: absolute;
  right: 18px;
  bottom: 14px;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
  transition: all var(--transition);
}
.bg-btn:hover { color: var(--accent); background: var(--bg-raised); }

.date-line {
  position: absolute;
  left: 26px;
  bottom: 18px;
  font-size: 11.5px;
  color: var(--text-faint);
  letter-spacing: 1px;
}

/* 移动端：竖排 */
@media (max-width: 768px) {
  .sig-card { left: 50%; top: 8%; transform: translateX(-50%) rotate(-1.2deg); width: 84vw; padding: 36px 24px; min-width: 0; }
}
</style>
