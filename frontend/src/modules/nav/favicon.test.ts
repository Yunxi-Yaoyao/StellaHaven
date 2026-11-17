import {it,expect} from 'vitest';
import {faviconCandidates} from './favicon';
it('probes at most three public origin paths without query, secrets or service ports',()=>{
 expect(faviconCandidates('https://www.wikipedia.org/private?token=secret')).toEqual(['https://www.wikipedia.org/favicon.ico','https://www.wikipedia.org/apple-touch-icon.png','https://www.wikipedia.org/favicon.png']);
 for(const u of ['http://localhost/a','http://127.0.0.1','http://2130706433','http://[::1]','https://router.local','http://example.com:24532','https://u:p@example.com'])expect(faviconCandidates(u)).toEqual([]);
});
