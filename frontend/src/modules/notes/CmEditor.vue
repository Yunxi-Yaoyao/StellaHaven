<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from "vue";
import { EditorView, keymap } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";

// Stella 暗夜主题（对齐 design tokens）
const stellaTheme = EditorView.theme({
  "&": {
    backgroundColor: "transparent",
    color: "var(--text-hi)",
    fontSize: "14px",
    height: "100%",
  },
  ".cm-content": {
    fontFamily: "var(--font-mono)",
    lineHeight: "1.8",
    padding: "16px",
    caretColor: "var(--accent)",
  },
  ".cm-cursor": { borderLeftColor: "var(--accent)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "var(--bg-raised) !important",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { overflow: "auto", fontFamily: "var(--font-mono)" },
  ".cm-line": { padding: "0 2px" },
}, { dark: true });

const props = defineProps<{ modelValue: string }>();
const emit = defineEmits<{
  "update:modelValue": [string];
  change: [EditorView];
  paste: [ClipboardEvent];
  drop: [DragEvent];
}>();

const host = ref<HTMLElement | null>(null);
let view: EditorView | null = null;
let syncingFromOutside = false;

onMounted(() => {
  view = new EditorView({
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        history(),
        keymap.of([...defaultKeymap, ...historyKeymap]),
        markdown({ base: markdownLanguage }),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        stellaTheme,
        EditorView.updateListener.of((u) => {
          if (u.docChanged && !syncingFromOutside) {
            emit("update:modelValue", u.state.doc.toString());
          }
          emit("change", u.view);
        }),
        EditorView.domEventHandlers({
          paste: (e) => emit("paste", e),
          drop: (e) => emit("drop", e),
          dragover: (e) => e.preventDefault(),
        }),
        EditorView.lineWrapping,
      ],
    }),
    parent: host.value!,
  });
});

// 外部（加载文档/采用草稿）改值 → 同步进编辑器，不打断正在打字的人
watch(() => props.modelValue, (v) => {
  if (!view) return;
  const cur = view.state.doc.toString();
  if (v === cur) return;
  syncingFromOutside = true;
  view.dispatch({ changes: { from: 0, to: cur.length, insert: v } });
  syncingFromOutside = false;
});

onUnmounted(() => view?.destroy());

/** 在当前选区/光标处包裹或插入文本（工具栏和斜杠命令用） */
function wrapSelection(before: string, after = "", placeholder = "") {
  if (!view) return;
  const { from, to } = view.state.selection.main;
  const selected = view.state.doc.sliceString(from, to) || placeholder;
  view.dispatch({
    changes: { from, to, insert: before + selected + after },
    selection: { anchor: from + before.length + selected.length + after.length },
  });
  view.focus();
}

function insertText(text: string) {
  if (!view) return;
  const { from } = view.state.selection.main;
  view.dispatch({ changes: { from, insert: text } });
  view.focus();
}

/** 删除从光标往前 N 个字符（斜杠命令触发后清掉 /xxx） */
function deleteBefore(n: number) {
  if (!view) return;
  const { from } = view.state.selection.main;
  view.dispatch({ changes: { from: Math.max(0, from - n), to: from, insert: "" } });
}

/** 当前行首插入前缀（H1/列表/待办用）；已在行首文本前则加在文本前 */
function linePrefix(prefix: string) {
  if (!view) return;
  const { from } = view.state.selection.main;
  const line = view.state.doc.lineAt(from);
  view.dispatch({
    changes: { from: line.from, insert: prefix },
    selection: { anchor: from + prefix.length },
  });
  view.focus();
}

function getCursor(): number {
  return view?.state.selection.main.head ?? 0;
}

function cursorPos(): number {
  return view?.coordsAtPos(view.state.selection.main.head)?.top ?? 0;
}

defineExpose({ wrapSelection, insertText, deleteBefore, linePrefix, getCursor, cursorPos, focus: () => view?.focus() });
</script>

<template>
  <div ref="host" class="cm-host" />
</template>

<style scoped>
.cm-host {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cm-host :deep(.cm-editor) {
  height: 100%;
}
</style>
