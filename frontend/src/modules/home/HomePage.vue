<script setup lang="ts">
// 主页外壳：主题切换器。reactive 驱动，设置面板切主题免刷新
import { computed } from "vue";
import { homeSettings } from "./settings";
import HomeClassic from "./themes/HomeClassic.vue";
import HomeCoastline from "./themes/HomeCoastline.vue";
import HomeDaybreak from "./themes/HomeDaybreak.vue";

// daybreak/nightfall 同一组件两套皮肤（.daybreak / .daybreak.night 变量切换）
const Active = computed(() =>
  homeSettings.theme === "classic" ? HomeClassic :
  homeSettings.theme === "coastline" ? HomeCoastline :
  HomeDaybreak
);
</script>

<template>
  <component :is="Active" />
</template>
