import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reachable, componentTone, errorDetail } from '../src/modules/servers/serverState.ts';
test('offline installed inventory stays gray; heartbeat expires at 120s', () => {
  const n = {status:'online', last_seen_at:new Date(1000).toISOString()};
  assert.equal(reachable(n, 121000), true);
  assert.equal(reachable(n, 121001), false);
  assert.equal(componentTone({...n,status:'offline'}, true, 1000), 'off');
  assert.equal(componentTone(n, true, 1000), 'ok');
});
test('API conflict detail is retained', () => assert.equal(errorDetail({detail:'节点不在线'}, 'fallback'), '节点不在线'));
