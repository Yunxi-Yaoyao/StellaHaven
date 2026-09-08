// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { sanitizeNoteHtml, sanitizeNoteSvg } from './noteHtml';
describe('imported note HTML safety', () => {
  it('removes active HTML and unsafe links while retaining notes widgets', () => {
    const html = sanitizeNoteHtml('<h1 id="toc-h0">Title</h1><script>alert(1)</script><img src="x" onerror="alert(1)"><a href="javascript:alert(1)">bad</a><iframe src="https://evil.test"></iframe><span class="attach-card" data-url="/attachments/abc"><svg viewBox="0 0 24 24"><path d="M1 2"/></svg></span><div class="mermaid">graph TD; A--&gt;B</div>');
    const node = document.createElement('div'); node.innerHTML = html;
    expect(node.querySelector('script, iframe, [onerror], a[href^="javascript:"]')).toBeNull();
    expect(node.querySelector('#toc-h0')?.textContent).toBe('Title');
    expect(node.querySelector('.attach-card')?.getAttribute('data-url')).toBe('/attachments/abc');
    expect(node.querySelector('svg path')).not.toBeNull();
    expect(node.querySelector('.mermaid')?.textContent).toBe('graph TD; A-->B');
  });
});

it('retains generated diagram styles and labels but removes SVG scripts', () => {
  const value = sanitizeNoteSvg('<svg xmlns="http://www.w3.org/2000/svg"><style>.node{fill:#abc}</style><text>A</text><script>alert(1)</script><foreignObject><div>bad</div></foreignObject></svg>');
  expect(value).toContain('<style>'); expect(value).toContain('<text>A</text>');
  expect(value).not.toMatch(/<script|<foreignObject/);
});
