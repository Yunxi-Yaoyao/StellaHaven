import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=(file:string)=>readFileSync(new URL(file,import.meta.url),'utf8');
test('server charts never import all ECharts modules',()=>{
 for(const f of ['NodeDetailView.vue','OverviewView.vue','ToolsView.vue','MonitorDetailModal.vue','ServerWorldMap.vue']) {
  assert.doesNotMatch(source('./'+f), /import \* as echarts from ["']echarts["']/);
 }
});
test('route views and optional modals are async boundaries',()=>{
 assert.doesNotMatch(source('./ServersHome.vue'),/import (OverviewView|ToolsView|DockerView) from/);
 assert.doesNotMatch(source('./NodeDetailView.vue'),/import (MetricsCompare|MonitorDetailModal) from/);
 assert.doesNotMatch(source('./OverviewView.vue'),/import (MonitorDetailModal|ServerWorldMap) from/);
});
