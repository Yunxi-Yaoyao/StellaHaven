import { reactive } from "vue";

// 全局图片放大查看器：任意组件 openLightbox(url) 即可
export const lightbox = reactive({ src: "" as string | null });

export function openLightbox(src: string) {
  lightbox.src = src;
}
export function closeLightbox() {
  lightbox.src = null;
}
