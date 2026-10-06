import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequestLane, createPoller, mapBounded } from './polling.ts';

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

test('slow request is singleflight and next tick waits for completion', async () => {
  let calls = 0, active = 0, max = 0;
  const poll = createPoller(async signal => {
    calls++; active++; max = Math.max(max, active);
    await sleep(50);
    active--;
    assert.equal(signal.aborted, false);
  }, 10);
  poll.start();
  await sleep(35);
  assert.equal(calls, 1);
  await poll.run();
  assert.equal(max, 1);
  poll.stop();
  const old = calls;
  await sleep(30);
  assert.equal(calls, old);
});

test('reset before the first microtask prevents even starting the fetch', async () => {
  const lane=createRequestLane();
  let calls=0;
  const task=lane.run(async()=>{calls++;});
  lane.reset();
  await task;
  assert.equal(calls,0);
});

test('window replacement aborts old fetch and new generation cannot be cleared by old result', async () => {
  const lane = createRequestLane();
  let oldSignal: AbortSignal | undefined;
  const old = lane.run(async signal => { oldSignal = signal; await sleep(20); });
  await Promise.resolve(); // allow the mocked fetch to enter its pending state
  lane.reset();
  assert.equal(oldSignal?.aborted, true);
  let calls = 0;
  const fresh = lane.run(async () => { calls++; await sleep(35); });
  await old;
  await lane.run(async () => { calls++; });
  await fresh;
  assert.equal(calls, 1);
});

test('abort stops queued interface fetches and concurrency is finite', async () => {
  const controller = new AbortController();
  let active = 0, max = 0, calls = 0;
  await mapBounded(Array.from({ length: 10 }, (_, i) => i), 3, async () => {
    calls++; active++; max = Math.max(max, active);
    await sleep(5); active--; controller.abort();
  }, controller.signal);
  assert.equal(max, 3);
  assert.equal(calls, 3);
});
