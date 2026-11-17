<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from "vue";
withDefaults(defineProps<{ label: string; portalTarget?: string | HTMLElement }>(),{portalTarget:'body'});
const id = `help-${useId()}`;
const trigger = ref<HTMLButtonElement>();
const panel = ref<HTMLElement>();
const open = ref(false);
const position = ref({ left: "8px", top: "8px" });
let pinned = false;
let restoringFocus = false;
let timer: ReturnType<typeof setTimeout> | undefined;
function cancelClose() {
  clearTimeout(timer);
}
function positionPanel() {
  if (!trigger.value || !panel.value) return;
  const t = trigger.value.getBoundingClientRect(),
    p = panel.value.getBoundingClientRect();
  position.value = {
    left: `${Math.max(8, Math.min(t.left, window.innerWidth - p.width - 8))}px`,
    top: `${Math.max(8, Math.min(t.bottom + 6, window.innerHeight - p.height - 8))}px`,
  };
}
async function show() {
  if (restoringFocus) return;
  cancelClose();
  open.value = true;
  await nextTick();
  positionPanel();
}
function dismiss() {
  cancelClose();
  pinned = false;
  open.value = false;
}
function delayClose() {
  cancelClose();
  timer = setTimeout(() => {
    if (
      !pinned &&
      !panel.value?.contains(document.activeElement) &&
      document.activeElement !== trigger.value
    )
      dismiss();
  }, 140);
}
function toggle() {
  if (pinned) dismiss();
  else {
    pinned = true;
    void show();
  }
}
function outside(e: Event) {
  if (
    !trigger.value?.contains(e.target as Node) &&
    !panel.value?.contains(e.target as Node)
  )
    dismiss();
}
function key(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) {
    e.preventDefault();
    dismiss();
    restoringFocus = true;
    trigger.value?.focus();
    restoringFocus = false;
  }
}
onMounted(() => {
  document.addEventListener("pointerdown", outside);
  document.addEventListener("keydown", key);
  window.addEventListener("resize", positionPanel);
  window.addEventListener("scroll", positionPanel, true);
});
onBeforeUnmount(() => {
  cancelClose();
  document.removeEventListener("pointerdown", outside);
  document.removeEventListener("keydown", key);
  window.removeEventListener("resize", positionPanel);
  window.removeEventListener("scroll", positionPanel, true);
});
</script>
<template>
  <button
    ref="trigger"
    class="help-hint"
    type="button"
    :aria-label="label"
    :aria-expanded="open"
    :aria-describedby="open ? id : undefined"
    :aria-controls="open ? id : undefined"
    @pointerenter="show"
    @pointerleave="delayClose"
    @focus="show"
    @blur="delayClose"
    @click="toggle"
  >
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.6"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6m0-10h.01" stroke-linecap="round" />
    </svg>
  </button>
  <Teleport :to="portalTarget" defer
    ><div
      v-if="open"
      :id="id"
      ref="panel"
      class="help-hint-popover"
      role="tooltip"
      tabindex="0"
      :style="position"
      @pointerenter="cancelClose"
      @pointerleave="delayClose"
      @focusin="cancelClose"
      @focusout="delayClose"
    >
      <slot /></div
  ></Teleport>
</template>
<style>
.help-hint {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  vertical-align: middle;
  width: 36px;
  height: 36px;
  flex: none;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--settings-muted, var(--text-lo));
  cursor: help;
}
.help-hint:hover {
  background: var(--settings-hover, var(--control-hover));
  color: var(--settings-text, var(--text-hi));
}
.help-hint:focus-visible,
.help-hint-popover:focus-visible {
  outline: 2px solid var(--settings-accent, var(--accent));
  outline-offset: 2px;
}
.help-hint-popover {
  position: fixed;
  z-index: 300;
  width: max-content;
  max-width: min(320px, calc(100vw - 16px));
  max-height: min(240px, calc(100dvh - 16px));
  overflow: auto;
  box-sizing: border-box;
  padding: 12px 14px;
  border: 1px solid var(--control-border);
  border-radius: 8px;
  background: var(--bg-raised);
  color: var(--text-hi);
  font:
    14px/1.65 "Inter Variable",
    "PingFang SC",
    "Microsoft YaHei",
    "WenQuanYi Micro Hei",
    system-ui,
    sans-serif;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 30px #0006;
  animation: help-enter 100ms ease-out;
}
@keyframes help-enter {
  from {
    opacity: 0;
    transform: translateY(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@media (max-width: 640px) {
  .help-hint {
    width: 44px;
    height: 44px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .help-hint-popover {
    animation: none;
  }
}
</style>
