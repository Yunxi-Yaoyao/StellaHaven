import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as h from '../src/modules/notes/import-helpers.ts';

test('ZIP is intercepted but never enters the flat text decoder', () => {
  assert.equal(h.isImportFilename('Notes.ZIP'), true);
  assert.equal(h.queueImports([new File(['broken'], 'notes.zip')])[0].status, 'rejected');
});

test('destination hierarchy includes nested, orphan and cyclic pages once', () => {
  assert.equal(typeof h.importTreeRows, 'function');
  const rows = h.importTreeRows([{id:'child',parent_id:'root',title:'Child'}, {id:'root',parent_id:null,title:'Root'}, {id:'orphan',parent_id:'gone',title:'Orphan'}, {id:'loop',parent_id:'loop',title:'Loop'}]);
  assert.deepEqual(rows.map(x => [x.id,x.depth]), [['root',0],['child',1],['orphan',0],['loop',0]]);
});
