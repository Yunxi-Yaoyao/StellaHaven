import {it, expect, vi, beforeEach, afterEach} from 'vitest';
import {sanitizeNoteSvg} from './noteHtml';
const state=vi.hoisted(()=>({failImport:false,imports:0,initialize:vi.fn(),render:vi.fn()}));
vi.mock('mermaid',()=>{state.imports++;if(state.failImport)throw new Error('chunk unavailable');return {default:{initialize:state.initialize,render:state.render}};});
vi.mock('mermaid/dist/mermaid.core.mjs?stella-retry',()=>{state.imports++;if(state.failImport)throw new Error('chunk unavailable');return {default:{initialize:state.initialize,render:state.render}};});
beforeEach(()=>{vi.resetModules();state.imports=0;state.failImport=false;state.initialize.mockReset();state.render.mockReset();state.render.mockResolvedValue({svg:'<svg><text>OK</text></svg>'});});
afterEach(()=>{document.body.innerHTML='';});
function root(code='flowchart LR\nA-->B'){const r=document.createElement('div');const b=document.createElement('div');b.className='mermaid';b.textContent=code;r.append(b);document.body.append(r);return r;}
it('singleflights initialization and retries a rejected import',async()=>{
 const {loadMermaid}=await import('./lazyMermaid');state.failImport=true;
 const first=loadMermaid();expect(loadMermaid()).toBe(first);await expect(first).rejects.toThrow();
 state.failImport=false;await loadMermaid();expect(state.imports).toBe(2);expect(state.initialize).toHaveBeenCalledTimes(1);
});
it.each(['generation','source','detach'] as const)('does not commit a delayed SVG after %s changes',async(boundary)=>{
 const {renderMermaidBlocks}=await import('./lazyMermaid');let resolve!:(v:any)=>void;state.render.mockReturnValue(new Promise(r=>resolve=r));const r=root();let live=true;
 const work=renderMermaidBlocks(r,()=>live);await vi.waitFor(()=>expect(state.render).toHaveBeenCalledOnce());
 if(boundary==='generation')live=false;if(boundary==='source')r.firstElementChild!.textContent='new code';if(boundary==='detach')r.remove();
 resolve({svg:'<svg><text>STALE</text></svg>'});await work;expect(r.querySelector('svg')).toBeNull();expect(r.querySelector('[data-processed]')).toBeNull();
});
it('invalid diagrams become inert source, then a new valid block still renders',async()=>{
 const {renderMermaidBlocks}=await import('./lazyMermaid');state.render.mockRejectedValueOnce(new Error('parse'));const r=root('flowchart LR\nA--');await renderMermaidBlocks(r,()=>true);expect(r.querySelector('pre')?.textContent).toBe('flowchart LR\nA--');
 const good=root();await renderMermaidBlocks(good,()=>true);expect(good.querySelector('svg text')?.textContent).toBe('OK');
});
it.each([
 '%%{init: {"securityLevel":"loose","themeCSS":"@import url(https://evil.test/x)"}}%%\nflowchart LR\nA-->B',
 '---\nconfig:\n  themeCSS: "@import url(https://evil.test/x)"\n---\nflowchart LR\nA-->B',
 'flowchart LR\nA@{ img: "https://evil.test/x" }',
 'flowchart LR\nA["<img src=https://evil.test/x>"]',
 'flowchart LR\nA-->B\nclassDef default fill:/*$$*/url(https://evil.test/x)/*$$*/',
 'flowchart LR\nA["$$\\includegraphics{https://evil.test/x}$$"]',
 'flowchart LR\nA["$$\\href{javascript:alert(1)}{x}$$"]',
 'flowchart LR\nA["&lt;img src=https://evil.test/x&gt;"]',
 'flowchart LR\nA-->B\nclassDef default fill:url(https://evil.test/x)',
 'flowchart LR\nA-->B\nclassDef default fill:u\\\\72l(https://evil.test/x)',
])('rejects resource-capable input before Mermaid touches the DOM: %s',async(code)=>{
 const {renderMermaidBlocks}=await import('./lazyMermaid');const r=root(code);await renderMermaidBlocks(r,()=>true);
 expect(state.render).not.toHaveBeenCalled();expect(r.querySelector('pre')?.textContent).toBe(code);
});
it('retains only inert XHTML/MathML labels in renderer foreignObjects',()=>{
 const clean=sanitizeNoteSvg('<svg><foreignObject width="60" height="30"><div xmlns="http://www.w3.org/1999/xhtml"><span><math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mn>1</mn><mn>2</mn></mfrac></math></span></div></foreignObject><foreignObject width="40" height="24"><div xmlns="http://www.w3.org/1999/xhtml"><p>End</p><img src="https://evil.test/" onerror="alert(1)"></div></foreignObject></svg>', true);
 expect(clean).toContain('<mfrac>');expect(clean).toContain('End');expect(clean).not.toContain('<img');expect(clean).not.toContain('evil.test');
});
it('preserves renderer colors, local markers and animation CSS without allowing imports',()=>{
 const safe=sanitizeNoteSvg('<svg><style>#diagram .node {fill:#abc;stroke:#def} @keyframes dash {to {stroke-dashoffset:0}}</style><path marker-end="url(#arrow)"/></svg>');
 expect(safe).toContain('fill:#abc');expect(safe).toContain('@keyframes');expect(safe).toContain('url(#arrow)');
});
it('sanitizes executable, navigable and external-resource SVG while keeping local vectors',()=>{
 const svg=sanitizeNoteSvg('<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://evil.test/css";</style><image href="https://evil.test/i"/><use href="https://evil.test/u#x"/><a href="javascript:alert(1)"><text onclick="alert(1)">label</text></a><a href="https://evil.test/"><text>link</text></a><foreignObject><img src="https://evil.test/f"/></foreignObject><path fill="url(https://evil.test/p)"/><animate attributeName="href" values="https://evil.test/a"/><defs><marker id="arrow"><path d="M0 0L1 1"/></marker></defs><path marker-end="url(#arrow)"/></svg>');
 const t=document.createElement('template');t.innerHTML=svg;
 expect(t.content.querySelector('image,use,foreignObject,animate')).toBeNull();
 expect(svg).not.toContain('evil.test');expect(svg).not.toContain('javascript:');expect(svg).not.toContain('onclick');
 expect(t.content.querySelector('marker#arrow')).not.toBeNull();expect(svg).toContain('url(#arrow)');expect(svg).toContain('label');
});
