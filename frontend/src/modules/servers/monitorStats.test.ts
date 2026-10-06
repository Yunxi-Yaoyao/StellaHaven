import {test} from 'node:test';
import assert from 'node:assert/strict';
import { summarizeMonitorPoints } from './monitorStats.ts';

test('uneven buckets use raw sample weights for availability latency and loss',()=>{
 const result=summarizeMonitorPoints([
  {ts:'a',success:true,latency_ms:10,loss_pct:0,sample_count:1000,success_count:999,latency_count:999,loss_count:1000},
  {ts:'b',success:false,latency_ms:100,loss_pct:100,sample_count:10,success_count:1,latency_count:1,loss_count:10},
 ]);
 assert.equal(result.total,1010);
 assert.equal(result.avail,1000/1010*100);
 assert.equal(result.avgLat,(999*10+100)/1000);
 assert.equal(result.loss,1000/1010);
});

test('raw points remain backward-compatible and unavailable latencies are ignored',()=>{
 assert.deepEqual(summarizeMonitorPoints([{ts:'a',success:true,latency_ms:10,loss_pct:null},{ts:'b',success:false,latency_ms:500,loss_pct:null}]),
 {total:2,avail:50,avgLat:10,loss:50});
});
