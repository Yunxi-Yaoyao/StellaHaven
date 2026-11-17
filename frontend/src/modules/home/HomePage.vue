<script setup lang="ts">
// One stable trigger survives theme changes; the appearance store stays shared.
import { computed, defineAsyncComponent, onDeactivated, onBeforeUnmount, ref, watch } from "vue";
import { homeSettings, settingsOpen, bgManagerOpen } from "./settings";
import { loggedIn } from "./auth";
const SettingsPanel = defineAsyncComponent(() => import("../../shell/SettingsPanel.vue"));
const requested = ref(settingsOpen.value);
watch(settingsOpen, open => { if (open) requested.value = true; });
const HomeClassic = defineAsyncComponent(() => import("./themes/HomeClassic.vue"));
const HomeDaybreak = defineAsyncComponent(() => import("./themes/HomeDaybreak.vue"));
const Active = computed(() => homeSettings.theme === "classic" ? HomeClassic : HomeDaybreak);
function closeOverlays() { settingsOpen.value = false; bgManagerOpen.value = false; }
onDeactivated(closeOverlays);
onBeforeUnmount(closeOverlays);
</script>

<template>
  <div class="home-page" :data-home-theme="homeSettings.theme">
    <component :is="Active" />
    <SettingsPanel v-if="requested && loggedIn" :key="'home-panel'" />
  </div>
</template>

<style scoped>
.home-page { position:relative; width:100%; height:100%; min-height:100%; background:var(--bg-base); color:var(--text-hi); }
</style>
