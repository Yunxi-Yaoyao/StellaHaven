import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
// Resolve from the actual parent, not a potentially unrelated hoisted copy.
const fromCollective = createRequire(require.resolve('opencollective/package.json'));
const minimist = fromCollective('minimist');

test('opencollective minimist rejects prototype pollution', () => {
  try {
    minimist(['--__proto__.stellaDependencyProbe', 'polluted']);
    assert.equal(Object.prototype.stellaDependencyProbe, undefined);
    minimist(['--constructor.prototype.stellaDependencyProbe', 'polluted']);
    assert.equal(Object.prototype.stellaDependencyProbe, undefined);
  } finally {
    delete Object.prototype.stellaDependencyProbe;
  }
});

test('opencollective CLI aliases, flags and positional API remain compatible', () => {
  // Matches src/lib/utils.js and src/commands/postinstall.js in opencollective 1.0.3.
  const result = minimist(['postinstall', '-c', 'stella', '-l', 'logo.png', '-h', '--plain'], {
    alias: { collective: 'c', logo: 'l', help: 'h' },
  });
  assert.deepEqual(result._, ['postinstall']);
  assert.equal(result.collective, 'stella');
  assert.equal(result.c, 'stella');
  assert.equal(result.logo, 'logo.png');
  assert.equal(result.l, 'logo.png');
  assert.equal(result.help, true);
  assert.equal(result.h, true);
  assert.equal(result.plain, true);
});
