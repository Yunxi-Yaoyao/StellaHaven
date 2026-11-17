"""Synthetic pinned speedtest-go TestDuration fixtures, NOT recovered user output.

Pinned server.go:55,62-67 uses four non-omitempty *time.Duration fields:
JSON object members are nanoseconds or null, not a scalar duration.
"""
from copy import deepcopy
import json
import subprocess
import pytest

from app.services import task as svc
from app.schemas.monitor import IperfTaskRead
from tests_isolated.test_throughput_backend_v12 import agent, ToolProcess
from tests_isolated.test_throughput_fix2_v12 import memory
from tests_isolated.test_throughput_fix2_http_v12 import http


def synthetic_go_result():
    return {
        'timestamp': '2026-10-22 00:00:00.000',
        'user_info': None,
        'servers': [{
            'id': '42', 'dl_speed': 12500000, 'ul_speed': 6250000,
            'latency': 12000000, 'jitter': 2000000,
            'test_duration': {
                'ping': 12000000, 'download': 5000000000,
                'upload': None, 'total': 5012000000,
            },
            'name': 'SYNTHETIC contract fixture',
            'vendor_extra': {'source': 'synthetic-not-user-raw'},
        }],
        'fixture_provenance': 'synthetic pinned official shape, not user raw',
    }


def run_agent(agent, monkeypatch, payload):
    proc = ToolProcess(json.dumps(payload))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    result = agent._run_speedtest_once(
        '/fixture/speedtest-go', {'id': 7, 'speedtest_server': '42'}, None)
    assert proc.waits > 0
    return result


@pytest.mark.parametrize('entry', ['agent', 'backend'])
def test_official_duration_object_survives_agent_service_repository_projection(agent, monkeypatch, memory, entry):
    payload = synthetic_go_result()
    before = deepcopy(payload)
    result = (run_agent(agent, monkeypatch, payload) if entry == 'agent'
              else svc._validate_iperf_result('speedtest', payload, '42'))
    assert result == before
    assert payload == before
    row, db = memory
    row.speedtest_server = '42'
    row.created_at = '2026-10-22T00:00:00Z'
    row.duration, row.parallel = 10, 1
    svc.finish_iperf(db, 7, 'done', result)
    assert row.status == 'done'
    assert row.result_json == before
    assert result == before
    assert db.commit.call_count == 1
    assert row.avg_mbps == 100 and row.peak_mbps == 50
    public = IperfTaskRead.model_validate(row).model_dump(mode='json')['result_json']
    assert public['servers'] == before['servers']
    assert public['raw_payload'] == before
    assert public['servers'][0]['test_duration'] == before['servers'][0]['test_duration']


MISSING = object()
DURATION_FIELDS = ('ping', 'download', 'upload', 'total')
VALID_DURATIONS = [
    pytest.param(MISSING, id='absent-legacy'),
    pytest.param(None, id='null-legacy'),
    pytest.param(0, id='scalar-zero-legacy'),
    pytest.param(123456789, id='scalar-ns-legacy'),
    pytest.param(0.5, id='scalar-fraction-legacy'),
    pytest.param(dict.fromkeys(DURATION_FIELDS), id='object-all-null'),
    pytest.param(dict.fromkeys(DURATION_FIELDS, 0), id='object-zero'),
    pytest.param(dict(zip(DURATION_FIELDS, (0.5, 10000000000, None, 1))), id='object-numeric-null'),
]


@pytest.mark.parametrize('location', ['server', 'top'])
@pytest.mark.parametrize('duration', VALID_DURATIONS)
def test_duration_optional_and_legacy_compatibility_is_lossless(agent, monkeypatch, location, duration):
    # Absent/null/scalar were accepted by the pre-fix validators. Scalars are
    # compatibility inputs, NOT a claim that pinned Go emits numeric duration.
    payload = synthetic_go_result()
    obj = payload['servers'][0] if location == 'server' else payload
    obj.pop('test_duration', None)
    if duration is not MISSING:
        obj['test_duration'] = deepcopy(duration)
    before = json.dumps(payload, sort_keys=True)
    result = run_agent(agent, monkeypatch, payload)
    assert result == payload
    assert svc._validate_iperf_result('speedtest', result, '42') == payload
    assert json.dumps(payload, sort_keys=True) == before
    assert json.dumps(result, sort_keys=True) == before


BAD_VALUES = [
    pytest.param(True, id='bool'), pytest.param('1', id='numeric-string'),
    pytest.param('1s', id='duration-string'), pytest.param(-1, id='negative'),
    pytest.param(float('nan'), id='nan'), pytest.param(float('inf'), id='inf'),
    pytest.param(float('-inf'), id='negative-inf'),
    pytest.param([], id='list'), pytest.param({}, id='nested-object'),
    pytest.param(10**400, id='overflow'),
]


def assert_rejected_losslessly(agent, monkeypatch, memory, payload):
    before = json.dumps(payload, sort_keys=True)
    assert run_agent(agent, monkeypatch, payload).get('error')
    with pytest.raises(ValueError, match='test_duration'):
        svc._validate_iperf_result('speedtest', payload, '42')
    row, db = memory
    svc.finish_iperf(db, 7, 'done', payload)
    assert row.status == 'failed'
    assert row.result_json['error']
    evidence = dict(row.result_json)
    evidence.pop('error')
    assert json.dumps(evidence, sort_keys=True) == before
    assert json.dumps(payload, sort_keys=True) == before
    assert db.commit.call_count == 1
    assert not hasattr(row, 'avg_mbps')  # failed evidence is not a measured speed


@pytest.mark.parametrize('location', ['server', 'top'])
@pytest.mark.parametrize('field', DURATION_FIELDS)
@pytest.mark.parametrize('bad', BAD_VALUES)
def test_duration_object_members_fail_closed_without_coercion(agent, monkeypatch, memory, location, field, bad):
    payload = synthetic_go_result()
    obj = payload['servers'][0] if location == 'server' else payload
    obj['test_duration'] = dict.fromkeys(DURATION_FIELDS)
    obj['test_duration'][field] = bad
    assert_rejected_losslessly(agent, monkeypatch, memory, payload)


@pytest.mark.parametrize('location', ['server', 'top'])
@pytest.mark.parametrize('duration', [
    pytest.param('1s', id='string'), pytest.param(True, id='bool'),
    pytest.param(-1, id='negative'), pytest.param(float('nan'), id='nan'),
    pytest.param(float('inf'), id='inf'), pytest.param([], id='list'),
    pytest.param({}, id='empty-object'),
    pytest.param({'total': 1}, id='missing-members'),
    pytest.param(dict.fromkeys((*DURATION_FIELDS, 'future')), id='unknown-member'),
    pytest.param({'Ping': None, 'download': None, 'upload': None, 'total': None}, id='wrong-case'),
])
def test_duration_shape_is_closed(agent, monkeypatch, memory, location, duration):
    payload = synthetic_go_result()
    obj = payload['servers'][0] if location == 'server' else payload
    obj['test_duration'] = duration
    assert_rejected_losslessly(agent, monkeypatch, memory, payload)


@pytest.mark.parametrize('bad', [False, True])
def test_exact_http_result_route_readback_retains_duration_and_node_extra(http, agent, monkeypatch, bad):
    client, row, db = http
    payload = synthetic_go_result()
    if bad:
        payload['servers'][0]['test_duration']['total'] = 'not-a-duration'
        # Authenticated backend also validates reports not produced by this Agent.
        result = payload
    else:
        result = run_agent(agent, monkeypatch, payload)
    before = deepcopy(result)
    row.speedtest_server = '42'
    response = client.post('/agent/iperf-tasks/7/result?status=done',
                           headers={'Authorization': 'Bearer client'}, json=result)
    assert response.status_code == 200
    expected = 'failed' if bad else 'done'
    assert row.status == expected
    assert client.get('/agent/iperf-tasks/7/status',
                      headers={'Authorization': 'Bearer client'}).json() == {'status': expected}
    stored = dict(row.result_json)
    if bad:
        assert stored.pop('error')
    assert stored == before
    assert result == before
    public = IperfTaskRead.model_validate(row).model_dump(mode='json')['result_json']
    assert public['raw_payload']['servers'] == before['servers']
    if not bad:
        assert public['servers'] == before['servers']
        assert row.avg_mbps == 100 and row.peak_mbps == 50


@pytest.mark.parametrize('field,bad', [
    ('dl_speed', None), ('ul_speed', True), ('dl_speed', -1),
    ('latency', '12ms'), ('jitter', float('nan')), ('id', 'different'),
    ('error', ''),
])
def test_valid_duration_never_licenses_other_invalid_measurements(agent, monkeypatch, memory, field, bad):
    payload = synthetic_go_result()
    payload['servers'][0][field] = bad
    assert run_agent(agent, monkeypatch, payload).get('error')
    with pytest.raises(ValueError):
        svc._validate_iperf_result('speedtest', payload, '42')
    row, db = memory
    row.speedtest_server = '42'
    svc.finish_iperf(db, 7, 'done', payload)
    assert row.status == 'failed'
    assert not hasattr(row, 'avg_mbps')
