import { test } from 'node:test';
import assert from 'node:assert/strict';
import { waitForTask } from './taskWait.ts';

test('bounds waits, aborts requests, suppresses late results and distinguishes terminal outcomes', { timeout: 1000 }, async () => {
  for (const status of ['failed', 'cancelled']) {
    assert.equal((await waitForTask(async () => ({ status }), { timeoutMs: 15 })).status, status);
  }
  let calls = 0;
  for (const status of [401, 403, 404]) {
    calls = 0;
    await assert.rejects(waitForTask(async () => { calls++; throw Object.assign(new Error('http'), { status }); }), /http/);
    assert.equal(calls, 1);
  }
  calls = 0;
  await assert.rejects(waitForTask(async () => { calls++; throw new Error('network'); }, { intervalMs: 1, maxTransientErrors: 2 }), /network/);
  assert.equal(calls, 3);
  let requestSignal: AbortSignal | undefined;
  await assert.rejects(waitForTask(signal => { requestSignal = signal; return new Promise(() => {}); }, { timeoutMs: 20, requestTimeoutMs: 5 }), { name: 'TaskWaitTimeoutError' });
  assert.equal(requestSignal?.aborted, true);
  const controller = new AbortController();
  const waiting = waitForTask(async () => { await new Promise(r => setTimeout(r, 20)); return { status: 'done' }; }, { signal: controller.signal });
  controller.abort();
  await assert.rejects(waiting, { name: 'AbortError' });
  calls = 0;
  await assert.rejects(waitForTask(async () => { calls++; return { status: 'pending' }; }, { signal: controller.signal }), { name: 'AbortError' });
  assert.equal(calls, 0);
  const sleepAbort = new AbortController();
  const sleeping = waitForTask(async () => ({ status: 'running' }), { signal: sleepAbort.signal, intervalMs: 10000 });
  setTimeout(() => sleepAbort.abort(), 5);
  await assert.rejects(sleeping, { name: 'AbortError' });
  await assert.rejects(waitForTask(async () => ({ status: 'running' }), { timeoutMs: 10, intervalMs: 10000 }), { name: 'TaskWaitTimeoutError' });
});

test('returns done after sequential pending requests', async () => {
  let calls = 0, active = 0, peak = 0;
  const result = await waitForTask(async () => {
    active++; peak = Math.max(peak, active);
    await new Promise(r => setTimeout(r, 2)); active--;
    return { status: ++calls === 3 ? 'done' : 'pending' };
  }, { intervalMs: 1 });
  assert.equal(result.status, 'done'); assert.equal(calls, 3); assert.equal(peak, 1);
});
