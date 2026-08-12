<script setup lang="ts">
// 时光进度条组：今天/本周/本月三条（主题色），今年放说明行。
// 颜色吃主题根的 --prog-* 变量，亮暗主题自动适配。
import { ref, computed, onMounted, onUnmounted } from "vue";

const now = ref(new Date());
let timer: ReturnType<typeof setInterval>;
onMounted(() => { timer = setInterval(() => (now.value = new Date()), 30000); });
onUnmounted(() => clearInterval(timer));

const dayPct = computed(() => {
  const d = now.value;
  return ((d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400) * 100;
});
const weekPct = computed(() => {
  const d = now.value;
  const dayIdx = (d.getDay() + 6) % 7; // 周一=0（中式习惯）
  return ((dayIdx * 86400 + d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / (7 * 86400)) * 100;
});
const monthPct = computed(() => {
  const d = now.value;
  const daysInMonth = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  return (((d.getDate() - 1) * 86400 + d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / (daysInMonth * 86400)) * 100;
});
const yearPct = computed(() => {
  const d = now.value;
  const start = new Date(d.getFullYear(), 0, 1).getTime();
  const end = new Date(d.getFullYear() + 1, 0, 1).getTime();
  return ((d.getTime() - start) / (end - start)) * 100;
});
</script>

<template>
  <div class="tp">
    <div class="tp-row">
      <span class="tp-label">今天</span>
      <div class="tp-track"><div class="tp-fill" :style="{ width: dayPct + '%' }" /></div>
      <span class="tp-pct">{{ dayPct.toFixed(1) }}%</span>
    </div>
    <div class="tp-row">
      <span class="tp-label">本周</span>
      <div class="tp-track"><div class="tp-fill" :style="{ width: weekPct + '%' }" /></div>
      <span class="tp-pct">{{ weekPct.toFixed(1) }}%</span>
    </div>
    <div class="tp-row">
      <span class="tp-label">本月</span>
      <div class="tp-track"><div class="tp-fill" :style="{ width: monthPct + '%' }" /></div>
      <span class="tp-pct">{{ monthPct.toFixed(1) }}%</span>
    </div>
    <div class="tp-cap">今年 {{ yearPct.toFixed(1) }}%</div>
  </div>
</template>

<style scoped>
.tp { width: 100%; }
.tp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.tp-row:first-child { margin-top: 0; }
.tp-label {
  font-size: 11.5px;
  color: var(--prog-label, #7a8fa0);
  width: 28px;
  flex-shrink: 0;
  letter-spacing: 1px;
}
.tp-track {
  flex: 1;
  height: 4.5px;
  border-radius: 3px;
  background: var(--prog-track, rgba(93, 147, 173, 0.18));
  overflow: hidden;
}
.tp-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--prog-from, #7fb3c8), var(--prog-to, #5d93ad));
  transition: width 600ms ease;
}
.tp-pct {
  font-size: 11px;
  color: var(--prog-label, #7a8fa0);
  width: 40px;
  text-align: right;
  flex-shrink: 0;
  letter-spacing: 0.5px;
}
.tp-cap {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--prog-cap, #9aabba);
  letter-spacing: 1px;
}
</style>
