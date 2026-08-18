<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from "vue";
import { EditorView, keymap, drawSelection } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { syntaxHighlighting, HighlightStyle } from "@codemirror/language";
import { tags as cmTags } from "@lezer/highlight";
import { searchKeymap } from "@codemirror/search";

// Stella 配色语法高亮（月白银/樱粉系，吃 design tokens 的色）
const stellaHighlight = HighlightStyle.define([
  { tag: cmTags.heading1, color: "#e8ecf4", fontWeight: "600", fontSize: "1.35em" },
  { tag: cmTags.heading2, color: "#c9d4e8", fontWeight: "600", fontSize: "1.2em" },
  { tag: cmTags.heading3, color: "#c9d4e8", fontWeight: "600" },
  { tag: cmTags.strong, color: "#e8a0bf", fontWeight: "600" },
  { tag: cmTags.emphasis, color: "#e8c9d8", fontStyle: "italic" },
  { tag: cmTags.link, color: "#c9d4e8", textDecoration: "underline dashed" },
  { tag: cmTags.url, color: "#8a94ab" },
  { tag: cmTags.monospace, color: "#e8a0bf", backgroundColor: "rgba(232,160,191,0.08)" },
  { tag: cmTags.quote, color: "#9aa3b5", fontStyle: "italic" },
  { tag: cmTags.list, color: "#c9d4e8" },
  { tag: cmTags.strikethrough, textDecoration: "line-through", color: "#5c6474" },
]);

// 回车自动续行：- 列表 / - [ ] 待办 / > 引用；空项回车=退出列表
function continueList(view: EditorView): boolean {
  const { from, to } = view.state.selection.main;
  if (from !== to) return false; // 有选区走默认
  const line = view.state.doc.lineAt(from);
  const m = line.text.match(/^(\s*(?:[-*+] |\d+\. |> )(\[ \] )?)/);
  if (!m) return false;
  const prefix = m[1];
  const rest = line.text.slice(prefix.length);
  if (!rest.trim()) {
    // 空列表项回车 → 清掉前缀退出列表
    view.dispatch({ changes: { from: line.from, to: line.to, insert: "" } });
    return true;
  }
  view.dispatch({
    changes: { from, insert: "\n" + prefix },
    selection: { anchor: from + 1 + prefix.length },
  });
  return true;
}

// Stella 暗夜主题（对齐 design tokens）
const stellaTheme = EditorView.theme({
  "&": {
    backgroundColor: "transparent",
    color: "var(--text-hi)",
    fontSize: "15px",
    height: "100%",
  },
  ".cm-content": {
    fontFamily: "var(--font-mono)",
    lineHeight: "1.8",
    padding: "16px",
    caretColor: "var(--accent)",
  },
  ".cm-cursor": {
    borderLeftColor: "var(--accent)",
    // CM6 默认光标闪烁动画，显式补上（theme 重写 .cm-cursor 后默认 animation 会丢）
    animation: "cm-blink 1.2s steps(1) infinite",
  },
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
  scroll: [number]; // 滚动比例 0-1（编辑/预览联动用）
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
        keymap.of([
          // 编辑器快捷键（手不离键盘）
          { key: "Mod-b", run: () => { wrapSelection("**", "**", "粗体"); return true; } },
          { key: "Mod-i", run: () => { wrapSelection("*", "*", "斜体"); return true; } },
          { key: "Mod-k", run: () => { wrapSelection("[", "](https://)", "链接文字"); return true; } },
          { key: "Enter", run: continueList }, // 列表/待办/引用自动续行
          ...searchKeymap, // Ctrl+F 文内查找/替换
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        markdown({ base: markdownLanguage }),
        syntaxHighlighting(stellaHighlight, { fallback: true }),
        stellaTheme,
        // 光标 + 选区绘制（含闪烁动画）——不引这个，CM6 根本不画光标
        drawSelection(),
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

  // 编辑器滚动 → 抛比例给外面（预览跟着滚）
  view.scrollDOM.addEventListener("scroll", () => {
    const el = view!.scrollDOM;
    const max = el.scrollHeight - el.clientHeight;
    emit("scroll", max > 0 ? el.scrollTop / max : 0);
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

/** 跳转到源码某字符偏移处（TOC 跳转时让编辑器同步滚到对应标题） */
function scrollToPos(offset: number) {
  if (!view) return;
  const pos = Math.max(0, Math.min(offset, view.state.doc.length));
  view.dispatch({
    selection: { anchor: pos },
    effects: EditorView.scrollIntoView(pos, { y: "start" }),
  });
  view.focus();
}

defineExpose({ wrapSelection, insertText, deleteBefore, linePrefix, getCursor, cursorPos, scrollToPos, focus: () => view?.focus() });
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
