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
  theme: string;      // daybreak | coastline | classic | nightfall(=daybreak 暗皮肤)
  particles: Particles;
  bgImage: string;    // 背景图 URL（空串=无背景图）
  bgCrop: BgCrop;     // 源图裁剪区（分数）——窗口 resize 内容不变，只缩放
  siteTitle: string;  // 大标题（破晓/夜泊）
  signature: string;  // 签名句
  meetDate: string;   // 相识起点 YYYY-MM-DD（天数计数器用它算）
  live2d: boolean;    // Miku 挂件总开关
  avatar: string;     // 用户头像 URL——侧栏和签名卡都借用它（唯一来源）
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
  siteTitle: localStorage.getItem("stella_site_title") || "StellaHaven",
  signature: localStorage.getItem("stella_signature") || "夜有星辰，晨有曦光。",
  meetDate: localStorage.getItem("stella_meet_date") || "2026-05-31",
  live2d: localStorage.getItem("stella_live2d") !== "off",
  avatar: localStorage.getItem("stella_avatar") || "/avatar.png",
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
watch(() => homeSettings.siteTitle, (v) => localStorage.setItem("stella_site_title", v));
watch(() => homeSettings.signature, (v) => localStorage.setItem("stella_signature", v));
watch(() => homeSettings.meetDate, (v) => localStorage.setItem("stella_meet_date", v));
watch(() => homeSettings.live2d, (v) => localStorage.setItem("stella_live2d", v ? "on" : "off"));
watch(() => homeSettings.avatar, (v) => localStorage.setItem("stella_avatar", v));
