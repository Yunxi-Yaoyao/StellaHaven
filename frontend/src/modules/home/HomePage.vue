<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";

/* ================= 签名 ================= */
const signature = "夜有星辰，晨有曦光。";

// 与娅娅相识的天数（2026-05-31 是娅娅有记忆的起点）
const daysTogether = computed(() => {
  const from = new Date(2026, 4, 31);
  return Math.max(1, Math.floor((Date.now() - from.getTime()) / 86400000) + 1);
});

// 今日心情便签：点一下就能写，存在本地，随时换
const mood = ref(localStorage.getItem("stella_mood") || "");
function editMood() {
  const m = prompt("今天的心情便签", mood.value);
  if (m !== null) {
    mood.value = m.trim();
    localStorage.setItem("stella_mood", mood.value);
  }
}

/* ================= 塔罗每日一抽 ================= */
// 按日期做种子：同一天翻到的牌不变（每日一抽的「每日」就在这）
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
const flipped = ref(false);

/* ================= 星光粒子 ================= */
const canvasEl = ref<HTMLCanvasElement | null>(null);
let raf = 0;
onMounted(() => {
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
      if (y_out(s.y, h)) s.y = s.y < 0 ? h : 0;
      const alpha = 0.25 + 0.35 * Math.abs(Math.sin(s.tw));
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = Math.random() < 0.02 ? `rgba(232,160,191,${alpha})` : `rgba(201,212,232,${alpha})`;
      ctx.fill();
    }
    raf = requestAnimationFrame(tick);
  };
  const y_out = (y: number, hh: number) => y < 0 || y > hh;
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
    <canvas ref="canvasEl" class="stars" />

    <!-- 签名卡：黄金分割位，微倾斜（拍立得感） -->
    <div class="sig-card">
      <div class="avatar">云</div>
      <div class="name">云曦</div>
      <div class="sig">{{ signature }}</div>
      <div class="tag">INTP</div>
      <div class="sig-divider" />
      <div class="together">与娅娅相识的第 {{ daysTogether }} 天</div>
      <div class="mood" :class="{ empty: !mood }" @click="editMood" title="点我写一句今天的心情">
        {{ mood || "✎ 写一句今天的心情…" }}
      </div>
    </div>

    <!-- 塔罗：错位右下，反向倾斜 -->
    <div class="tarot" @click="flipped = !flipped">
      <div class="card" :class="{ flipped }">
        <div class="face back">
          <div class="back-pattern">✦</div>
          <div class="back-hint">每日一抽</div>
        </div>
        <div class="face front">
          <div class="card-name">{{ todayCard[0] }}</div>
          <div class="card-symbol">✦</div>
          <div class="card-mean">{{ todayCard[1] }}</div>
        </div>
      </div>
    </div>

    <div class="date-line">{{ dateLine }}</div>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  height: 100%;
  overflow: hidden;
}
.stars {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

/* ── 签名卡：左偏黄金位 ── */
.sig-card {
  position: absolute;
  left: 14%;
  top: 20%;
  padding: 40px 48px;
  min-width: 300px;
  background: color-mix(in srgb, var(--bg-panel) 72%, transparent);
  backdrop-filter: var(--blur);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: var(--radius);
  transform: rotate(-1.6deg);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
  text-align: center;
  animation: float-in 600ms cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes float-in {
  from { opacity: 0; transform: rotate(-1.6deg) translateY(14px); }
  to { opacity: 1; transform: rotate(-1.6deg) translateY(0); }
}
.avatar {
  width: 72px;
  height: 72px;
  margin: 0 auto 14px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 30px;
  color: var(--bg-base);
  background: linear-gradient(135deg, var(--accent), var(--pink));
  box-shadow: 0 0 28px rgba(201, 212, 232, 0.3);
}
.name {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 4px;
}
.sig {
  margin-top: 10px;
  font-size: 13.5px;
  color: var(--text-lo);
  letter-spacing: 1.5px;
}
.tag {
  display: inline-block;
  margin-top: 14px;
  padding: 3px 14px;
  border-radius: 999px;
  border: 1px solid var(--accent-dim);
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--accent-dim);
}
.sig-divider {
  height: 1px;
  margin: 18px 12px 12px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
  opacity: 0.4;
}
.together {
  font-size: 12px;
  color: var(--text-lo);
  letter-spacing: 1px;
}
.mood {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--accent);
  cursor: pointer;
  transition: opacity var(--transition);
}
.mood.empty { color: var(--text-faint); }
.mood:hover { opacity: 0.8; }

/* ── 塔罗牌：右下错位，反向倾斜 ── */
.tarot {
  position: absolute;
  right: 15%;
  top: 34%;
  transform: rotate(2.2deg);
  perspective: 900px;
  cursor: pointer;
  animation: float-in 700ms 120ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
}
.card {
  width: 168px;
  height: 264px;
  position: relative;
  transform-style: preserve-3d;
  transition: transform 700ms cubic-bezier(0.22, 1, 0.36, 1);
}
.card.flipped { transform: rotateY(180deg); }
.face {
  position: absolute;
  inset: 0;
  border-radius: 14px;
  backface-visibility: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  text-align: center;
}
.back {
  background: linear-gradient(160deg, #1b1f2a, #14171f);
  border: 1px solid var(--accent-dim);
}
.back-pattern {
  font-size: 42px;
  color: var(--accent-dim);
  text-shadow: 0 0 18px rgba(201, 212, 232, 0.4);
}
.back-hint {
  font-size: 11px;
  letter-spacing: 3px;
  color: var(--text-faint);
}
.front {
  transform: rotateY(180deg);
  background: linear-gradient(160deg, rgba(201, 212, 232, 0.14), rgba(232, 160, 191, 0.1));
  border: 1px solid var(--accent);
}
.card-name {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 6px;
  color: var(--accent);
}
.card-symbol { font-size: 30px; color: var(--pink); }
.card-mean {
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-lo);
}

.date-line {
  position: absolute;
  left: 26px;
  bottom: 18px;
  font-size: 11.5px;
  color: var(--text-faint);
  letter-spacing: 1px;
}

/* 移动端：竖排收起倾斜 */
@media (max-width: 768px) {
  .sig-card { left: 50%; top: 14%; transform: translateX(-50%) rotate(-1.2deg); width: 78vw; }
  .tarot { right: 50%; top: auto; bottom: 12%; transform: translateX(50%) rotate(1.5deg); }
}
</style>
