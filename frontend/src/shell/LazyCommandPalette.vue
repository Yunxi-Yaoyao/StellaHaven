<script setup lang="ts">
// Keep the global activation listeners small; the palette graph loads on intent.
import { defineAsyncComponent, onMounted, onBeforeUnmount, ref, watch } from 'vue';
const props = defineProps<{ modules?: { label: string; path: string }[] }>();
const Palette = defineAsyncComponent(() => import('../modules/notes/CommandPalette.vue'));
const requested = ref(false);
const pendingOpen = ref(false);
const palette = ref<{ show(): void; close(): void } | null>(null);
function requestOpen() {
  if (palette.value) return; // The loaded palette owns its existing listeners.
  pendingOpen.value = true;
  requested.value = true;
}
function key(event: KeyboardEvent) {
  if (palette.value) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !event.altKey) {
    event.preventDefault();
    pendingOpen.value = !pendingOpen.value;
    requested.value = true;
  } else if (event.key === 'Escape' && pendingOpen.value) {
    event.preventDefault();
    pendingOpen.value = false;
  }
}
watch(palette, instance => { if (instance && pendingOpen.value) instance.show(); }, { flush: 'post' });
onMounted(() => {
  window.addEventListener('keydown', key);
  window.addEventListener('stella:command-palette', requestOpen);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', key);
  window.removeEventListener('stella:command-palette', requestOpen);
});
</script>
<template>
  <span v-if="!palette" class="command-palette-root" hidden></span>
  <Palette v-if="requested" ref="palette" :modules="props.modules" />
</template>
