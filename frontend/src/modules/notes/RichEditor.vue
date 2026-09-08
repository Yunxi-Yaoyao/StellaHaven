<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { Crepe } from '@milkdown/crepe';
import { commandsCtx, editorViewCtx } from '@milkdown/kit/core';
import { EditorState, TextSelection } from '@milkdown/kit/prose/state';
import { Slice } from '@milkdown/kit/prose/model';
import { uploadConfig } from '@milkdown/kit/plugin/upload';
import { toggleStrongCommand, toggleEmphasisCommand, toggleInlineCodeCommand,
  wrapInHeadingCommand, wrapInBulletListCommand, wrapInBlockquoteCommand, insertHrCommand,
  toggleLinkCommand, insertImageCommand } from '@milkdown/kit/preset/commonmark';
import { createRichMarkdown, RichMarkdownSession } from './richMarkdown';
import '@milkdown/crepe/theme/common/style.css';
import '@milkdown/crepe/theme/classic.css';

const props = defineProps<{ modelValue: string; docId: string }>();
const emit = defineEmits<{
  'update:modelValue': [value: string];
  ready: [];
  paste: [event: ClipboardEvent];
  drop: [event: DragEvent];
}>();
const host = ref<HTMLElement>();
const error = ref('');
const urlKind = ref<'link' | 'image' | null>(null);
const urlValue = ref('');
const session = new RichMarkdownSession(props.docId, props.modelValue);
const markdown = createRichMarkdown();
let crepe: Crepe | undefined;
let initialized = false;
let disposed = false;
let loading = false;

function load() {
  if (!crepe || !initialized) return;
  loading = true;
  try {
    crepe.editor.action(ctx => {
      const view = ctx.get(editorViewCtx);
      const doc = markdown.parse(ctx, session.flush(), true);
      // Reset history on external source/doc changes, never on v-show or our v-model echo.
      view.updateState(EditorState.create({ schema: view.state.schema, doc, plugins: view.state.plugins }));
    });
    error.value = '';
  } catch (cause) {
    error.value = '此内容暂时无法在富文本模式编辑，请切换源码模式。原文已保留。';
    crepe.setReadonly(true);
    console.error('RichEditor load:', cause);
  } finally { loading = false; }
}

watch(() => [props.docId, props.modelValue] as const, ([id, value]) => {
  if (session.accept(id, value)) {
    urlKind.value = null;
    if (crepe && initialized) crepe.setReadonly(false);
    load();
  }
}, { flush: 'sync' });

onMounted(async () => {
  const instance = new Crepe({ root: host.value, defaultValue: '', features: {
    [Crepe.Feature.Latex]: false,
    [Crepe.Feature.ImageBlock]: false,
    [Crepe.Feature.TopBar]: false,
    [Crepe.Feature.AI]: false,
  } });
  crepe = instance;
  instance.editor.use(markdown.plugins).config(ctx => {
    // Attachment ownership belongs to DocEditor. Never persist temporary blob URLs.
    ctx.update(uploadConfig.key, config => ({ ...config, uploader: async () => [] }));
  });
  try {
    await instance.create();
    if (disposed) { await instance.destroy(); return; }
    initialized = true;
    const view = instance.editor.action(ctx => ctx.get(editorViewCtx));
    view.setProps({
      dispatchTransaction(transaction) {
        if (disposed || !initialized) return;
        const revision = session.revision;
        const previous = view.state.doc;
        const result = view.state.applyTransaction(transaction);
        view.updateState(result.state);
        if (!loading && !error.value && transaction.docChanged && !previous.eq(result.state.doc)) {
          const value = instance.editor.action(ctx => markdown.serialize(ctx, result.state.doc));
          const changed = session.userEdit(revision, value);
          if (changed !== undefined) emit('update:modelValue', changed);
        }
      },
      attributes: { 'aria-label': '笔记富文本编辑器', spellcheck: 'false' },
    });
    load();
    emit('ready');
  } catch (cause) {
    if (!disposed) error.value = '富文本编辑器加载失败，请切换源码模式。原文已保留。';
    console.error('RichEditor create:', cause);
  }
});

onBeforeUnmount(() => {
  disposed = true;
  if (initialized) { initialized = false; void crepe?.destroy(); }
});

function focus() {
  if (initialized && !error.value) crepe?.editor.action(ctx => ctx.get(editorViewCtx).focus());
}
function flush(): string { return session.flush(); }
/** Insert Markdown at the current selection. Returns false until ready or on failure. */
function insertText(text: string): boolean {
  if (!crepe || !initialized || error.value) return false;
  crepe.editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    const doc = markdown.parse(ctx, text);
    view.dispatch(view.state.tr.replaceSelection(Slice.maxOpen(doc.content)).scrollIntoView());
    view.focus();
  });
  return true;
}
/** Commands act on ProseMirror selection; URL commands open an inline form. */
function exec(action: string): boolean {
  if (!crepe || !initialized || error.value) return false;
  if (action === 'link' || action === 'image') {
    urlKind.value = action; urlValue.value = '';
    return true;
  }
  return crepe.editor.action(ctx => {
    const commands = ctx.get(commandsCtx), view = ctx.get(editorViewCtx);
    view.focus();
    switch (action) {
      case 'bold': return commands.call(toggleStrongCommand.key);
      case 'italic': return commands.call(toggleEmphasisCommand.key);
      case 'code': return commands.call(toggleInlineCodeCommand.key);
      case 'h1': return commands.call(wrapInHeadingCommand.key, 1);
      case 'h2': return commands.call(wrapInHeadingCommand.key, 2);
      case 'ul': return commands.call(wrapInBulletListCommand.key);
      case 'quote': return commands.call(wrapInBlockquoteCommand.key);
      case 'hr': return commands.call(insertHrCommand.key);
      case 'todo': {
        let depth = view.state.selection.$from.depth;
        while (depth > 0 && view.state.selection.$from.node(depth).type.name !== 'list_item') depth--;
        if (!depth) {
          if (!commands.call(wrapInBulletListCommand.key)) return false;
          depth = view.state.selection.$from.depth;
          while (depth > 0 && view.state.selection.$from.node(depth).type.name !== 'list_item') depth--;
        }
        if (!depth) return false;
        const node = view.state.selection.$from.node(depth);
        view.dispatch(view.state.tr.setNodeMarkup(view.state.selection.$from.before(depth), undefined,
          { ...node.attrs, checked: node.attrs.checked == null ? false : !node.attrs.checked }));
        return true;
      }
      default: return false;
    }
  });
}
function applyUrl() {
  const href = urlValue.value.trim();
  if (!href || /^(?:javascript|data|vbscript|blob):/i.test(href) || !crepe || !urlKind.value) return;
  crepe.editor.action(ctx => {
    const view = ctx.get(editorViewCtx), commands = ctx.get(commandsCtx);
    if (urlKind.value === 'image') commands.call(insertImageCommand.key, { src: href, alt: '图片' });
    else {
      if (view.state.selection.empty) {
        const from = view.state.selection.from;
        const tr = view.state.tr.insertText('链接');
        view.dispatch(tr.setSelection(TextSelection.create(tr.doc, from, from + 2)));
      }
      commands.call(toggleLinkCommand.key, { href });
    }
    view.focus();
  });
  urlKind.value = null;
}
function onPaste(event: ClipboardEvent) {
  emit('paste', event);
  if (event.clipboardData?.files.length) event.preventDefault();
}
function onDrop(event: DragEvent) {
  emit('drop', event);
  if (event.dataTransfer?.files.length) event.preventDefault();
}
function scrollToHeading(text: string): boolean {
  const heading = Array.from(host.value?.querySelectorAll('h1,h2,h3,h4,h5,h6') ?? [])
    .find(element => element.textContent?.trim() === text.trim());
  if (!heading || !initialized || !crepe) return false;
  crepe.editor.action(ctx => {
    const view = ctx.get(editorViewCtx);
    const pos = view.posAtDOM(heading, 0);
    view.dispatch(view.state.tr.setSelection(TextSelection.near(view.state.doc.resolve(pos))).scrollIntoView());
    view.focus();
  });
  return true;
}
defineExpose({ focus, insertText, exec, flush, scrollToHeading });
</script>

<template>
  <div class="rich-editor" @paste.capture="onPaste" @drop.capture="onDrop">
    <p v-if="error" class="rich-error" role="alert">{{ error }}</p>
    <form v-if="urlKind" class="rich-url" @submit.prevent="applyUrl" @keydown.esc="urlKind = null">
      <label :for="`rich-url-${docId}`">{{ urlKind === 'image' ? '图片地址' : '链接地址' }}</label>
      <input :id="`rich-url-${docId}`" v-model="urlValue" placeholder="https:// 或 /api/…" autocomplete="off" />
      <button type="submit">插入</button><button type="button" @click="urlKind = null">取消</button>
    </form>
    <div ref="host" class="rich-host" />
  </div>
</template>

<style scoped>
.rich-editor { flex: 1; min-height: 0; overflow: auto; position: relative; color: var(--text-hi); }
.rich-host { min-height: 100%; }
.rich-host :deep(.milkdown) {
  --crepe-color-background: transparent;
  --crepe-color-on-background: var(--text-hi, #e8ecf4);
  --crepe-color-surface: var(--bg-raised, #252532);
  --crepe-color-surface-low: var(--bg-base, #181820);
  --crepe-color-on-surface: var(--text-hi, #e8ecf4);
  --crepe-color-on-surface-variant: var(--text-lo, #a0a6b5);
  --crepe-color-outline: var(--text-faint, #646879);
  --crepe-color-primary: var(--accent, #e8a0bf);
  --crepe-color-on-primary: var(--bg-base, #181820);
  --crepe-color-secondary: var(--bg-raised, #303040);
  --crepe-color-on-secondary: var(--text-hi, #e8ecf4);
  --crepe-color-inverse: var(--text-hi, #e8ecf4);
  --crepe-color-on-inverse: var(--bg-base, #181820);
  --crepe-color-inline-code: var(--accent, #e8a0bf);
  --crepe-color-hover: var(--bg-raised, #303040);
  --crepe-color-selected: var(--bg-raised, #303040);
  --crepe-font-default: var(--font-ui, Inter, sans-serif);
  --crepe-font-title: var(--font-ui, Inter, sans-serif);
  --crepe-font-code: var(--font-mono, monospace);
  background: transparent;
}
.rich-host :deep(.ProseMirror) { padding: 24px 48px 120px; min-height: 320px; font-size: 15px; line-height: 1.85; outline: none; }
.rich-host :deep(.ProseMirror img) { max-width: 100%; }
.rich-host :deep(.stella-opaque) { white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px 16px; border: 1px dashed var(--text-faint); border-radius: 8px; color: var(--text-lo); font: 13px/1.7 var(--font-mono, monospace); }
.rich-host :deep(.stella-wiki) { color: var(--accent); border-radius: 3px; }
.rich-error { padding: 12px; color: var(--accent); }
.rich-url { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 8px; padding: 12px; background: var(--bg-raised, #252532); }
.rich-url input { min-width: 0; flex: 1; padding: 7px; background: var(--bg-base); color: var(--text-hi); border: 1px solid var(--text-faint); border-radius: 4px; }
.rich-url button { white-space: nowrap; color: var(--text-hi); background: var(--bg-raised); padding: 6px 10px; border: 1px solid var(--text-faint); border-radius: 4px; cursor: pointer; }
@media (max-width: 768px) { .rich-host :deep(.ProseMirror) { padding: 16px 24px 100px; } .rich-url { flex-wrap: wrap; } }
</style>
