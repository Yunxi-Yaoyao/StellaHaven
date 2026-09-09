import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { createPinia, setActivePinia, defineStore } from 'pinia';
import { ref } from 'vue';
globalThis.__VUE_PROD_DEVTOOLS__ = false;
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return { promise, resolve }; };
function storeWith(api) {
  setActivePinia(createPinia());
  const exports = {};
  new Function('require', 'exports', compile(readFileSync(new URL('../src/stores/notes.ts', import.meta.url), 'utf8')))(name => name === 'pinia' ? { defineStore } : name === 'vue' ? { ref } : name.endsWith('/notes') ? api : name.endsWith('useToast') ? { toast() {} } : { ApiError: Error }, exports);
  const store = exports.useNotesStore(); store.workspaceId = 'ws'; return store;
}
test('successful create remains selectable when list read fails', async () => {
  const doc = { id: 'new', workspace_id: 'ws', title: 'new' };
  const store = storeWith({ createDoc: async () => doc, listDocs: async () => { throw Error('read unavailable'); } });
  assert.equal((await store.createNew()).id, 'new');
  assert.equal(store.docs[0].id, 'new');
});
test('older list response cannot overwrite a newer refresh', async () => {
  const old = deferred(); let calls = 0;
  const store = storeWith({ listDocs: () => ++calls === 1 ? old.promise : Promise.resolve([{ id: 'new' }]) });
  const first = store.refreshList(); await store.refreshList(); old.resolve([{ id: 'old' }]); await first;
  assert.equal(store.docs[0].id, 'new');
});
function loader(getDoc) {
  const source = readFileSync(new URL('../src/modules/notes/DocEditor.vue', import.meta.url), 'utf8');
  const section = source.slice(source.indexOf('// ── 加载文档'), source.indexOf('watch(() => props.docId'));
  const state = Object.fromEntries(['doc','title','content','savedTitle','savedContent','savedAt','draftSynced','draftPreview','draftBanner'].map(k => [k, { value: null }]));
  const notices = []; const props = { docId: 'a' };
  const env = { ...state, props, getDoc, toast: s => notices.push(s), isDismissed: () => false, loadBacklinks: async () => {}, loadAttachMeta: async () => {} };
  const load = new Function(...Object.keys(env), compile(section) + '\nreturn load;')(...Object.values(env));
  return { ...state, props, load, notices };
}
test('late document response cannot replace the currently selected note', async () => {
  const old = deferred(); const h = loader(id => id === 'a' ? old.promise : Promise.resolve({ id: 'b', title: 'B', content: 'B' }));
  const first = h.load('a'); h.props.docId = 'b'; await h.load('b'); old.resolve({ id: 'a', title: 'A', content: 'A' }); await first;
  assert.equal(h.doc.value.id, 'b'); assert.equal(h.content.value, 'B');
});
test('document read error is surfaced rather than an unhandled rejection', async () => {
  const h = loader(async () => { throw Error('offline'); });
  await h.load('a'); assert.equal(h.notices.length, 1);
});

test('directory inventory remains complete during search and removes moved/deleted pages', async () => {
  let all = [{id:'parent',workspace_id:'ws',title:'Parent',updated_at:'a'}, {id:'child',workspace_id:'ws',parent_id:'parent',title:'Child',updated_at:'a'}];
  const store = storeWith({listDocs:async()=>all,searchDocs:async()=>[all[0]]});
  await store.refreshList(); store.searchQuery = 'Parent'; await store.refreshList();
  assert.deepEqual(store.docs.map(d=>d.id),['parent']);
  assert.deepEqual(store.allDocs?.map(d=>d.id),['parent','child']);
  assert.equal(store.childCount('parent'),1);
  store.requestDelete(all[0]);
  assert.equal(store.pendingDelete.childCount,1);
  all=[all[0]]; await store.refreshList();
  assert.deepEqual(store.allDocs.map(d=>d.id),['parent']);
  store.resetSession(); assert.deepEqual(store.allDocs,[]);
});
