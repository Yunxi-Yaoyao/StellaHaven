<script setup lang="ts">
// 通用粒子画布：星空点点 / 浮尘微粒 / 樱花飘落 三态（主页设置下拉切换）
// 三个主题共用；mode 变化时自动重启循环
import { ref, watch, onMounted, onUnmounted } from "vue";

export type ParticleMode = "stars" | "motes" | "sakura";

const props = defineProps<{ mode: ParticleMode }>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
let raf = 0;
let cleanup: (() => void) | null = null;

/* ── 星空点点（夜色主题：横向微漂 + 明灭） ── */
function startStars(ctx: CanvasRenderingContext2D, w: () => number, h: () => number) {
  const stars = Array.from({ length: 70 }, () => ({
    x: Math.random() * w(), y: Math.random() * h(),
    r: 0.6 + Math.random() * 1.6,
    vx: (Math.random() - 0.5) * 0.08, vy: (Math.random() - 0.5) * 0.06,
    tw: Math.random() * Math.PI * 2,
  }));
  return () => {
    for (const s of stars) {
      s.x += s.vx; s.y += s.vy; s.tw += 0.02;
      if (s.x < 0) s.x = w(); if (s.x > w()) s.x = 0;
      if (s.y < 0) s.y = h(); if (s.y > h()) s.y = 0;
      const alpha = 0.25 + 0.35 * Math.abs(Math.sin(s.tw));
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = Math.random() < 0.02 ? `rgba(232,160,191,${alpha})` : `rgba(201,212,232,${alpha})`;
      ctx.fill();
    }
  };
}

/* ── 浮尘微粒（白日主题：缓降 + 微光） ── */
function startMotes(ctx: CanvasRenderingContext2D, w: () => number, h: () => number) {
  const motes = Array.from({ length: 46 }, () => ({
    x: Math.random() * w(), y: Math.random() * h(),
    r: 0.8 + Math.random() * 2.2,
    vx: (Math.random() - 0.5) * 0.12, vy: 0.05 + Math.random() * 0.14,
    tw: Math.random() * Math.PI * 2,
  }));
  return () => {
    for (const s of motes) {
      s.x += s.vx; s.y += s.vy; s.tw += 0.015;
      if (s.x < 0) s.x = w(); if (s.x > w()) s.x = 0;
      if (s.y > h()) s.y = -4;
      const alpha = 0.10 + 0.22 * Math.abs(Math.sin(s.tw));
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = Math.random() < 0.03 ? `rgba(232,160,191,${alpha})` : `rgba(140,170,200,${alpha})`;
      ctx.fill();
    }
  };
}

/* ── 樱花飘落（旋转 + 左右摇曳 + 下落） ── */
function startSakura(ctx: CanvasRenderingContext2D, w: () => number, h: () => number) {
  const petals = Array.from({ length: 26 }, () => ({
    x: Math.random() * w(), y: Math.random() * h(),
    rx: 2.6 + Math.random() * 2.8,           // 花瓣半宽
    vy: 0.35 + Math.random() * 0.5,          // 下落速度
    swayAmp: 14 + Math.random() * 22,        // 摇曳幅度
    swaySpd: 0.4 + Math.random() * 0.5,      // 摇曳频率
    phase: Math.random() * Math.PI * 2,
    rot: Math.random() * Math.PI * 2,
    rotSpd: (Math.random() - 0.5) * 0.03,
    pink: 0.75 + Math.random() * 0.25,       // 粉色浓度
  }));
  return () => {
    const t = performance.now() / 1000;
    for (const p of petals) {
      p.y += p.vy;
      p.rot += p.rotSpd;
      if (p.y > h() + 12) { p.y = -12; p.x = Math.random() * w(); }
      const px = p.x + Math.sin(t * p.swaySpd + p.phase) * p.swayAmp;
      ctx.save();
      ctx.translate(px, p.y);
      ctx.rotate(p.rot);
      // 花瓣 = 一头略尖的椭圆
      ctx.beginPath();
      ctx.moveTo(0, -p.rx * 1.6);
      ctx.bezierCurveTo(p.rx * 1.3, -p.rx * 0.9, p.rx * 1.1, p.rx * 0.9, 0, p.rx * 1.5);
      ctx.bezierCurveTo(-p.rx * 1.1, p.rx * 0.9, -p.rx * 1.3, -p.rx * 0.9, 0, -p.rx * 1.6);
      ctx.fillStyle = `rgba(232,160,191,${0.55 * p.pink})`;
      ctx.fill();
      ctx.restore();
    }
  };
}

function boot() {
  teardown();
  const canvas = canvasEl.value;
  if (!canvas) return;
  const ctx = canvas.getContext("2d")!;
  let w = (canvas.width = canvas.offsetWidth);
  let h = (canvas.height = canvas.offsetHeight);
  const onResize = () => {
    w = canvas.width = canvas.offsetWidth;
    h = canvas.height = canvas.offsetHeight;
  };
  window.addEventListener("resize", onResize);
  const draw =
    props.mode === "stars" ? startStars(ctx, () => w, () => h) :
    props.mode === "sakura" ? startSakura(ctx, () => w, () => h) :
    startMotes(ctx, () => w, () => h);
  const tick = () => {
    ctx.clearRect(0, 0, w, h);
    draw();
    raf = requestAnimationFrame(tick);
  };
  tick();
  cleanup = () => window.removeEventListener("resize", onResize);
}
function teardown() {
  cancelAnimationFrame(raf);
  cleanup?.();
  cleanup = null;
}

onMounted(boot);
watch(() => props.mode, boot);
onUnmounted(teardown);
</script>

<template>
  <canvas ref="canvasEl" class="particles" />
</template>

<style scoped>
.particles {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
