// 主页设置 store：主题/粒子氛围/背景图。reactive + localStorage 持久化，切换免刷新。
// 模式参考 imsyy/home 的 persist paths（只有登记的字段落盘），组件是我们手写。
import { reactive, ref, watch } from "vue";

/** 设置面板开关（各主题的齿轮都往这写） */
export const settingsOpen = ref(false);
/** 背景图管理浮窗开关 */
export const bgManagerOpen = ref(false);

export const DEFAULT_HOME_BG = "/assets/homebg/default-bg-kimono-1920.webp";

/** 站点背景（管理员设置）；有效账号背景由 auth.displayBg 按账号→站点→默认解析。 */
export const siteBackground = ref("");

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
  theme: ['daybreak', 'nightfall', 'classic'].includes(localStorage.getItem('stella_home_theme') || '') ? localStorage.getItem('stella_home_theme')! : 'daybreak',
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

// Failed fields stay in memory and remain visible until their own write/readback succeeds.
export const homeSaveErrors = reactive<Record<string, string>>({});
export const homeSaved = ref(false);
const localFields = [
  ['theme', 'stella_home_theme', '主题'], ['particles', 'stella_home_particles', '氛围粒子'],
  ['bgImage', 'stella_home_bg', '背景'], ['bgCrop', 'stella_home_bgcrop', '背景取景'],
  ['siteTitle', 'stella_site_title', '大标题'], ['signature', 'stella_signature', '签名'],
  ['meetDate', 'stella_meet_date', '相识起点'], ['live2d', 'stella_live2d', '挂件'],
  ['avatar', 'stella_avatar', '头像'],
] as const;
function persistHomeField([field,key,label]: typeof localFields[number]) {
  const value = field === 'bgCrop' ? JSON.stringify(homeSettings[field]) : field === 'live2d' ? (homeSettings[field] ? 'on' : 'off') : String(homeSettings[field]);
  try {
    localStorage.setItem(key, value);
    if (localStorage.getItem(key) !== value) throw new Error('readback mismatch');
    delete homeSaveErrors[field]; homeSaved.value = true;
  } catch {
    homeSaveErrors[field] = `${label}未保存到当前设备，输入已保留。请检查浏览器存储后重试。`;
  }
}
export function retryHomeSave() {
  for (const entry of localFields) if (homeSaveErrors[entry[0]]) persistHomeField(entry);
}
for (const entry of localFields) watch(() => homeSettings[entry[0]], () => persistHomeField(entry), {deep:true});
