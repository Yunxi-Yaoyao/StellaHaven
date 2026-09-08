import { computed, ref, reactive, watch, type Ref } from "vue";
import { auth } from "./auth";
import { DEFAULT_HOME_BG } from "./settings";

export type Quality = "original" | "compressed1" | "compressed2";
export interface BgMedia {
  url: string;
  status: "missing" | "queued" | "processing" | "ready" | "error";
  poster?: string | null;
  thumbnail?: string | null;
  variants: { original: string; compressed1?: string; compressed2?: string };
  error?: string | null;
  width?: number;
  height?: number;
}
export interface BackgroundEntry {
  id: string; name: string; ext: string; url: string; isDefault: boolean; media?: BgMedia;
}
export const QUALITY_KEY = "stella_home_bg_quality";
export const qualityOptions = [
  { value: "original", label: "原画" },
  { value: "compressed1", label: "压缩1" },
  { value: "compressed2", label: "压缩2" },
];
function validateQuality(v: unknown): Quality {
  return v === "original" || v === "compressed2" ? v : "compressed1";
}
function savedQuality(): Quality {
  try { return validateQuality(localStorage.getItem(QUALITY_KEY)); } catch { return "compressed1"; }
}
export const quality = ref<Quality>(savedQuality());
export function setBackgroundQuality(v: unknown) { quality.value = validateQuality(v); }
watch(quality, (v) => {
  const valid = validateQuality(v);
  if (v !== valid) quality.value = valid;
  try { localStorage.setItem(QUALITY_KEY, valid); } catch { /* private browsing */ }
}, { flush: "sync" });

export const backgroundMedia = reactive<Record<string, BgMedia>>({});
export const backgroundEntries = ref<BackgroundEntry[]>([]);
const pending = new Map<string, Promise<BgMedia | null>>();
const optimizing = new Map<string, Promise<BgMedia | null>>();
let entriesPending: Promise<BackgroundEntry[]> | null = null;
const active = new Map<string, { count: number; timer?: ReturnType<typeof setTimeout>; polls: number }>();
// Only known local asset URLs. Never proxy arbitrary remote or protocol-relative URLs.
export function isLocalBackground(url: string) { return /^\/assets\/homebg\/[^?#]+(?:[?#].*)?$/.test(url) && !url.includes(".."); }
export function storeBackgroundMedia(media: BgMedia) {
  backgroundMedia[media.url] = media;
  schedule(media.url);
}
export function backgroundThumbnail(url: string): string {
  const m = backgroundMedia[url];
  return m?.thumbnail || m?.poster || (url === DEFAULT_HOME_BG ? DEFAULT_HOME_BG : "");
}
export function backgroundSource(url: string): string {
  return backgroundMedia[url]?.variants?.[quality.value] || url;
}
function failed(url: string, error: unknown) {
  storeBackgroundMedia({ ...backgroundMedia[url], url, status: "error", variants: backgroundMedia[url]?.variants || { original: url }, error: error instanceof Error ? error.message : "背景处理失败" });
}
export async function loadBackgroundEntries(): Promise<BackgroundEntry[]> {
  if (!auth.me) return [];
  if (entriesPending) return entriesPending;
  entriesPending = (async () => {
    const r = await fetch("/homebg/");
    if (!r.ok) throw new Error(`背景图库加载失败 (${r.status})`);
    const entries: BackgroundEntry[] = await r.json();
    backgroundEntries.value = entries;
    for (const e of entries) if (e.media) storeBackgroundMedia(e.media);
    return entries;
  })();
  try { return await entriesPending; } finally { entriesPending = null; }
}
export function reloadBackgroundMedia(url: string): Promise<BgMedia | null> {
  if (!isLocalBackground(url)) return Promise.resolve(null);
  const current = pending.get(url);
  if (current) return current;
  const request = (async () => {
    try {
      const r = await fetch(`/homebg/media?url=${encodeURIComponent(url)}`);
      if (!r.ok) throw new Error(`背景信息加载失败 (${r.status})`);
      const m: BgMedia = await r.json();
      storeBackgroundMedia({ ...m, url });
      return backgroundMedia[url]!;
    } catch (e) { failed(url, e); return null; }
    finally { pending.delete(url); }
  })();
  pending.set(url, request);
  return request;
}
export function optimizeBackground(url: string): Promise<BgMedia | null> {
  if (!auth.me || !isLocalBackground(url)) return Promise.resolve(null);
  const current = optimizing.get(url);
  if (current) return current;
  const request = (async () => {
    try {
      const entries = await loadBackgroundEntries();
      if (!auth.me) return null;
      const entry = entries.find(e => e.url === url);
      if (!entry) return null; // bundled defaults outside the managed library stay original
      const r = await fetch(`/homebg/${encodeURIComponent(entry.id)}/optimize`, { method: "POST" });
      if (!r.ok) throw new Error(`背景处理失败 (${r.status})`);
      const m: BgMedia = await r.json();
      storeBackgroundMedia({ ...m, url });
      const consumer = active.get(url);
      if (consumer) consumer.polls = 0;
      return await reloadBackgroundMedia(url);
    } catch (e) { failed(url, e); return null; }
    finally { optimizing.delete(url); }
  })();
  optimizing.set(url, request);
  return request;
}
function schedule(url: string) {
  const a = active.get(url);
  if (!a || a.timer || !auth.me || a.polls >= 60) return;
  if (!["queued", "processing"].includes(backgroundMedia[url]?.status || "")) return;
  a.timer = setTimeout(async () => {
    a.timer = undefined;
    if (!active.has(url) || !auth.me || !["queued", "processing"].includes(backgroundMedia[url]?.status || "")) return;
    a.polls++;
    await reloadBackgroundMedia(url);
    schedule(url);
  }, 3000);
}
/** Shared media state. Passing an empty URL suspends this consumer. Watch cleanup
 * releases polling on URL change, auth change, effect-scope stop or unmount. */
export function useBackgroundMedia(url: Readonly<Ref<string>>) {
  const media = computed(() => backgroundMedia[url.value] || null);
  const source = computed(() => isLocalBackground(url.value) && !media.value && quality.value !== "original" ? "" : backgroundSource(url.value));
  const poster = computed(() => media.value?.poster || media.value?.thumbnail || "");
  const status = computed(() => media.value?.status || "missing");
  watch([url, () => auth.me?.id], ([value], _, cleanup) => {
    if (!isLocalBackground(value)) return;
    const a = active.get(value) || { count: 0, polls: 0 };
    a.count++;
    active.set(value, a);
    let live = true;
    cleanup(() => {
      live = false;
      if (--a.count === 0) { clearTimeout(a.timer); active.delete(value); }
    });
    void (async () => {
      const m = backgroundMedia[value] || await reloadBackgroundMedia(value);
      if (!live) return;
      if (m?.status === "missing" && auth.me) await optimizeBackground(value);
      if (live) schedule(value);
    })();
  }, { immediate: true });
  return { media, source, poster, quality, status };
}
