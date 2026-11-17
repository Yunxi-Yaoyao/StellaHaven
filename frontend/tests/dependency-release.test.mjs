// gh-pages is an upstream release tool accidentally declared as a runtime dep.
// Resolve it from Pixi's actual package, not an unrelated hoisted installation.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {execFileSync} from 'node:child_process';
const require = createRequire(import.meta.url);
const pixi = createRequire(require.resolve('pixi-live2d-display/cubism4'));
const ghRoot = dirname(pixi.resolve('gh-pages/package.json'));
const {uniqueDirs, copy} = require(join(ghRoot, 'lib/util.js'));

test('gh-pages directory keys are inert, including prototype property names', () => {
  // This exercises the advisory's actual uniqueDirs sink. It is not a claim
  // that the old implementation overwrites global Object.prototype by itself.
  const before = Object.getOwnPropertyDescriptors(Object.prototype);
  assert.deepEqual(uniqueDirs(['__proto__/a', 'constructor/b', 'toString/c', 'ordinary/d', 'ordinary/e']),
    ['__proto__', 'constructor', 'toString', 'ordinary']);
  assert.deepEqual(Object.getOwnPropertyDescriptors(Object.prototype), before);
});

test('gh-pages upgraded async copy API preserves nested files and rejects missing inputs', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'gh-copy-'));
  try {
    mkdirSync(join(dir, 'in/nested'), {recursive: true});
    mkdirSync(join(dir, 'out'));
    writeFileSync(join(dir, 'in/nested/page.html'), '<p>valid page</p>');
    await copy(['nested/page.html'], join(dir, 'in'), join(dir, 'out'));
    assert.equal(readFileSync(join(dir, 'out/nested/page.html'), 'utf8'), '<p>valid page</p>');
    await assert.rejects(copy(['missing.html'], join(dir, 'in'), join(dir, 'out')));
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('Pixi release CLI retains -d and user/branch/dest/add options without any push', () => {
  const dir = mkdtempSync(join(tmpdir(), 'gh-release-'));
  const env = {...process.env, HOME: dir, XDG_CONFIG_HOME: dir,
    CACHE_DIR: join(dir, 'cache'), GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_ALLOW_PROTOCOL: 'file', GIT_TERMINAL_PROMPT: '0'};
  // Do not allow inherited config injection to reroute a local fixture repository.
  for (const key of Object.keys(env)) {
    if (/^GIT_CONFIG_(COUNT|KEY_|VALUE_|PARAMETERS)/.test(key) || /^GIT_(DIR|WORK_TREE|INDEX_FILE|OBJECT_DIRECTORY|ALTERNATE_OBJECT_DIRECTORIES)$/.test(key)) delete env[key];
  }
  const git = (...args) => execFileSync('git', args, {cwd: dir, env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}).trim();
  try {
    writeFileSync(join(dir, 'package.json'), '{"name":"isolated-release-test","private":true}');
    git('init', '--bare', '--initial-branch=gh-pages', 'remote.git');
    git('init', '--initial-branch=gh-pages', 'seed');
    git('-C', 'seed', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'seed');
    const seed = git('-C', 'seed', 'rev-parse', 'HEAD');
    // Populate the local bare object database without git push or a network remote.
    git('--git-dir=remote.git', 'fetch', join(dir, 'seed'), 'gh-pages:gh-pages');
    mkdirSync(join(dir, 'site/nested'), {recursive: true});
    writeFileSync(join(dir, 'site/index.html'), '<h1>first</h1>');
    writeFileSync(join(dir, 'site/nested/page.html'), 'nested');
    writeFileSync(join(dir, 'site/.nojekyll'), '');
    const cli = (...extra) => execFileSync(process.execPath, [join(ghRoot, 'bin/gh-pages.js'),
      '-d', 'site', '-r', join(dir, 'remote.git'), '--no-push', '-b', 'gh-pages', '-e', 'docs',
      '-u', 'Release Fixture <fixture@example.invalid>', '--dotfiles', ...extra],
      {cwd: dir, env, encoding: 'utf8', timeout: 30000});
    assert.match(cli(), /Published/);
    const caches = readdirSync(join(dir, 'cache/gh-pages'));
    assert.equal(caches.length, 1);
    const checkout = join(dir, 'cache/gh-pages', caches[0]);
    assert.equal(readFileSync(join(checkout, 'docs/index.html'), 'utf8'), '<h1>first</h1>');
    assert.equal(readFileSync(join(checkout, 'docs/.nojekyll'), 'utf8'), '');
    assert.equal(git('-C', checkout, 'log', '-1', '--format=%an <%ae>'), 'Release Fixture <fixture@example.invalid>');
    writeFileSync(join(dir, 'site/index.html'), '<h1>second</h1>');
    assert.match(cli('--add'), /Published/);
    assert.equal(readFileSync(join(checkout, 'docs/index.html'), 'utf8'), '<h1>second</h1>');
    assert.equal(readFileSync(join(checkout, 'docs/nested/page.html'), 'utf8'), 'nested');
    assert.equal(git('--git-dir=remote.git', 'rev-parse', 'gh-pages'), seed, 'no push must leave remote unchanged');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
