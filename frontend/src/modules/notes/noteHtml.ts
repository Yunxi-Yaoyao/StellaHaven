import DOMPurify from 'dompurify';
/** Sanitize display HTML only; stored Markdown remains untouched. */
export function sanitizeNoteHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, svg: true, svgFilters: true },
    FORBID_TAGS: ['style', 'iframe', 'object', 'embed', 'form', 'foreignObject'],
    FORBID_ATTR: ['style', 'srcdoc'],
  });
}

export function sanitizeNoteSvg(svg: string): string {
  // Only for SVG produced by Mermaid in strict mode, not imported HTML.
  return DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, FORBID_TAGS: ['foreignObject'] });
}
