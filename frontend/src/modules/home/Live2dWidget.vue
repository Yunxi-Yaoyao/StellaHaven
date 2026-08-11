<script setup lang="ts">
// Live2D 挂件：Miku（Cubism 4，自带眨眼/呼吸/物理摆动/Idle 动作）
// pixi-live2d-display 渲染；戳她 → 比心 + 播报今日塔罗
import { ref, onMounted, onUnmounted } from "vue";
import * as PIXI from "pixi.js";
// pixi-live2d-display 在 import 时就检查 Live2D 运行时（缺 cubism2 运行时会直接炸路由），
// 所以必须先把两个运行时脚本挂上 window，再动态 import 它。

const emit = defineEmits<{ poke: [] }>();
const host = ref<HTMLElement | null>(null);
// 热区透视（#zones 开启）：把点击分区画在她身上给老婆校准
const showZones = typeof location !== "undefined" && location.hash.includes("zones");
const debugZones = ref<{ x: number; y: number; w: number; h: number; label: string; color: string }[]>([]);
let app: PIXI.Application | null = null;
let ro: ResizeObserver | null = null;
let idleTimer: number | undefined;
let onFocusMove: ((e: PointerEvent) => void) | null = null;

// 生命周期钩子必须在 setup 同步阶段注册（onMounted 是 async 的，await 之后注册会丢失）
onUnmounted(() => {
  if (idleTimer !== undefined) clearInterval(idleTimer);
  if (onFocusMove) window.removeEventListener("pointermove", onFocusMove);
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
    // 高清屏不糊的关键：buffer 按 devicePixelRatio 放大，autoDensity 保持 CSS 尺寸不变
    resolution: window.devicePixelRatio || 1,
    autoDensity: true,
  });
  el.appendChild(app.view as HTMLCanvasElement);
  app.view.style.width = "100%";
  app.view.style.height = "100%";

  const model = await Live2DModel.from("/assets/miku-l2d/miku.model3.json", {
    autoInteract: false, // 自带的视线映射在这模型 3500×8888 的巨型坐标系里会退化，自己实现
  });
  app.stage.addChild(model as any);
  // 永久隐藏水印部件（模型自带的归属文字）。事件只有 beforeModelUpdate（没有 after 版），
  // 在 model.update() 折叠部件透明度之前压掉，每帧生效。
  const HIDE_PARTS = ["Part17", "Part18"];
  // 程序化小动作：呼吸 + 极缓的轻晃（add 叠加，不和视线/动作打架）
  const animT0 = performance.now();
  // Q版形态：连续值 0..1，每帧直写参数（不走单槽表情系统——否则悬停表情会把形态顶掉）
  let formV = 0;
  // 哭哭：眯眼+低头+嘴角下撇（单眯眼 918px 太弱被无视，组合出击）
  let cryV = 0;
  model.internalModel.on("beforeModelUpdate", () => {
    const core = model.internalModel.coreModel as any;
    for (const id of HIDE_PARTS) core.setPartOpacityById(id, 0);
    core.setParameterValueById("EyeL_Squint", cryV);
    core.setParameterValueById("EyeR_Squint", cryV);
    core.addParameterValueById("ParamAngleY", cryV * 9); // 委屈低头
    core.addParameterValueById("ParamMouthForm", cryV * -0.7); // 嘴角下撇
    const t = (performance.now() - animT0) / 1000;
    core.addParameterValueById("ParamBreath", Math.sin(t * 1.6) * 0.5 + 0.5); // 0..1 慢呼吸
    core.addParameterValueById("ParamAngleZ", Math.sin(t * 0.5) * 1.2); // ±1.2° 轻晃
    core.addParameterValueById("ParamBodyAngleZ", Math.sin(t * 0.5 + 1.2) * 0.8);
    // Q版形态参数（大小变 = Param131+136）
    core.setParameterValueById("Param131", formV);
    core.setParameterValueById("Param136", formV);
  });
  // 调试句柄：控制台可用 __miku.expression("脸红") 等直接调戏她
  (window as any).__miku = model;
  (window as any).__mikuApp = app;
  (window as any).__mikuForm = () => formV;
  (window as any).__mikuState = () => ({ hovering, idleActive, faceExpr, cryV });

  // 适配容器：先按逻辑盒缩放定位，再渲染出来量「真实内容像素盒」精修——
  // 逻辑盒含大量不可见留白，直接对齐它人会偏（老婆截图实锤：人物缩在右下）。
  const CROP_TOP = 0.6;
  const CHIBI_SHIFT_Y = 180; // Q版整体下移量
  let normalY = 0;
  // 内容盒：画布上真实非透明像素的边界（CSS 像素），热区和悬停都锚它
  let contentBox = { x: 0, y: 0, w: 1, h: 1 };
  const measureContent = () => {
    if (!app) return;
    const gl = (app.renderer as any).gl as WebGLRenderingContext;
    // 冻结时钟量静止姿势——活体在动，量运动的模型会得到抖动盒（热区跟着抖）
    model.internalModel.update(0, 100000);
    app.renderer.render(app.stage);
    const w = gl.drawingBufferWidth;
    const h = gl.drawingBufferHeight;
    const buf = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    // 密度检测：alpha>60 才算实色；一行/列要 >10 个实色点才算内容（抗微光残影）
    // 注意：readPixels 的 y 轴原点在左下角——必须翻转成屏幕坐标，否则内容盒上下颠倒
    const ALPHA = 60;
    const MIN_DENSE = 10;
    const rowDense = new Array(h).fill(0);
    const colDense = new Array(w).fill(0);
    for (let gy = 0; gy < h; gy += 2) {
      const y = h - 1 - gy; // GL→屏幕翻转
      for (let x = 0; x < w; x += 2) {
        if (buf[(gy * w + x) * 4 + 3] > ALPHA) { rowDense[y]++; colDense[x]++; }
      }
    }
    let minY = 0, maxY = h - 1, minX = 0, maxX = w - 1;
    while (minY < h && rowDense[minY] <= MIN_DENSE) minY++;
    while (maxY > minY && rowDense[maxY] <= MIN_DENSE) maxY--;
    while (minX < w && colDense[minX] <= MIN_DENSE) minX++;
    while (maxX > minX && colDense[maxX] <= MIN_DENSE) maxX--;
    if (minY >= maxY || minX >= maxX) return;
    const res = app.renderer.resolution; // readPixels 是设备像素，除回 CSS 像素
    contentBox = { x: minX / res, y: minY / res, w: (maxX - minX) / res, h: (maxY - minY) / res };
  };
  // 形态补间：同一时钟同时驱动 formV（大小变）和 model.y（下移）——严格同步，不闪现不分离
  let formTween: { fromV: number; toV: number; fromY: number; toY: number; t0: number; dur: number } | null = null;
  const tweenForm = (toV: number, toY: number, dur: number) => {
    formTween = { fromV: formV, toV, fromY: model.y, toY, t0: performance.now(), dur };
  };
  PIXI.Ticker.shared.add(() => {
    if (!formTween) return;
    const k = Math.min((performance.now() - formTween.t0) / formTween.dur, 1);
    const e = 1 - Math.pow(1 - k, 3); // easeOutCubic
    formV = formTween.fromV + (formTween.toV - formTween.fromV) * e;
    model.y = formTween.fromY + (formTween.toY - formTween.fromY) * e;
    if (k >= 1) { formTween = null; measureContent(); } // 变形落定后重测内容盒
  });
  const fit = () => {
    const w = el.clientWidth;
    const h = el.clientHeight;
    model.scale.set(1);
    model.position.set(0, 0);
    const lb = model.getLocalBounds();
    if (!lb.width || !lb.height) return;
    const s = Math.min(w / lb.width, h / (lb.height * CROP_TOP)) * 0.98;
    model.scale.set(s);
    // 先粗放到画布中央，再量真实内容精修：内容水平居中、头顶贴 2%
    const b = model.getBounds();
    model.x += (w - b.width) / 2 - b.x;
    model.y += h * 0.02 - b.y;
    measureContent();
    model.x += (w - contentBox.w) / 2 - contentBox.x;
    model.y += h * 0.02 - contentBox.y;
    measureContent();
    formTween = null; // 硬取景取消补间
    normalY = model.y;
  };
  fit();
  // 贴图加载后再校正两轮（第 1 帧 + 兜底 800ms）
  requestAnimationFrame(fit);
  setTimeout(fit, 800);
  // ResizeObserver 加守卫：尺寸没变不重排（否则会把进行中的补间抹掉）
  let lastW = el.clientWidth;
  let lastH = el.clientHeight;
  ro = new ResizeObserver(() => {
    if (el.clientWidth === lastW && el.clientHeight === lastH) return;
    lastW = el.clientWidth;
    lastH = el.clientHeight;
    fit();
  });
  ro.observe(el);

  // 加载完立刻播放待机动作
  try { model.motion("Idle"); } catch { /* noop */ }

  // 热区透视模式：每 500ms 把当前分区画成框（与点击判定共用 ZONES + 内容盒同一份数学）
  if (showZones) {
    window.setInterval(() => {
      const rect = (z: { x0: number; x1: number; y0: number; y1: number }, label: string, color: string) =>
        ({ x: contentBox.x + z.x0 * contentBox.w, y: contentBox.y + z.y0 * contentBox.h,
           w: (z.x1 - z.x0) * contentBox.w, h: (z.y1 - z.y0) * contentBox.h, label, color });
      debugZones.value = [
        rect(ZONES.head, "头·Q版", "rgba(232,160,191,.30)"),
        rect(ZONES.chest, "胸口·哭哭", "rgba(140,180,255,.30)"),
        rect(ZONES.armL, "手臂·比心", "rgba(150,230,180,.30)"),
        rect(ZONES.armR, "手臂·比心", "rgba(150,230,180,.30)"),
      ];
    }, 500);
  }

  // 视线跟踪（自实现）：以她的脸为锚点算方向，带距离衰减——
  // 鼠标在她脸附近 = 正视前方，偏离越多看得越多，全屏都跟随
  const canvas = app.view as HTMLCanvasElement;
  onFocusMove = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    const b = model.getBounds();
    const faceX = r.left + b.x + b.width / 2;
    const faceY = r.top + b.y + b.height * 0.15; // 脸 ≈ 可见区顶部往下 15%
    const dx = e.clientX - faceX;
    const dy = e.clientY - faceY;
    const len = Math.hypot(dx, dy) || 1;
    const strength = Math.min(len / 300, 1); // 300px 内线性过渡，避免贴脸时乱飘
    // 注意：focusController 的 y 轴与屏幕相反（库原生实现就是 -sin），这里必须取负
    model.internalModel.focusController.focus((dx / len) * strength, (-dy / len) * strength);
  };
  window.addEventListener("pointermove", onFocusMove);

  // ── 互动系统 ─────────────────────────────────────────────
  // 分层设计：形态（Q版=formV 直写参数）与脸（表情槽）完全独立，互不顶掉。
  // 点击=开关（常驻），悬停/冷落=状态（即时覆盖，退出回常驻脸）。
  const exprMgr = () => (model.internalModel.motionManager as any).expressionManager;
  const setExpr = (name: string) => { try { exprMgr()?.setExpression(name); } catch { /* 表情不存在就跳过 */ } };
  // reset 时清掉预约位：否则加载中的表情会在 reset 之后落地「抢尸」（异步竞态实测）
  const resetExpr = () => { try { const m = exprMgr(); if (m) m.reserveExpressionIndex = -1; m?.resetExpression(); } catch { /* noop */ } };

  let faceExpr: string | null = null; // 常驻表情（比心/唱歌/葱开关）
  let hovering = false;
  let idleActive = false;
  let lastActive = Date.now();

  const applyFace = () => {
    // 常驻脸（用户戳出来的）最优先；冷落前倾是「端着等人哄」状态，压过悬停鼓脸
    if (faceExpr) setExpr(faceExpr);
    else if (idleActive) setExpr("前倾");
    else if (hovering) setExpr("鼓脸");
    else resetExpr();
  };

  // 分区热区：锚定「真实内容盒」的分数（像素实测，不是逻辑盒！），跟着她的身体走。
  // 分数按老婆截图解剖标定：下巴0.27/领口0.34/胸口0.40-0.55/袖子0.40-0.76/头宽0.29-0.68
  const ZONES = {
    head: { x0: 0.37, x1: 0.76, y0: 0.0, y1: 0.12 },
    chest: { x0: 0.45, x1: 0.68, y0: 0.39, y1: 0.53 },
    armL: { x0: 0.18, x1: 0.42, y0: 0.45, y1: 0.78 },
    armR: { x0: 0.78, x1: 0.97, y0: 0.45, y1: 0.78 },
  };
  const hitZone = (z: { x0: number; x1: number; y0: number; y1: number }, px: number, py: number) => {
    const fx = (px - contentBox.x) / contentBox.w;
    const fy = (py - contentBox.y) / contentBox.h;
    return fx >= z.x0 && fx <= z.x1 && fy >= z.y0 && fy <= z.y1;
  };

  // 整体命中（悬停/长按用）：真实内容盒
  const pointOnFigure = (x: number, y: number) =>
    x >= contentBox.x && x <= contentBox.x + contentBox.w && y >= contentBox.y && y <= contentBox.y + contentBox.h;

  // 戳一戳：普通态 摸头=变Q版 / 戳身体=比心开关；Q版态 点她=变回原版。都播报塔罗
  // 长按 0.5s = 甩葱（举葱+摇头开关），长按触发后吞掉随后的 click 防连击
  let pressTimer: number | undefined;
  let longPressed = false;
  canvas.addEventListener("pointerdown", (e) => {
    longPressed = false;
    const r = canvas.getBoundingClientRect();
    if (!pointOnFigure(e.clientX - r.left, e.clientY - r.top)) return; // 点在空白不算
    pressTimer = window.setTimeout(() => {
      longPressed = true;
      faceExpr = faceExpr === "葱" ? null : "葱";
      try { model.motion("Shake"); } catch { /* noop */ }
      applyFace();
      emit("poke");
    }, 500);
  });
  const cancelPress = () => { if (pressTimer !== undefined) clearTimeout(pressTimer); };
  canvas.addEventListener("pointerup", cancelPress);
  canvas.addEventListener("pointercancel", cancelPress);

  // 双击 = 唱歌开关（单击的第二次 detail=2 跳过，防止比心跟着翻转）
  canvas.addEventListener("dblclick", () => {
    lastActive = Date.now();
    idleActive = false;
    faceExpr = faceExpr === "唱歌" ? null : "唱歌";
    applyFace();
    emit("poke");
  });

  canvas.addEventListener("click", (e) => {
    if (longPressed) { longPressed = false; return; } // 长按已处理，吞掉这次点击
    if (e.detail >= 2) return; // 双击的第二次单击不处理（交给 dblclick）
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    lastActive = Date.now();
    idleActive = false;
    if (formV > 0.5) {
      // Q版态：点她变回原版（形态+位置同步滑回）
      tweenForm(0, normalY, 1000);
      applyFace();
      emit("poke");
      return;
    }
    // 分区（锚定模型包围盒）：头顶=Q版 / 胸口=哭哭 / 手臂=比心 / 其余=只报塔罗
    if (hitZone(ZONES.head, px, py)) {
      tweenForm(1, normalY + CHIBI_SHIFT_Y, 1100);
      try { model.motion("Nod"); } catch { /* noop */ }
    } else if (hitZone(ZONES.chest, px, py)) {
      cryV = cryV ? 0 : 1; // 胸口：哭哭开关
    } else if (hitZone(ZONES.armL, px, py) || hitZone(ZONES.armR, px, py)) {
      faceExpr = faceExpr === "比心" ? null : "比心"; // 手臂：比心开关
      try { model.motion("Tilt"); } catch { /* noop */ }
    }
    applyFace();
    emit("poke");
  });

  // 悬停鼓脸：指针停在她身上就气鼓鼓（状态级，移开回常驻脸；不再顶掉Q版形态）
  // 冷落前倾中：悬停不会立刻消她的「等人哄」，要悬满 5 秒才消（中途挪走重新计时）
  let idleHoverTimer: number | undefined;
  const clearIdleHover = () => { if (idleHoverTimer !== undefined) { clearTimeout(idleHoverTimer); idleHoverTimer = undefined; } };
  canvas.addEventListener("pointermove", (e) => {
    lastActive = Date.now();
    const r = canvas.getBoundingClientRect();
    const over = pointOnFigure(e.clientX - r.left, e.clientY - r.top);
    if (over && !hovering) {
      hovering = true;
      if (idleActive) {
        // 前倾中：开始计 5 秒「哄她」时长
        clearIdleHover();
        idleHoverTimer = window.setTimeout(() => {
          if (idleActive && hovering) { idleActive = false; applyFace(); }
        }, 5000);
        // 前倾优先级高于鼓脸，这里不用 applyFace（她保持前倾）
      } else {
        applyFace();
      }
    } else if (!over && hovering) {
      hovering = false;
      clearIdleHover();
      applyFace();
    }
  });
  canvas.addEventListener("pointerleave", () => {
    clearIdleHover();
    if (hovering) { hovering = false; applyFace(); }
  });

  // 冷落触发：30 秒没人理她，她前倾凑过来看你；待机动作 Idle/Sway 轮流续命
  let idleAlt = false;
  idleTimer = window.setInterval(() => {
    try {
      if (!(model.internalModel.motionManager as any).playing) {
        model.motion(idleAlt ? "Sway" : "Idle");
        idleAlt = !idleAlt;
      }
    } catch { /* noop */ }
    if (!idleActive && !hovering && Date.now() - lastActive > 30000) {
      idleActive = true;
      applyFace();
    }
  }, 5000);
});
</script>

<template>
  <div ref="host" class="live2d-host" title="戳戳 Miku">
    <div
      v-for="(z, i) in debugZones"
      :key="i"
      class="zone-debug"
      :style="{ left: z.x + 'px', top: z.y + 'px', width: z.w + 'px', height: z.h + 'px', background: z.color }"
    >{{ z.label }}</div>
  </div>
</template>

<style scoped>
.live2d-host {
  width: 100%;
  height: 100%;
  cursor: pointer;
  position: relative;
}
.zone-debug {
  position: absolute;
  pointer-events: none;
  border: 1px dashed rgba(255, 255, 255, 0.6);
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-shadow: 0 1px 2px #000;
  z-index: 10;
}
</style>
