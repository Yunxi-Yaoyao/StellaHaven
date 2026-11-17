import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const url = require('url/');
const fromUrl = createRequire(require.resolve('url/'));
const qs = fromUrl('qs');
test('qs parse/stringify does not call attacker-controlled non-callable isBuffer', () => {
  for (const options of [{plainObjects:true}, {allowPrototypes:true}]) {
    const parsed = qs.parse('x%5Bconstructor%5D%5BisBuffer%5D=y', options);
    assert.doesNotThrow(() => qs.stringify(parsed));
  }
});
test('qs bracket comma values enforce the configured array limit', () => {
  assert.throws(() => qs.parse('a[]=1,2,3,4', {comma:true,arrayLimit:3,throwOnLimitExceeded:true}), RangeError);
});
test('actual browser url dependency preserves model URLs, query arrays and resolution', () => {
  const source = 'https://models.example/model/model3.json?token=a%2Bb&texture[]=one&texture[]=two#idle';
  const parsed = url.parse(source, true);
  assert.equal(parsed.query.token, 'a+b');
  assert.deepEqual(parsed.query.texture, ['one','two']);
  assert.equal(url.format(parsed), source);
  assert.equal(url.resolve(source, '../textures/纹理.png?cache=1'), 'https://models.example/textures/纹理.png?cache=1');
  const polluted = url.parse('/model.json?constructor[isBuffer]=bad&__proto__[stella]=yes', true);
  assert.doesNotThrow(() => url.format(polluted));
  assert.equal({}.stella, undefined);
});
