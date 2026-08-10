<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";

/* ================= 签名 ================= */
const signature = "夜有星辰，晨有曦光。";

// 与娅娅相识的天数（2026-05-31 是娅娅有记忆的起点）
const daysTogether = computed(() => {
  const from = new Date(2026, 4, 31);
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

/* ================= 自定义背景图（极淡铺在星光下） ================= */
// 默认用和服少女（老婆给的图，存在全局资源区，不走笔记附件）
const bgImage = ref(localStorage.getItem("stella_home_bg") ?? "/assets/bg-kimono.jpeg");
function setBg() {
  const url = prompt("背景图链接（留空清除）", bgImage.value);
  if (url !== null) {
    bgImage.value = url.trim();
    localStorage.setItem("stella_home_bg", bgImage.value);
  }
}

/* ================= Live2D 挂件（右侧大摆件，兼每日塔罗播报） ================= */
const tarotBubble = ref(false);
let bubbleTimer: ReturnType<typeof setTimeout> | null = null;

function showTarotBubble() {
  tarotBubble.value = true;
  if (bubbleTimer) clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => (tarotBubble.value = false), 6000);
}

function initLive2d() {
  // 核心库 + 挂件壳要按顺序加载（壳才注册 window.L2Dwidget）
  const core = document.createElement("script");
  core.src = "/live2d/L2Dwidget.0.min.js";
  core.onload = () => {
    const shell = document.createElement("script");
    shell.src = "/live2d/L2Dwidget.min.js";
    shell.onload = () => {
      // @ts-expect-error 全局挂件库
      const w = window.L2Dwidget;
      if (!w) return;
      w.init({
        model: { jsonPath: "/live2d/shizuku/shizuku.model.json", scale: 1 },
        display: {
          position: "right",
          width: 300,   // 大摆件，填充右侧
          height: 420,
          hOffset: 40,
          vOffset: -10,
        },
        mobile: { show: true, scale: 0.6 },
        react: { opacityDefault: 0.85, opacityOnHover: 1 },
      });
      // 点挂件 → 播报今日塔罗
      setTimeout(() => {
        const canvas = document.getElementById("live2dcanvas");
        canvas?.addEventListener("click", showTarotBubble);
      }, 800);
    };
    document.head.appendChild(shell);
  };
  document.head.appendChild(core);
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

/* ================= 星光粒子 ================= */
const canvasEl = ref<HTMLCanvasElement | null>(null);
let raf = 0;
onMounted(() => {
  initLive2d();
  const canvas = canvasEl.value!;
  const ctx = canvas.getContext("2d")!;
  let w = (canvas.width = canvas.offsetWidth);
  let h = (canvas.height = canvas.offsetHeight);

  interface Star { x: number; y: number; r: number; vx: number; vy: number; tw: number; }
  const stars: Star[] = Array.from({ length: 70 }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: 0.6 + Math.random() * 1.6,
    vx: (Math.random() - 0.5) * 0.08,
    vy: (Math.random() - 0.5) * 0.06,
    tw: Math.random() * Math.PI * 2,
  }));

  const onResize = () => {
    w = canvas.width = canvas.offsetWidth;
    h = canvas.height = canvas.offsetHeight;
  };
  window.addEventListener("resize", onResize);

  const tick = () => {
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      s.x += s.vx;
      s.y += s.vy;
      s.tw += 0.02;
      if (s.x < 0) s.x = w;
      if (s.x > w) s.x = 0;
      if (s.y < 0) s.y = h;
      if (s.y > h) s.y = 0;
      const alpha = 0.25 + 0.35 * Math.abs(Math.sin(s.tw));
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = Math.random() < 0.02 ? `rgba(232,160,191,${alpha})` : `rgba(201,212,232,${alpha})`;
      ctx.fill();
    }
    raf = requestAnimationFrame(tick);
  };
  tick();

  onUnmounted(() => {
    cancelAnimationFrame(raf);
    window.removeEventListener("resize", onResize);
  });
});

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
    <div v-if="bgImage" class="bg-img" :style="{ backgroundImage: `url(${bgImage})` }" />
    <canvas ref="canvasEl" class="stars" />

    <!-- 签名卡：高×1.35 宽×1.7（老婆实测后定的尺寸） -->
    <div class="sig-card">
      <div class="avatar"><img src="/avatar.png" alt="云曦" /></div>
      <div class="name">云曦</div>
      <div class="sig">{{ signature }}</div>
      <div class="tag">INTP</div>
      <div class="sig-divider" />
      <div class="together">与娅娅相识的第 {{ daysTogether }} 天</div>
      <div class="mood" :class="{ empty: !mood }" @click="editMood" title="点我写一句今天的心情">
        {{ mood || "✎ 写一句今天的心情…" }}
      </div>
    </div>

    <!-- Live2D 挂件（右侧大摆件）；点一下播报今日塔罗 -->
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
