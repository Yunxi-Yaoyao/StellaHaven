// 主页设置 store：主题/粒子氛围/背景图。reactive + localStorage 持久化，切换免刷新。
// 模式参考 imsyy/home 的 persist paths（只有登记的字段落盘），组件是我们手写。
import { reactive, ref, watch } from "vue";

/** 设置面板开关（各主题的齿轮都往这写） */
export const settingsOpen = ref(false);
/** 背景图管理浮窗开关 */
export const bgManagerOpen = ref(false);

export const DEFAULT_HOME_BG = "/assets/homebg/default-bg-kimono.jpeg";

/** 粒子氛围：星空点点（夜色）/ 浮尘微粒（白日）/ 樱花飘落 / off=关闭 */
export type Particles = "stars" | "motes" | "sakura" | "off";

export interface BgCrop { cx: number; cy: number; w: number; h: number; }

export interface HomeSettings {
  theme: string;      // daybreak | coastline | classic
  particles: Particles;
  bgImage: string;    // 背景图 URL（空串=无背景图）
  bgCrop: BgCrop;     // 源图裁剪区（分数）——窗口 resize 内容不变，只缩放
}

// 旧字段迁移：stella_home_stars(on/off) → particles(stars/off)
function loadParticles(): Particles {
  const v = localStorage.getItem("stella_home_particles");
  if (v === "stars" || v === "motes" || v === "sakura" || v === "off") return v;
  return localStorage.getItem("stella_home_stars") === "off" ? "off" : "stars";
}

export const homeSettings = reactive<HomeSettings>({
  theme: localStorage.getItem("stella_home_theme") || "daybreak",
  particles: loadParticles(),
  bgImage: migrateBg(localStorage.getItem("stella_home_bg")),
  bgCrop: loadCrop(),
});

// 旧默认路径 → 附件系统里的默认背景
function migrateBg(v: string | null): string {
  if (v === null) return DEFAULT_HOME_BG;
  if (v === "" || v === "/assets/bg-kimono.jpeg") return v === "" ? "" : DEFAULT_HOME_BG;
  return v;
}
function loadCrop(): BgCrop {
  try {
    const v = JSON.parse(localStorage.getItem("stella_home_bgcrop") || "");
    if (v && v.w > 0 && v.h > 0) return v;
  } catch { /* noop */ }
  return { cx: 0.5, cy: 0.5, w: 1, h: 1 };
}

watch(() => homeSettings.theme, (v) => localStorage.setItem("stella_home_theme", v));
watch(() => homeSettings.particles, (v) => localStorage.setItem("stella_home_particles", v));
watch(() => homeSettings.bgImage, (v) => localStorage.setItem("stella_home_bg", v));
watch(() => homeSettings.bgCrop, (v) => localStorage.setItem("stella_home_bgcrop", JSON.stringify(v)), { deep: true });
