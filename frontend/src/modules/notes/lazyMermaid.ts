import { sanitizeNoteSvg } from './noteHtml';
import type { Mermaid } from 'mermaid';

let loading: Promise<Mermaid> | undefined;
let failedLoads = 0;
// Chromium caches failed module-map entries. A second build-resolved local
// entry (same locked package, shared dependencies) permits an entry-fetch retry.
// No user-supplied URL, global renderer or network/CDN fallback is accepted.
const retryEntry = import.meta.glob<{ default: Mermaid }>(
  '/node_modules/mermaid/dist/mermaid.core.mjs', { query: '?stella-retry' },
);
let sequence = 0;
/** One local, lockfile-reviewed module; never consult window or a CDN. */
export function loadMermaid(): Promise<Mermaid> {
  if (!loading) {
    const retry = retryEntry['/node_modules/mermaid/dist/mermaid.core.mjs'];
    loading = (failedLoads && retry ? retry() : import('mermaid')).then(({ default: mermaid }) => {
      // Per-diagram config cannot relax the site's rendering boundary.
      mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict',
        // Native MathML labels require Mermaid's HTML layout. Only inert
        // XHTML/MathML survives sanitizeNoteSvg; raw HTML input is rejected below.
        htmlLabels: true, flowchart: { htmlLabels: true }, suppressErrorRendering: true,
        secure: ['securityLevel', 'startOnLoad', 'htmlLabels', 'flowchart', 'themeCSS',
          'themeVariables', 'dompurifyConfig', 'maxTextSize', 'maxEdges', 'suppressErrorRendering'] });
      return mermaid;
    }).catch(error => { ++failedLoads; loading = undefined; throw error; });
  }
  return loading;
}

export async function renderMermaidBlocks(root: HTMLElement, current: () => boolean): Promise<void> {
  const blocks = Array.from(root.querySelectorAll<HTMLElement>('.mermaid:not([data-processed])'));
  if (!blocks.length || !current()) return;
  let mermaid: Mermaid;
  try { mermaid = await loadMermaid(); } catch { return; } // Source remains; next invocation retries.
  for (const block of blocks) {
    const code = (block.textContent || '').trim();
    if (!current() || !root.contains(block) || !root.isConnected) return;
    try {
      // Mermaid measures in a live DOM before returning SVG. Post-sanitation alone
      // cannot stop image/CSS fetches during that phase. These opt-in resource and
      // configuration features stay as source; ordinary vector diagrams still work.
      const outsideMath = code.replace(/\$\$[\s\S]*?\$\$/g, '');
      if (code.length > 50000 || /^\s*---/.test(code) || /%%\s*\{|@\s*\{|!\[|<\/?[a-z!]|&(?:#|(?:lt|gt|quot|colon);)|#(?:\d+|x[\da-f]+|colon|lt|gt|quot);/i.test(code.replace(/<<(?:interface|abstract|service|enumeration)>>/g, '')) ||
          /url\s*\(|@import|image-set\s*\(|\bimg\s*:|\b(?:style|classDef|linkStyle)\b[^\n]*\$\$/i.test(code) || /\\/.test(outsideMath) ||
          /\\(?:includegraphics|href|url|html\w*|def|gdef|edef|xdef|let|futurelet|newcommand|renewcommand|providecommand|csname)\b/i.test(code)) {
        throw new Error('Resource-capable Mermaid syntax is not enabled');
      }
      const { svg } = await mermaid.render(`stella-mmd-${++sequence}`, code);
      if (!current() || !root.contains(block) || !root.isConnected || block.textContent?.trim() !== code) continue;
      block.innerHTML = sanitizeNoteSvg(svg, true);
    } catch {
      if (!current() || !root.contains(block) || !root.isConnected || block.textContent?.trim() !== code) continue;
      const pre = document.createElement('pre'); pre.className = 'mermaid-error'; pre.textContent = code;
      block.replaceChildren(pre);
    }
    block.dataset.processed = '1';
  }
}
