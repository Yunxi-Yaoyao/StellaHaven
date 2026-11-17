import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
const require = createRequire(import.meta.url);
const consumer = createRequire(require.resolve('mermaid'));
const entry = process.env.KATEX_TEST_PACKAGE || consumer.resolve('katex');
const katex = require(entry);

test('Mermaid KaTeX API retains fractions, roots, sums and matrices in both output modes', () => {
 for (const output of ['mathml', 'htmlAndMathml']) {
  for (const tex of [String.raw`x^2+\frac{1}{2}`, String.raw`\sqrt{x}+\sum_{i=1}^n i`, String.raw`\begin{pmatrix}a&b\\c&d\end{pmatrix}`]) {
   const rendered = katex.renderToString(tex, {throwOnError:true, displayMode:true, output});
   assert.match(rendered, /<math/);
   assert.doesNotMatch(rendered, /katex-error/);
   if (tex.includes('frac')) assert.match(rendered, /<mfrac>/);
   if (output === 'htmlAndMathml') assert.match(rendered, /katex-html/);
  }
 }
});

test('inherited renderer trust never enables links or external images', () => {
 const options=Object.assign(Object.create({trust:true}), {throwOnError:true,displayMode:true,output:'htmlAndMathml'});
 for (const tex of [String.raw`\href{javascript:alert(1)}{click}`, String.raw`\includegraphics{https://evil.test/image.png}`]) {
  const rendered = katex.renderToString(tex, options);
  assert.doesNotMatch(rendered, /<(?:a|img)\b/, 'inherited trust activated resource-capable rendering');
 }
});

test('polluted Object.prototype trust stays inert in a disposable subprocess', () => {
 // Never pollute the test runner, browser host or another test's realm.
 const child=spawnSync(process.execPath,['--input-type=commonjs','-e',`
 const assert=require('node:assert/strict');const katex=require(${JSON.stringify(entry)});
 Object.prototype.trust=true;
 try {
  for(const tex of [String.raw\`\\href{javascript:alert(1)}{click}\`, String.raw\`\\includegraphics{https://evil.test/image.png}\`]) {
   assert.doesNotMatch(katex.renderToString(tex,{throwOnError:true,displayMode:true,output:'mathml'}), /<(?:a|mglyph)\\b/);
  }
 } finally {delete Object.prototype.trust;}
 `],{encoding:'utf8'});
 assert.equal(child.status,0,child.stderr);
 assert.equal(Object.hasOwn(Object.prototype,'trust'),false);
});
