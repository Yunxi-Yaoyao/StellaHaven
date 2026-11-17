import { describe, expect, it } from 'vitest';
import createDOMPurify from 'dompurify';
import { sanitizeNoteHtml, sanitizeNoteSvg } from './noteHtml';

// Dependency-level regressions, not claims that Stella uses IN_PLACE/hooks.
// GHSA-6688-9rhm-gjv2 and GHSA-p98j-92pf-mc4p.
describe('DOMPurify security patch', () => {
  it('refuses to return a removed rawtext root for HTML reparsing', () => {
    const purify = createDOMPurify(window);
    const root = document.createElement('style');
    root.textContent = '</style><img src=x onerror=ATTACKER()>';
    document.body.append(root);
    try {
      expect(() => purify.sanitize(root, { IN_PLACE: true })).toThrow(TypeError);
    } finally {
      root.remove();
    }
  });

  it.each(['afterSanitizeElements', 'afterSanitizeAttributes'] as const)(
    'neutralizes descendants detached by %s', (hook) => {
      const purify = createDOMPurify(window);
      const root = document.createElement('div');
      root.innerHTML = '<section id="removed"><img src="x" onerror="ATTACKER()"></section>';
      const img = root.querySelector('img')!;
      document.body.append(root);
      const detach = (node: Node) => {
        if ((node as Element).id === 'removed') node.parentNode?.removeChild(node);
      };
      if (hook === 'afterSanitizeElements') purify.addHook(hook, detach);
      else purify.addHook(hook, detach);
      try {
        purify.sanitize(root, { IN_PLACE: true });
        expect(root.querySelector('section')).toBeNull();
        expect(img.hasAttribute('onerror')).toBe(false);
      } finally {
        purify.removeAllHooks();
        root.remove();
      }
    },
  );

  it('preserves actual note HTML while removing active imported content', () => {
    const html = sanitizeNoteHtml('<h2 id="toc-h1">Title</h2><p><strong>bold</strong></p><a href="/notes/1">note</a><img src="/attachments/1" onerror="ATTACKER()"><svg><script>ATTACKER()</script><image href="javascript:ATTACKER()"/></svg><div class="mermaid">graph TD; A--&gt;B</div>');
    const result = document.createElement('div');
    result.innerHTML = html;
    expect(result.querySelector('h2')?.id).toBe('toc-h1');
    expect(result.querySelector('strong')?.textContent).toBe('bold');
    expect(result.querySelector('img')?.getAttribute('src')).toBe('/attachments/1');
    expect(result.querySelector('a')?.getAttribute('href')).toBe('/notes/1');
    expect(result.querySelector('.mermaid')?.textContent).toBe('graph TD; A-->B');
    expect(result.querySelector('script, [onerror], [href^="javascript:"]')).toBeNull();
  });

  it('preserves Mermaid-style vectors and CSS while stripping active SVG', () => {
    const svg = sanitizeNoteSvg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><style>.node{fill:#abc}</style><g class="node"><rect width="50" height="20"/><text>A</text></g><a href="javascript:ATTACKER()"><text>B</text></a><foreignObject><div>bad</div></foreignObject><script>ATTACKER()</script></svg>');
    const result = document.createElement('div');
    result.innerHTML = svg;
    expect(result.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 100 100');
    expect(result.querySelector('style')?.textContent).toBe('.node{fill:#abc}');
    expect(result.querySelector('.node rect')?.getAttribute('width')).toBe('50');
    expect(result.querySelector('.node text')?.textContent).toBe('A');
    expect(result.querySelector('foreignObject, script, [href^="javascript:"]')).toBeNull();
  });
});
