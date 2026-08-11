<script setup lang="ts">
// Live2D 挂件：Miku（Cubism 4，自带眨眼/呼吸/物理摆动/Idle 动作）
// pixi-live2d-display 渲染；戳她 → 比心 + 播报今日塔罗
import { ref, onMounted, onUnmounted } from "vue";
import * as PIXI from "pixi.js";
// pixi-live2d-display 在 import 时就检查 Live2D 运行时（缺 cubism2 运行时会直接炸路由），
// 所以必须先把两个运行时脚本挂上 window，再动态 import 它。

const emit = defineEmits<{ poke: [] }>();
const host = ref<HTMLElement | null>(null);
let app: PIXI.Application | null = null;
let ro: ResizeObserver | null = null;

// 生命周期钩子必须在 setup 同步阶段注册（onMounted 是 async 的，await 之后注册会丢失）
onUnmounted(() => {
  ro?.disconnect();
  app?.destroy(true);
  app = null;
});

function loadScript(src: string, globalName: string): Promise<void> {
  return new Promise((res, rej) => {
    if ((window as any)[globalName]) return res();
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => res();
    s.onerror = () => rej(new Error("load fail " + src));
    document.head.appendChild(s);
  });
}

onMounted(async () => {
  // Miku 是 Cubism 4 模型 → 走 cubism4 专用入口（全量包 import 时会强制检查 cubism2 运行时）
  await loadScript("/live2dcubismcore.min.js", "Live2DCubismCore");

  const { Live2DModel } = await import("pixi-live2d-display/cubism4");
  // 关键：不显式注册 Ticker，模型只渲染第一帧——没有眨眼/呼吸/动作（「死板」的根因）
  Live2DModel.registerTicker(PIXI.Ticker);

  const el = host.value!;
  app = new PIXI.Application({
    width: el.clientWidth,
    height: el.clientHeight,
    backgroundAlpha: 0,
    autoStart: true,
    antialias: true,
    // pixi 默认给 Application 造独立 ticker，而 pixi-live2d-display 把模型更新挂到 Ticker.shared——
    // 不用 sharedTicker 的话模型永远收不到 update（画面静止的第二层根因）
    sharedTicker: true,
  });
  el.appendChild(app.view as HTMLCanvasElement);
  app.view.style.width = "100%";
  app.view.style.height = "100%";

  const model = await Live2DModel.from("/assets/miku-l2d/miku.model3.json", {
    autoInteract: true, // 视线/头自动跟鼠标（移动端跟触摸）
  });
  app.stage.addChild(model as any);
  // 调试句柄：控制台可用 __miku.expression("脸红") 等直接调戏她
  (window as any).__miku = model;
  (window as any).__mikuApp = app;

  // 适配容器：水平居中、底部贴到 98% 高度。
  // 注意：model.width 是「变换后」的宽度（含 scale），反复 fit 会振荡发散——
  // 必须每次先重置变换，用 getLocalBounds()（不含 scale）做计算基准。
  const fit = () => {
    const w = el.clientWidth;
    const h = el.clientHeight;
    model.scale.set(1);
    model.position.set(0, 0);
    const lb = model.getLocalBounds();
    if (!lb.width || !lb.height) return;
    const s = Math.min(w / lb.width, h / lb.height) * 0.98;
    model.scale.set(s);
    const b = model.getBounds();
    model.x += (w - b.width) / 2 - b.x;
    model.y += h * 0.98 - (b.y + b.height);
  };
  fit();
  // 贴图加载后再校正两轮（第 1 帧 + 兜底 800ms）
  requestAnimationFrame(fit);
  setTimeout(fit, 800);
  ro = new ResizeObserver(fit);
  ro.observe(el);

  // 戳一戳：比心 + 播报（由外面弹塔罗气泡）
  (app.view as HTMLCanvasElement).addEventListener("click", () => {
    try {
      model.expression("比心");
    } catch {
      /* 表情不存在就安静跳过 */
    }
    emit("poke");
  });
});
</script>

<template>
  <div ref="host" class="live2d-host" title="戳戳 Miku" />
</template>

<style scoped>
.live2d-host {
  width: 100%;
  height: 100%;
  cursor: pointer;
}
</style>
