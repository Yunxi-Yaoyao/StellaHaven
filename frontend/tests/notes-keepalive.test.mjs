import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const editor = readFileSync(new URL('../src/modules/notes/DocEditor.vue', import.meta.url), 'utf8');
test('draft socket pauses, resumes once, and ignores late close after destruction', () => {
  const hooks = {}, sockets = [], timers = new Map(); let n = 0, watcher;
  class Socket { static OPEN = 1; readyState = 1; constructor() { sockets.push(this); } close() { this.closed = true; this.onclose?.(); } send() {} }
  const vue = { watch: (_ref, cb) => { watcher = cb; cb('a'); }, onActivated: cb => hooks.activate = cb, onDeactivated: cb => hooks.deactivate = cb, onBeforeUnmount: cb => hooks.destroy = cb, onUnmounted: cb => hooks.destroy = cb };
  const exports = {};
  new Function('require', 'exports', 'WebSocket', 'location', 'setTimeout', 'clearTimeout', compile(readFileSync(new URL('../src/composables/useDraftSocket.ts', import.meta.url), 'utf8')))(() => vue, exports, Socket, { protocol: 'http:', host: 'test' }, cb => { timers.set(++n, cb); return n; }, id => timers.delete(id));
  exports.useDraftSocket({ value: 'a' }, { value: 'test' }, () => {});
  assert.equal(typeof hooks.deactivate, 'function');
  hooks.activate(); assert.equal(sockets.length, 1);
  const lateClose = sockets[0].onclose;
  hooks.deactivate(); assert.equal(sockets[0].onclose, null); assert.equal(timers.size, 0);
  lateClose(); watcher('a'); assert.equal(timers.size, 0); assert.equal(sockets.length, 1);
  hooks.activate(); hooks.activate(); assert.equal(sockets.length, 2);
  const finalClose = sockets[1].onclose; hooks.destroy(); finalClose(); hooks.activate();
  assert.equal(timers.size, 0); assert.equal(sockets.length, 2);
});
test('editor hooks retain state while pausing and idempotently resuming resources', () => {
  const section = editor.slice(editor.indexOf('let listenersActive ='), editor.indexOf('function fmtDraftTime'));
  const hooks = {}, listeners = new Set(), timers = new Set(), loads = []; let flushed = 0;
  const env = { ownsSession: () => true, editorActive: true, loadSequence: 0, draftTimer: 123, tickTimer: null, nowTick: { value: 0 }, onWinResize() {}, onKey() {}, renderMermaid() {}, props: { docId: 'a' }, load: (...args) => loads.push(args), flushDraft: () => flushed++, window: { addEventListener: name => listeners.add(name), removeEventListener: name => listeners.delete(name) }, setInterval: () => { timers.add(1); return 1; }, clearInterval: id => timers.delete(id), clearTimeout() {}, onMounted: cb => hooks.mount = cb, onActivated: cb => hooks.activate = cb, onDeactivated: cb => hooks.deactivate = cb };
  new Function(...Object.keys(env), compile(section))(...Object.values(env));
  hooks.mount(); hooks.activate(); assert.equal(timers.size, 1); assert.equal(loads.length, 0);
  hooks.deactivate(); assert.equal(flushed, 1); assert.equal(timers.size, 0); assert.equal(listeners.size, 0);
  hooks.activate(); assert.equal(timers.size, 1); assert.equal(listeners.size, 2); assert.deepEqual(loads, [['a', true]]);
});
test('background document response cannot overwrite edits made while awaiting it', async () => {
  const section = editor.slice(editor.indexOf('// ── 加载文档'), editor.indexOf('watch(() => props.docId'));
  let resolve; const pending = new Promise(r => resolve = r);
  const state = Object.fromEntries(['doc','title','content','savedTitle','savedContent','savedAt','draftSynced','draftPreview','draftBanner'].map(k => [k, { value: null }]));
  state.doc.value = { id: 'a' }; state.title.value = state.savedTitle.value = 'A'; state.content.value = state.savedContent.value = 'old';
  const env = { ...state, props: { docId: 'a' }, getDoc: () => pending, dirty: { get value() { return state.content.value !== state.savedContent.value; } }, toast() {}, isDismissed: () => false, loadBacklinks: async () => {}, loadAttachMeta: async () => {} };
  const load = new Function(...Object.keys(env), compile(section) + '\nreturn load;')(...Object.values(env));
  const request = load('a', true); state.content.value = 'local edit'; resolve({ id: 'a', title: 'A', content: 'remote' }); await request;
  assert.equal(state.content.value, 'local edit');
});
