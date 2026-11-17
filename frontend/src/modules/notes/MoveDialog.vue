<script setup lang="ts">
import { computed } from "vue";
import { useNotesStore, buildTree, collectDescendants, type TreeNode } from "../../stores/notes";

const props = defineProps<{ node: TreeNode }>();
const emit = defineEmits<{ done: []; cancel: [] }>();
const store = useNotesStore();

// 候选父级：排除自己 + 自己的后代（循环防护前端先过滤，后端还有硬校验兜底）
const candidates = computed(() => {
  const tree = buildTree(store.docs);
  const excluded = collectDescendants(tree, props.node.id);
  excluded.add(props.node.id);
  const flat: { id: string | null; label: string }[] = [{ id: null, label: "（根级）" }];
  const walk = (nodes: TreeNode[], depth: number) => {
    for (const n of nodes) {
      if (!excluded.has(n.id)) {
        flat.push({ id: n.id, label: "　".repeat(depth) + n.title });
        walk(n.children, depth + 1);
      }
    }
  };
  walk(tree, 0);
  return flat;
});

async function pick(id: string | null) {
  const ok = await store.moveTo(props.node as any, id);
  if (ok) emit("done");
}
</script>

<template>
  <div class="mask" @click.self="emit('cancel')">
    <div class="dialog">
      <div class="head">移动「{{ node.title }}」到…</div>
      <p role="note" style="padding:0 18px;font-size:12px">项目内移动/重命名会改变相对引用，需自行检查 HTML/CSS/JS，动态路径不会自动修复。单个无子页文本可移出并保留私有源码编辑；二进制/整目录移出及跨项目移入暂不支持，图片可拖到普通笔记正文独立复制。</p>
      <div class="list">
        <div
          v-for="c in candidates"
          :key="String(c.id)"
          class="opt"
          :class="{ current: c.id === node.parent_id }"
          @click="pick(c.id)"
        >{{ c.label }}</div>
      </div>
      <div class="foot"><button @click="emit('cancel')">取消</button></div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: grid;
  place-items: center;
  z-index: 100;
}
.dialog {
  width: 340px;
  max-height: 60vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--bg-raised);
  border-radius: var(--radius);
  overflow: hidden;
}
.head { padding: 14px 18px; font-size: 14px; font-weight: 600; border-bottom: 1px solid var(--bg-raised); }
.list { flex: 1; overflow-y: auto; padding: 8px; }
.opt {
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  cursor: pointer;
  color: var(--text-lo);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.opt:hover { background: var(--bg-raised); color: var(--text-hi); }
.opt.current { color: var(--accent); }
.foot { padding: 10px 18px; text-align: right; border-top: 1px solid var(--bg-raised); }
.foot button {
  padding: 6px 16px;
  border: 1px solid var(--text-faint);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-lo);
  font-size: 12px;
  cursor: pointer;
}
</style>
