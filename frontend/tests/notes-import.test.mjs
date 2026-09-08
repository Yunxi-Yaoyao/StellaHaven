import { test } from 'node:test';
import assert from 'node:assert/strict';

const helpers = await import('../src/modules/notes/import-helpers.ts');

test('Markdown decoding preserves heading and normalizes UTF-8 BOM / CRLF', () => {
  assert.equal(typeof helpers.decodeImport, 'function', 'decodeImport must exist');
  const result = helpers.decodeImport(new Uint8Array([0xef, 0xbb, 0xbf, ...new TextEncoder().encode('# Heading\r\nbody\r\n')]), 'draft.MD');
  assert.equal(result.content, '# Heading\nbody\n');
  assert.equal(result.title, 'draft');
});

test('Strict decoding offers explicit encoding recovery and rejects binary text', () => {
  assert.throws(() => helpers.decodeImport(new Uint8Array([0xd6, 0xd0]), '中文.md'), /编码/);
  assert.equal(helpers.decodeImport(new Uint8Array([0xd6, 0xd0]), '中文.md', 'gb18030').content, '中');
  assert.equal(helpers.decodeImport(new Uint8Array([0xff, 0xfe, 0x2d, 0x4e]), 'a.md').content, '中');
  assert.equal(helpers.decodeImport(new Uint8Array([0xfe, 0xff, 0x4e, 0x2d]), 'a.md').content, '中');
  assert.throws(() => helpers.decodeImport(new Uint8Array([65, 0, 66]), 'a.md'), /二进制/);
  assert.throws(() => helpers.decodeImport(new Uint8Array([0xff, 0xfe, 0, 0]), 'a.md'), /二进制/);
  assert.equal(helpers.decodeImport(new Uint8Array(), 'empty.md').content, '');
});


test('TXT escapes Markdown and HTML while keeping hard line breaks', () => {
  const text = '# heading\r\n*bold* [x](y) <img> &copy;\nnext';
  assert.equal(helpers.decodeImport(new TextEncoder().encode(text), 'plain.txt').content,
    '\\# heading  \n\\*bold\\* \\[x\\]\\(y\\) &lt;img&gt; &amp;copy;  \nnext');
});


test('Batch validation lists unsupported, directory, oversize and over-count files explicitly', async () => {
  assert.equal(typeof helpers.queueImports, 'function');
  const file = (name, size = 1, webkitRelativePath = '') => ({ name, size, webkitRelativePath });
  const rows = helpers.queueImports([file('a.md'), file('photo.png'), file('z.zip'),
    file('big.txt', helpers.MAX_IMPORT_FILE_BYTES + 1), file('nested.md', 1, 'dir/nested.md')]);
  assert.deepEqual(rows.map(r => r.status), ['pending', 'rejected', 'rejected', 'rejected', 'rejected']);
  assert.match(rows[1].error, /md.*txt/i);
  assert.match(rows[4].error, /目录/);
  const many = helpers.queueImports(Array.from({ length: helpers.MAX_IMPORT_FILES + 1 }, () => file('a.md')));
  assert.equal(many.length, helpers.MAX_IMPORT_FILES + 1);
  assert.equal(many.at(-1).status, 'rejected');
  const heavy = helpers.queueImports(Array.from({ length: 6 }, () => file('a.md', helpers.MAX_IMPORT_FILE_BYTES)));
  assert.equal(heavy.at(-1).status, 'rejected');
});


test('Preparation exposes encoding recovery and relative-image warning without altering Markdown', async () => {
  assert.equal(typeof helpers.prepareImport, 'function');
  const raw = '# Original\n![a](assets/a.png)\n![b][img]\n[img]: ./b.jpg';
  const rows = helpers.queueImports([new File([raw], 'a.md'), new File([new Uint8Array([0xd6, 0xd0])], 'b.txt')]);
  await helpers.prepareImport(rows[0]);
  assert.equal(rows[0].status, 'ready');
  assert.equal(rows[0].content, raw);
  assert.match(rows[0].warning, /相对.*图片/);
  await helpers.prepareImport(rows[1]);
  assert.equal(rows[1].status, 'encoding-error');
  rows[1].encoding = 'gb18030';
  await helpers.prepareImport(rows[1]);
  assert.equal(rows[1].status, 'ready');
  assert.equal(rows[1].content, '中');
  const remote = helpers.queueImports([new File(['![a](https://x/a.png)'], 'r.md')])[0];
  await helpers.prepareImport(remote);
  assert.equal(remote.warning, '');
});


test('Batch creates one note per file with frozen destination, suffixes, progress and failed-only retry', async () => {
  assert.equal(typeof helpers.runImportBatch, 'function');
  const rows = helpers.queueImports([new File(['# Kept'], 'same.md'), new File(['second'], 'same.txt'), new File([''], 'empty.md')]);
  for (const row of rows) await helpers.prepareImport(row);
  const calls = [];
  const target = { workspaceId: 'ws-1', parentId: 'parent-1' };
  let fail = true;
  const create = async payload => {
    assert.equal(rows[calls.length].status, 'importing');
    calls.push(payload);
    target.workspaceId = 'changed'; target.parentId = null;
    if (payload.content === 'second' && fail) throw new Error('server failed');
    return { id: 'doc-' + calls.length };
  };
  await helpers.runImportBatch(rows, target, ['same'], create);
  assert.deepEqual(rows.map(r => r.status), ['success', 'failed', 'success']);
  assert.deepEqual(calls.map(p => p.title), ['same (2)', 'same (3)', 'empty']);
  assert.ok(calls.every(p => p.workspace_id === 'ws-1' && p.parent_id === 'parent-1' && p.status === 'published'));
  assert.equal(calls[0].content, '# Kept');
  assert.equal(calls[2].content, '');
  assert.equal(new Set(calls.map(p => p.file_path)).size, 3);
  assert.match(calls[0].file_path, /same%20%282%29\.md$/);
  const failedPayload = calls[1];
  await helpers.runImportBatch(rows, target, [], async payload => { calls.push(payload); return { id: 'retry' }; });
  assert.equal(calls.length, 4);
  assert.deepEqual(calls[3], failedPayload);
  assert.deepEqual(rows.map(r => r.status), ['success', 'success', 'success']);
});
