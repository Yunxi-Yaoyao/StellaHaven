<script setup lang="ts">
// 通用下拉栏：Stella 主题的自定义下拉菜单，替代原生 select。
// 原生 select 的下拉选项面板是浏览器白底黑字，CSS 改不了主题，所以用 pop-menu 风格自绘。
import { ref, computed, onMounted, onUnmounted } from "vue";
import Icon from "../shell/Icon.vue";

const props = defineProps<{
  modelValue: string | number | boolean | null;
  options: { value: string | number | boolean; label: string; desc?: string }[];
}>();

const emit = defineEmits<{ "update:modelValue": [v: string | number | boolean] }>();

const open = ref(false);
const selected = computed(() => props.options.find((o) => o.value === props.modelValue)?.label || "—");

function pick(v: string | number | boolean) {
  emit("update:modelValue", v);
  open.value = false;
}

function onDocClick() { open.value = false; }
onMounted(() => document.addEventListener("click", onDocClick));
onUnmounted(() => document.removeEventListener("click", onDocClick));
</script>

<template>
  <div class="dd" @click.stop>
    <button class="dd-btn" type="button" @click="open = !open">
      <span class="dd-label">{{ selected }}</span>
      <Icon name="chevron" :size="12" class="dd-arrow" :class="{ rot: open }" />
    </button>
    <transition name="dd-fade">
      <div v-if="open" class="dd-menu">
        <button
          v-for="o in options"
          :key="String(o.value)"
          type="button"
          class="dd-item"
          :class="{ active: o.value === modelValue }"
          @click="pick(o.value)"
        >
          <span class="dd-item-label">{{ o.label }}</span>
          <span v-if="o.desc" class="dd-item-desc">{{ o.desc }}</span>
        </button>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.dd { position: relative; }
.dd-btn {
  display: inline-flex; align-items: center; gap: 6px; justify-content: space-between;
  padding: 7px 11px; background: var(--bg-panel); border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm); color: var(--text-hi); font-size: 13px; cursor: pointer;
  min-width: 140px; transition: border-color var(--transition);
}
.dd-btn:hover { border-color: var(--accent-dim); }
.dd-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dd-arrow { color: var(--text-faint); transition: transform 0.2s; flex-shrink: 0; }
.dd-arrow.rot { transform: rotate(90deg); }
.dd-menu {
  position: absolute; top: calc(100% + 4px); left: 0; z-index: 30;
  background: var(--bg-raised); border: 1px solid rgba(255,255,255,0.1);
  border-radius: var(--radius-sm); padding: 4px; min-width: 150px;
  max-height: 320px; overflow-y: auto; box-shadow: 0 6px 20px rgba(0,0,0,0.45);
  display: flex; flex-direction: column; gap: 2px;
}
.dd-item {
  display: flex; align-items: baseline; gap: 8px; width: 100%;
  background: transparent; border: none; color: var(--text-lo); text-align: left;
  padding: 6px 10px; font-size: 12.5px; border-radius: 4px; cursor: pointer;
}
.dd-item:hover { background: var(--bg-base); color: var(--text-hi); }
.dd-item.active { color: var(--accent); }
.dd-item-label { white-space: nowrap; }
.dd-item-desc { font-size: 11px; color: var(--text-faint); margin-left: auto; white-space: nowrap; }
.dd-fade-enter-active, .dd-fade-leave-active { transition: opacity 0.15s; }
.dd-fade-enter-from, .dd-fade-leave-to { opacity: 0; }
</style>
