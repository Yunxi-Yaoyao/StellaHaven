import { reactive } from "vue";

// 全局轻提示：模块级响应式列表，组件销毁了 toast 也能弹完
export interface ToastItem {
  id: number;
  text: string;
}

export const toasts = reactive<ToastItem[]>([]);
let seq = 0;

export function toast(text: string, ms = 2600) {
  const id = ++seq;
  toasts.push({ id, text });
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id);
    if (i >= 0) toasts.splice(i, 1);
  }, ms);
}
