import DOMPurify from 'dompurify';
/** Sanitize display HTML only; stored Markdown remains untouched. */
export function sanitizeNoteHtml(html: string): string {
  const clean = DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, svg: true, svgFilters: true },
    // Imported SVG may display images, but filter image loaders/animation are not needed.
    // Animation could rewrite an otherwise inert href after insertion.
    FORBID_TAGS: ['style', 'iframe', 'object', 'embed', 'form', 'foreignObject', 'feImage', 'use', 'animate', 'animateColor', 'animateMotion', 'animateTransform', 'set'],
    FORBID_ATTR: ['style', 'srcdoc'],
  });
  // Preserve vectors/local defs and ordinary guarded <image>, not external SVG
  // paint/filter/gradient references (native loaders beyond image href).
  const template=document.createElement('template');template.innerHTML=clean;
  for(const el of template.content.querySelectorAll('svg, svg *'))for(const attr of [...el.attributes]) {
    const local=/^#[\w.-]+$/.test(attr.value);
    const href=['href','xlink:href'].includes(attr.name);
    if(href&&!['image','a'].includes(el.tagName.toLowerCase())&&!local)el.removeAttribute(attr.name);
    if(attr.value.includes('\\')||/url\s*\(/i.test(attr.value)&&!/^url\(\s*['"]?#[\w.-]+['"]?\s*\)$/i.test(attr.value))el.removeAttribute(attr.name);
  }
  return template.innerHTML;
}

export function sanitizeNoteSvg(svg: string): string {
  // Only for SVG produced by Mermaid in strict mode, not imported HTML.
  return DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, FORBID_TAGS: ['foreignObject'] });
}
