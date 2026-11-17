import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createApp, nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../../api/client', () => ({ api: mocks.api }));
vi.mock('./chartRuntime', () => ({
  init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }),
  getInstanceByDom: () => null,
}));
import Tools from './ToolsView.vue';

let app: ReturnType<typeof createApp> | undefined;
let commands: any[] = [];
let response: any;
const serverTable = '[ 1345] 1.25km 2.50ms  Fixture HK\n[ 5678] 2km 4ms  Fixture TW\n[ 0] 1km 1ms  Invalid ID';
const flush = async () => {
  for (let i = 0; i < 20; i++) { await Promise.resolve(); await nextTick(); }
};
const fetchButton = () => document.querySelector<HTMLButtonElement>('.st-fetch')!;
const completion = () => [...document.querySelectorAll<HTMLElement>('[role="status"]')]
  .find(el => /已获取 \d+ 个测速服务器喵~/.test(el.textContent || ''));

async function choose(label: string, value: string) {
  const field = [...document.querySelectorAll<HTMLElement>('.form-row')]
    .find(row => row.querySelector('label')?.textContent?.trim().startsWith(label))!;
  field.querySelector<HTMLButtonElement>('.dd-btn')!.click();
  await flush();
  const option = [...field.querySelectorAll<HTMLButtonElement>('[role="option"]')]
    .find(button => button.querySelector('.dd-item-label')?.textContent?.trim() === value);
  expect(option, `option ${value}`).toBeTruthy();
  option!.click();
  await flush();
}

async function mountSFC() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
  ] });
  await router.push('/fixture');
  const host = document.createElement('div');
  document.body.append(host);
  app = createApp(Tools, { tool: 'iperf' });
  app.use(router);
  app.mount(host);
  await flush();
  await choose('模式', '公共 speedtest');
}

function baseApi(path: string, opts: any = {}) {
  if (path === '/nodes/') return Promise.resolve([
    { id: 1, name: 'Public HK', platform: 'linux', status: 'online', net_type: 'public', last_seen_at: new Date().toISOString() },
    { id: 2, name: 'Private LAN', platform: 'linux', status: 'online', net_type: 'private', last_seen_at: new Date().toISOString() },
  ]);
  if (path === '/commands' && opts.method === 'POST') {
    commands = [response];
    return Promise.resolve(response);
  }
  if (path === '/commands') return Promise.resolve(commands);
  if (['/iperf-tasks', '/mtr-tasks?trigger=manual', '/component-installs'].includes(path)) return Promise.resolve([]);
  throw Error('Unexpected fixture request ' + path);
}

beforeEach(() => {
  commands = [];
  response = { id: 7, status: 'done', exit_code: 0, stdout: serverTable, stderr: '' };
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  mocks.api.mockImplementation(baseApi);
});
afterEach(() => {
  app?.unmount(); app = undefined;
  document.body.innerHTML = '';
  vi.useRealTimers(); vi.restoreAllMocks(); vi.clearAllMocks();
});

it('shows a persistent completion status with the parsed usable count and allows fetching again', async () => {
  await mountSFC();
  expect(completion()).toBeUndefined();
  expect(fetchButton().textContent).toBe('获取列表');
  fetchButton().click();
  await flush();
  expect(completion()?.textContent).toBe('已获取 2 个测速服务器喵~');
  expect(fetchButton().textContent).toBe('重新获取');
  expect(fetchButton().disabled).toBe(false);
  await vi.advanceTimersByTimeAsync(30000);
  await flush();
  expect(completion()?.textContent).toBe('已获取 2 个测速服务器喵~');
  await choose('测速服务器', 'Fixture HK · 2.50ms · #1345');
  expect(completion()?.textContent).toBe('已获取 2 个测速服务器喵~');
});

it('clears the previous completion as soon as a retry starts, blocks duplicates, then reports the new count', async () => {
  await mountSFC();
  fetchButton().click(); await flush();
  expect(completion()?.textContent).toBe('已获取 2 个测速服务器喵~');
  let release!: (value: any) => void;
  const held = new Promise(resolve => { release = resolve; });
  mocks.api.mockImplementation((path: string, opts: any = {}) =>
    path === '/commands' && opts.method === 'POST' ? held : baseApi(path, opts));
  fetchButton().click(); await flush();
  expect(completion()).toBeUndefined();
  expect(fetchButton().textContent).toBe('拉取中喵~');
  expect(fetchButton().disabled).toBe(true);
  fetchButton().click(); await flush();
  expect(mocks.api.mock.calls.filter(([path, opts]) => path === '/commands' && opts?.method === 'POST')).toHaveLength(2);
  commands = [{ id: 8, status: 'done', exit_code: 0, stdout: '{"servers":[{"id":9999,"name":"New fixture"}]}' }];
  release(commands[0]); await flush();
  expect(completion()?.textContent).toBe('已获取 1 个测速服务器喵~');
  expect(fetchButton().textContent).toBe('重新获取');
});

it('clears completed server count and choices when the client changes', async () => {
  await mountSFC();
  fetchButton().click(); await flush();
  expect(completion()).toBeTruthy();
  await choose('客户端', 'Public HK · 公网');
  expect(completion()).toBeUndefined();
  expect(fetchButton().textContent).toBe('获取列表');
  expect(fetchButton().disabled).toBe(false);
  const row = document.querySelector('.st-server-field')!;
  row.querySelector<HTMLButtonElement>('.dd-btn')!.click(); await flush();
  expect([...row.querySelectorAll('[role="option"]')].map(el => el.textContent?.trim())).toEqual(['自动（延迟最低）']);
});

it.each([
  ['nonzero exit with partial rows', { status: 'done', exit_code: 23, stdout: serverTable, stderr: 'fixture refusal' }, 'fixture refusal'],
  ['failed command with rows', { status: 'failed', stdout: serverTable, stderr: 'fixture failure' }, 'fixture failure'],
  ['cancelled command with rows', { status: 'cancelled', stdout: serverTable }, '获取服务器列表失败'],
  ['empty stdout', { status: 'done', stdout: '' }, '节点未返回列表'],
  ['empty JSON array', { status: 'done', stdout: '[]' }, '没有返回可识别'],
  ['empty JSON wrapper', { status: 'done', stdout: '{"servers":[]}' }, '没有返回可识别'],
  ['unrecognized output', { status: 'done', stdout: 'Not a server list' }, '没有返回可识别'],
  ['filtered invalid IDs', { status: 'done', stdout: '[{"id":0},{"id":"oops"}]' }, '没有返回可识别'],
])('does not retain completion after a retry returns %s', async (_name, result, error) => {
  await mountSFC(); fetchButton().click(); await flush();
  expect(completion()).toBeTruthy();
  response = { id: 8, exit_code: 0, stderr: '', ...result };
  fetchButton().click(); await flush();
  expect(completion()).toBeUndefined();
  expect(document.querySelector('.iperf-error')?.textContent).toContain(error);
  expect(fetchButton().textContent).toBe('获取列表');
  expect(fetchButton().disabled).toBe(false);
});

it.each([
  ['API error', { detail: 'fixture API unavailable' }],
  ['transport abort', new DOMException('Aborted fixture request', 'AbortError')],
])('does not retain completion after a retry rejects with %s', async (_name, error) => {
  await mountSFC(); fetchButton().click(); await flush();
  expect(completion()).toBeTruthy();
  mocks.api.mockImplementation((path: string, opts: any = {}) =>
    path === '/commands' && opts.method === 'POST' ? Promise.reject(error) : baseApi(path, opts));
  fetchButton().click(); await flush();
  expect(completion()).toBeUndefined();
  expect(document.querySelector('.iperf-error')?.textContent).toBeTruthy();
  expect(fetchButton().disabled).toBe(false);
});

it.each(['before', 'after'])('ignores the old node response released %s the new node succeeds', async order => {
  await mountSFC();
  let releaseOld!: (value: any) => void;
  let releaseNew!: (value: any) => void;
  const oldResponse = new Promise(resolve => { releaseOld = resolve; });
  const newResponse = new Promise(resolve => { releaseNew = resolve; });
  let submissions = 0;
  mocks.api.mockImplementation((path: string, opts: any = {}) => {
    if (path === '/commands' && opts.method === 'POST') return ++submissions === 1 ? oldResponse : newResponse;
    return baseApi(path, opts);
  });
  fetchButton().click(); await flush();
  await choose('客户端', 'Public HK · 公网');
  expect(completion()).toBeUndefined();
  expect(fetchButton().disabled).toBe(false);
  fetchButton().click(); await flush();
  const stale = { id: 7, status: 'done', exit_code: 0, stdout: serverTable };
  if (order === 'before') {
    releaseOld(stale); await flush();
    expect(completion()).toBeUndefined();
    expect(fetchButton().disabled).toBe(true);
    expect(fetchButton().textContent).toBe('拉取中喵~');
  }
  commands = [{ id: 8, status: 'done', exit_code: 0, stdout: '[ 9999] 1km 1ms  Current node only' }];
  releaseNew(commands[0]); await flush();
  if (order === 'after') { releaseOld(stale); await flush(); }
  expect(completion()?.textContent).toBe('已获取 1 个测速服务器喵~');
  expect(fetchButton().disabled).toBe(false);
  const row = document.querySelector('.st-server-field')!;
  row.querySelector<HTMLButtonElement>('.dd-btn')!.click(); await flush();
  expect(row.textContent).toContain('Current node only');
  expect(row.textContent).not.toContain('Fixture HK');
});

it.each(['client change', 'unmount'])('aborts the in-flight list read on %s and never reports its late result', async action => {
  await mountSFC();
  let signal: AbortSignal | undefined;
  let release!: (value: any) => void;
  const held = new Promise(resolve => { release = resolve; });
  mocks.api.mockImplementation((path: string, opts: any = {}) => {
    if (path === '/commands' && opts.method !== 'POST') { signal = opts.signal; return held; }
    return baseApi(path, opts);
  });
  fetchButton().click(); await flush();
  expect(signal).toBeTruthy();
  expect(signal!.aborted).toBe(false);
  expect(completion()).toBeUndefined();
  if (action === 'client change') await choose('客户端', 'Public HK · 公网');
  else { app!.unmount(); app = undefined; }
  await flush();
  expect(signal!.aborted).toBe(true);
  release([{ id: 7, status: 'done', exit_code: 0, stdout: serverTable }]); await flush();
  expect(completion()).toBeUndefined();
  if (action === 'client change') {
    expect(fetchButton().disabled).toBe(false);
    expect(document.querySelector('.iperf-error')).toBeNull();
  }
});
