import type { Ctx } from '@milkdown/kit/ctx';
import { parserCtx, serializerCtx } from '@milkdown/kit/core';
import { Fragment, type Node as ProseNode } from '@milkdown/kit/prose/model';
import { $node, $remark } from '@milkdown/kit/utils';

type MarkdownTree = {
  type: string; value?: string; meta?: string; children?: MarkdownTree[];
  position?: { start: { offset?: number }; end: { offset?: number } };
};
const supported = new Set(['root', 'paragraph', 'heading', 'text', 'strong', 'emphasis', 'delete',
  'inlineCode', 'code', 'blockquote', 'list', 'listItem', 'thematicBreak', 'break', 'link', 'image',
  'table', 'tableRow', 'tableCell']);

/** Per-editor lossless envelope; unsupported blocks are inert, visible source atoms. */
export function createRichMarkdown() {
  let parsedBlocks: string[] = [];
  const originals: { node: ProseNode; source: string }[] = [];
  const opaque = $node('stella_opaque', () => ({
    group: 'block', atom: true, isolating: true,
    attrs: { source: { default: '' } },
    parseDOM: [{ tag: 'pre[data-stella-opaque]', getAttrs: dom => ({ source: dom.textContent ?? '' }) }],
    toDOM: node => ['pre', { 'data-stella-opaque': '', class: 'stella-opaque', contenteditable: 'false',
      title: '原样保留的 Markdown；请切换源码模式编辑' }, ['code', {}, node.attrs.source]],
    parseMarkdown: { match: node => node.type === 'stellaOpaque', runner: (state, node, type) => {
      state.addNode(type, { source: node.value });
    } },
    toMarkdown: { match: node => node.type.name === 'stella_opaque', runner: (state, node) => {
      state.addNode('html', undefined, node.attrs.source);
    } },
  }));
  const wiki = $node('stella_wiki', () => ({
    group: 'inline', inline: true, atom: true,
    attrs: { source: { default: '' } },
    parseDOM: [{ tag: 'span[data-stella-wiki]', getAttrs: dom => ({ source: dom.textContent ?? '' }) }],
    toDOM: node => ['span', { 'data-stella-wiki': '', class: 'stella-wiki' }, node.attrs.source],
    parseMarkdown: { match: node => node.type === 'stellaWiki', runner: (state, node, type) => {
      state.addNode(type, { source: node.value });
    } },
    toMarkdown: { match: node => node.type.name === 'stella_wiki', runner: (state, node) => {
      state.addNode('html', undefined, node.attrs.source);
    } },
  }));
  const preserve = $remark('stellaPreserve', () => () => (tree, file) => {
    const root = tree as unknown as MarkdownTree;
    const source = String(file);
    const unsupported = (node: MarkdownTree): boolean => !supported.has(node.type)
      || (node.type === 'code' && !!node.meta) || !!node.children?.some(unsupported);
    const wikify = (node: MarkdownTree) => {
      if (!node.children) return;
      node.children = node.children.flatMap(child => {
        // CommonMark's earlier plugin labels soft breaks as inline spaces.
        // Notes preview uses marked breaks:true, so rich mode must show them too.
        if (child.type === 'break') return [{ type: 'break' }];
        if (child.type !== 'text' || !child.value) { wikify(child); return [child]; }
        const parts: MarkdownTree[] = [];
        let offset = 0;
        for (const match of child.value.matchAll(/\[\[[^\]\n]+\]\]/g)) {
          if (match.index! > offset) parts.push({ type: 'text', value: child.value.slice(offset, match.index) });
          parts.push({ type: 'stellaWiki', value: match[0] });
          offset = match.index! + match[0].length;
        }
        if (!offset) return child.value.split(/\r?\n/).flatMap((value, index) => index ? [{ type: 'break' }, { type: 'text', value }] : [{ type: 'text', value }]);
        if (offset < child.value.length) parts.push({ type: 'text', value: child.value.slice(offset) });
        return parts;
      });
    };
    parsedBlocks = [];
    const children: MarkdownTree[] = [];
    let previousEnd = 0;
    const preserveGap = (end: number) => {
      const raw = source.slice(previousEnd, end).trim();
      if (raw) { children.push({ type: 'stellaOpaque', value: raw }); parsedBlocks.push(raw); }
    };
    for (const node of root.children ?? []) {
      const start = node.position?.start.offset ?? 0, end = node.position?.end.offset ?? source.length;
      preserveGap(start);
      previousEnd = end;
      const raw = source.slice(start, end);
      parsedBlocks.push(raw);
      if (unsupported(node) || /^(?:\s*:::+|\s*\$\$|\[\^[^\]]+\]:)/m.test(raw)) {
        children.push({ type: 'stellaOpaque', value: raw });
      } else { wikify(node); children.push(node); }
    }
    preserveGap(source.length);
    root.children = children;
  });
  let baseline: ProseNode | undefined;
  let original = '';
  function parse(ctx: Ctx, source: string, reset = false): ProseNode {
    // Strip the envelope before parsing: TOML can otherwise share a paragraph
    // with the first body line, and skipping that paragraph loses body content.
    const frontmatter = source.match(/^\uFEFF?(---|\+\+\+)[\t ]*\r?\n[\s\S]*?\r?\n(?:\1|\.\.\.)[\t ]*(?:\r?\n|$)/)?.[0];
    let doc = ctx.get(parserCtx)(frontmatter ? source.slice(frontmatter.length) : source);
    if (frontmatter) {
      const raw = frontmatter.replace(/\r?\n$/, '');
      parsedBlocks.unshift(raw);
      doc = doc.copy(Fragment.from(doc.type.schema.nodes.stella_opaque!.create({ source: raw })).append(doc.content));
    }
    if (reset) { originals.length = 0; baseline = doc; original = source; }
    doc.forEach((node, _offset, index) => {
      const raw = parsedBlocks[index];
      if (raw !== undefined) originals.push({ node, source: raw });
    });
    return doc;
  }
  // Typed wiki syntax is plain ProseMirror text until the next source load.
  // Convert only text (never code) in a serialization copy, keeping marks.
  function serializeWikis(node: ProseNode): ProseNode {
    if (node.type.spec.code) return node;
    const nodes: ProseNode[] = [];
    node.forEach(child => {
      if (!child.isText || child.marks.some(mark => mark.type.spec.code)) { nodes.push(serializeWikis(child)); return; }
      const text = child.text!;
      let offset = 0;
      for (const match of text.matchAll(/\[\[[^\]\n]+\]\]/g)) {
        if (match.index! > offset) nodes.push(node.type.schema.text(text.slice(offset, match.index), child.marks));
        nodes.push(node.type.schema.nodes.stella_wiki!.create({ source: match[0] }, null, child.marks));
        offset = match.index! + match[0].length;
      }
      if (!offset) nodes.push(child);
      else if (offset < text.length) nodes.push(node.type.schema.text(text.slice(offset), child.marks));
    });
    return node.copy(Fragment.fromArray(nodes));
  }
  function serialize(ctx: Ctx, doc: ProseNode): string {
    if (baseline?.eq(doc)) return original;
    const chunks: string[] = [];
    const used = new Set<(typeof originals)[number]>();
    doc.forEach((node, _offset, index) => {
      if (index === doc.childCount - 1 && node.type.name === 'paragraph' && !node.content.size) return;
      if (node.type.name === 'stella_opaque') { chunks.push(node.attrs.source); return; }
      const sameMarkdown = (before: ProseNode) => before.eq(node) || (
        before.type.name === 'heading' && node.type.name === 'heading'
        && before.attrs.level === node.attrs.level && before.content.eq(node.content)
      ); // Crepe generates heading DOM ids after edits; ids are not Markdown changes.
      const cached = originals.find(entry => !used.has(entry) && entry.node === node)
        ?? originals.find(entry => !used.has(entry) && sameMarkdown(entry.node));
      if (cached) used.add(cached);
      chunks.push(cached?.source ?? ctx.get(serializerCtx)(doc.copy(Fragment.from(serializeWikis(node)))).replace(/\n$/, ''));
    });
    return chunks.join('\n\n') + (original.endsWith('\n') && chunks.length ? '\n' : '');
  }
  return { plugins: [opaque, wiki, preserve].flat(), parse, serialize };
}

/** Synchronous source authority. A revision rejects callbacks from a previous load. */
export class RichMarkdownSession {
  revision = 0;
  private docId: string;
  private value: string;
  constructor(docId: string, value: string) {
    this.docId = docId;
    this.value = value;
  }
  accept(docId: string, value: string): boolean {
    if (this.docId === docId && this.value === value) return false;
    this.docId = docId;
    this.value = value;
    this.revision++;
    return true;
  }
  userEdit(revision: number, value: string): string | undefined {
    if (revision !== this.revision || value === this.value) return;
    this.value = value;
    return value;
  }
  flush(): string { return this.value; }
}
