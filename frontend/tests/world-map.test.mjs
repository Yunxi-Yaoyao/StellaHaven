import test from 'node:test';
import assert from 'node:assert/strict';
import { groupMapNodes, projectMapLinks, parseLocationInput, escapeHtml, mapReasonLabel } from '../src/modules/servers/worldMapHelpers.ts';

const node = (id, latitude, longitude, location_label = null) => ({ id, name: `node-${id}`, status: 'online', latitude, longitude, location_label, location_source: 'nat' });

test('groups identical coordinates and city labels without manufacturing coordinates', () => {
  const input = [node(1, 22.3, 114.2, '香港'), node(2, 22.31, 114.21, '香港'), node(3, 22.3, 114.2, 'HK'), node(4, null, null, '香港')];
  const before = JSON.stringify(input);
  const result = groupMapNodes(input);
  assert.equal(result.groups.length, 1);
  assert.deepEqual(result.groups[0].nodes.map(n => n.id), [1, 2, 3]);
  assert.deepEqual(result.groups[0].coordinate, [114.2, 22.3]);
  assert.deepEqual(result.unknown.map(n => n.id), [4]);
  assert.equal(JSON.stringify(input), before);
});

test('unknown, invalid, zero and distant same-name cities remain honest', () => {
  const {groups, unknown} = groupMapNodes([node(1, 0, 0), node(2, NaN, 20), node(3, 91, 0), node(4, 20, 181), node(5, 10, 20, 'City'), node(6, 40, 70, 'City')]);
  assert.equal(groups.length, 3);
  assert.deepEqual(unknown.map(n => n.id), [2,3,4]);
});

test('configured directed links only: unknown and same-city links are listed, not drawn', () => {
  const groups = groupMapNodes([node(1, 22, 114, 'HK'), node(2, 22, 114, 'HK'), node(3, 35, 140, 'Tokyo'), node(4, null, null)]).groups;
  const links = [
    {id:'a', source:1, target:3, state:'recent'},
    {id:'b', source:1, target:2, state:'stale'},
    {id:'c', source:1, target:null, state:'never'},
    {id:'d', source:1, target:4, state:'unknown'},
  ];
  const {drawable, unplaced} = projectMapLinks(links, groups);
  assert.deepEqual(drawable.map(l => l.id), ['a']);
  assert.deepEqual(drawable[0].coords, [[114,22],[140,35]]);
  assert.deepEqual(unplaced.map(l => l.id), ['b','c','d']);
  assert.equal(drawable.length + unplaced.length, links.length);
  assert.equal(unplaced[0].display_reason, '同城 / 同坐标，见链路详情');
});

test('manual coordinates are finite paired values; clear is explicit', () => {
  assert.deepEqual(parseLocationInput('0', '0', ' 城市 '), { latitude:0, longitude:0, label:'城市' });
  for (const [lat, lon] of [['','0'],['0',''],['91','0'],['0','181'],['NaN','2'],['Infinity','0'],['','']]) {
    assert.throws(() => parseLocationInput(lat, lon, ''), /经纬度/);
  }
});

test('Vue numeric input values validate without trim errors', () => {
  assert.deepEqual(parseLocationInput(22.3, 114.2, ''), { latitude: 22.3, longitude: 114.2, label: null });
  assert.deepEqual(parseLocationInput(0, 0, ''), { latitude: 0, longitude: 0, label: null });
  for (const pair of [[0, ''], ['', 0], [Infinity, 0], [91, 0], ['  ', 0]]) {
    assert.throws(() => parseLocationInput(...pair, ''), /经纬度/);
  }
});
test('reason codes have human-readable labels and safe unknown fallback', () => {
  assert.equal(mapReasonLabel('internal_requires_manual_location'), '内网节点需要人工设置城市位置');
  assert.equal(mapReasonLabel('unmatched_peer'), '对端尚未匹配到已登记节点');
  assert.equal(mapReasonLabel('<img src=x>'), '原因未知');
  assert.equal(mapReasonLabel(null), '');
});

test('tooltip content cannot inject HTML', () => {
  assert.equal(escapeHtml('<img src=x onerror="bad">&'), '&lt;img src=x onerror=&quot;bad&quot;&gt;&amp;');
});
