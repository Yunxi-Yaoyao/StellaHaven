import createDOMPurify from 'dompurify';
// Mermaid installs persistent hooks on the package singleton. Keep note display
// policy independent: rendering a diagram must not change later imported HTML.
const DOMPurify = createDOMPurify(window);
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

export function sanitizeNoteSvg(svg: string, generatedLabels = false): string {
  // Mermaid output only: no navigation, image loaders or animated URL rewrites.
  // Keep renderer typography/colors (unlike imported note HTML) and local markers.
  const clean = DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true, mathMl: true },
    ADD_TAGS: ['foreignObject', 'div', 'span', 'p', 'br', 'strong', 'em'],
    HTML_INTEGRATION_POINTS: { foreignobject: true },
    FORBID_TAGS: [...(generatedLabels ? [] : ['foreignObject']), 'image', 'feImage', 'use', 'animate', 'animateColor', 'animateMotion', 'animateTransform', 'set'],
    FORBID_ATTR: ['href', 'xlink:href', 'src', 'srcset'],
  });
  const template = document.createElement('template');
  template.innerHTML = clean;
  // Re-sanitize foreignObject labels with a small inert vocabulary. Arbitrary
  // embedded HTML/SVG is never retained, but native MathML needs this SVG bridge.
  for (const label of template.content.querySelectorAll('foreignObject')) {
    label.innerHTML = DOMPurify.sanitize(label.innerHTML, {
      ALLOWED_TAGS: ['div', 'span', 'p', 'br', 'strong', 'em', 'math', 'mrow', 'msup',
        'msub', 'msubsup', 'mfrac', 'mi', 'mn', 'mo', 'mtext', 'msqrt', 'mroot',
        'mover', 'munder', 'munderover', 'mtable', 'mtr', 'mtd', 'mspace', 'mpadded',
        'mstyle', 'mmultiscripts', 'mprescripts', 'none'],
      ALLOWED_ATTR: ['xmlns', 'style', 'class', 'display', 'mathvariant', 'stretchy',
        'fence', 'separator', 'accent', 'accentunder', 'linethickness', 'rowspacing', 'columnspacing'],
      ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false,
    });
    if (!label.textContent?.trim()) label.remove();
  }
  const unsafeCss = (value: string) => /\\|@(?!keyframes\s)|image\s*\(|image-set\s*\(|src\s*\(/i.test(value) ||
    /url\s*\(/i.test(value.replace(/url\(\s*['"]?#[\w.-]+['"]?\s*\)/gi, ''));
  for (const style of template.content.querySelectorAll('style')) {
    if (unsafeCss(style.textContent || '')) style.remove();
  }
  for (const el of template.content.querySelectorAll('*')) {
    for (const attr of [...el.attributes]) {
      if (unsafeCss(attr.value)) el.removeAttribute(attr.name);
    }
  }
  return template.innerHTML;
}
