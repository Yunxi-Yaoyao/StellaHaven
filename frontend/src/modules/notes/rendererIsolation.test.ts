import {expect, it} from 'vitest';
import {sanitizeNoteHtml} from './noteHtml';
import mermaid from 'mermaid';

it('Mermaid sanitation hooks cannot change imported-note sanitation', async () => {
 const dirty='<a href="https://example.com" target="_blank">ordinary</a><a data-temp-href-target="injected">marker</a>';
 const before=sanitizeNoteHtml(dirty);
 mermaid.initialize({startOnLoad:false,securityLevel:'strict',htmlLabels:true});
 await mermaid.parse('flowchart LR\nA[Start]-->B[End]');
 expect(sanitizeNoteHtml(dirty)).toBe(before);
 const template=document.createElement('template');template.innerHTML=sanitizeNoteHtml(dirty);
 expect(template.content.querySelector('a[target]')).toBeNull();
});
