"""TR01: real service/repository, memory identity-map only; HTTP added separately."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.services import task as svc
from tests_isolated.test_throughput_backend_v12 import agent, ToolProcess, StreamProcess, client_task
import ast, os, shutil, subprocess, re
from pathlib import Path


def test_inventory_only_cli_is_not_ready_and_can_install_go(agent, monkeypatch):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'agent/stella_agent.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Agent')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_check_components')
    ns = agent._run_speedtest.__globals__
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<actual-inventory>', 'exec'), ns)
    agent._check_components = ns['_check_components'].__get__(agent)
    monkeypatch.setattr(shutil, 'which', lambda x: '/fixture/'+x if x in ('speedtest-cli', 'speedtest') else None)
    monkeypatch.setattr(os.path, 'isfile', lambda _: False)
    agent._comp_version = Mock(return_value=None)
    agent._monitoring_capability = agent._check_firewall = agent._check_docker = lambda: {}
    result = agent._check_components()
    assert result['speedtest']['installed'] is False  # UI offers install when false
    assert '未安装 speedtest-go' in agent._run_speedtest({'id': 7})['error']
    agent._run_speedtest_once = Mock(return_value={'fixture': True})
    monkeypatch.setattr(shutil, 'which', lambda x: '/fixture/speedtest-go' if x == 'speedtest-go' else None)
    assert agent._check_components()['speedtest']['installed'] is True
    assert agent._run_speedtest({'id': 7}) == {'fixture': True}
    assert agent._run_speedtest_once.call_args.args[0] == '/fixture/speedtest-go'


def test_inventory_and_execution_prefer_same_agent_go(agent, monkeypatch):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'agent/stella_agent.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Agent')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_check_components')
    ns = agent._run_speedtest.__globals__
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<actual-inventory>', 'exec'), ns)
    agent._check_components = ns['_check_components'].__get__(agent)
    monkeypatch.setattr(shutil, 'which', lambda x: '/path/'+x)
    monkeypatch.setattr(os.path, 'isfile', lambda _: True)
    monkeypatch.setattr(os, 'access', lambda *a: True)
    agent._comp_version = Mock(return_value='fixture')
    agent._monitoring_capability = agent._check_firewall = agent._check_docker = lambda: {}
    agent._check_components()
    discovered = [c.args[0] for c in agent._comp_version.call_args_list if 'speedtest' in str(c.args[0])][0]
    agent._run_speedtest_once = Mock(return_value={})
    agent._run_speedtest({'id': 7})
    assert discovered == agent._run_speedtest_once.call_args.args[0]


GO = {'servers': [{'id': '42', 'dl_speed': 12500000, 'ul_speed': 6250000, 'latency': 12000000, 'jitter': 2000000}]}
IPERF = {'avg_bitrate': 8e6, 'peak_bitrate': None, 'total_bytes': 1000000, 'duration': 1, 'lost_pct': None}
NATIVE = {'end': {'sum_received': {'bits_per_second': 8e6, 'bytes': 1000000, 'seconds': 1}}}
OOKLA = {'download': {'bandwidth': 12500000}, 'upload': {'bandwidth': 6250000}, 'ping': {'latency': 12, 'jitter': 2}}
CLI = {'download': 100000000, 'upload': 50000000, 'ping': 12}

@pytest.fixture
def memory():
    row = SimpleNamespace(id=7, status='running', mode='speedtest', direction='forward', speedtest_server=None,
                          progress_json=[], result_json=None, client_node_id=1, server_node_id=2, server_started=True)
    db = SimpleNamespace(get=lambda *a: row, commit=Mock())
    return row, db

@pytest.mark.parametrize('mode,payload', [
    ('speedtest', {}), ('speedtest', IPERF), ('iperf3', GO), ('iperf3', {}),
    ('speedtest', {'error': 'synthetic failure', **GO}),
    ('speedtest', {'error': '', **GO}),
    ('speedtest', {'servers': [{'dl_speed': -1, 'ul_speed': 5}]}),
    ('speedtest', {'servers': [{'dl_speed': 1, 'ul_speed': 'bad'}]}),
    ('speedtest', {'servers': [{'dl_speed': 1, 'ul_speed': True}]}),
    ('speedtest', {'servers': [{'dl_speed': 1, 'ul_speed': 2, 'latency': 'bad'}]}),
    ('speedtest', {'servers': [{'dl_speed': 1, 'ul_speed': 2, 'jitter': -1}]}),
    ('speedtest', {'servers': [{'dl_speed': 1, 'ul_speed': 2}], 'download': {'bandwidth': -1}}),
    ('speedtest', {'download': {}, 'upload': {}}),
    ('speedtest', {'download': {'bandwidth': 1}, 'upload': {'bandwidth': 2}, 'ping': {'latency': 'bad'}}),
    ('iperf3', {'avg_bitrate': 1}), ('iperf3', dict(IPERF, duration=0)),
    ('iperf3', dict(IPERF, total_bytes='1')), ('iperf3', dict(IPERF, lost_pct=101)),
    ('iperf3', dict(IPERF, send_avg_bitrate=float('inf'))),
    ('iperf3', dict(IPERF, error='synthetic failure')),
    ('iperf3', {'end': {'sum_received': {'bits_per_second': 1}}}),
    ('iperf3', {'role': 'client'}), ('speedtest', {'servers': [{}]}),
    ('iperf3', dict(IPERF, end={'error': 'native failure'})),
    ('iperf3', dict(IPERF, end={'sum_received': {'bits_per_second': -1, 'bytes': 10, 'seconds': 1}})),
])
def test_invalid_done_is_failed_not_success(memory, mode, payload):
    row, db = memory
    row.mode = mode
    svc.finish_iperf(db, 7, 'done', deepcopy(payload))
    assert row.status == 'failed'
    assert row.result_json.get('error')
    assert db.commit.call_count == 1

@pytest.mark.parametrize('mode,payload', [('speedtest', GO), ('speedtest', OOKLA), ('speedtest', CLI),
    ('iperf3', IPERF), ('iperf3', NATIVE), ('iperf3', {'sum_sent': NATIVE['end']['sum_received']}),
    ('iperf3', dict(IPERF, avg_bitrate=0, total_bytes=0, lost_pct=None))])
def test_known_valid_results_still_complete(memory, mode, payload):
    row, db = memory
    row.mode = mode
    svc.finish_iperf(db, 7, 'done', deepcopy(payload))
    assert row.status == 'done'
    assert 'error' not in row.result_json
    if mode == 'speedtest':
        assert row.avg_mbps == 100 and row.peak_mbps == 50

@pytest.mark.parametrize('terminal', ['done', 'failed', 'cancelled'])
def test_late_result_does_not_replace_terminal(memory, terminal):
    row, db = memory
    row.status, row.result_json = terminal, {'original': True}
    svc.finish_iperf(db, 7, 'done', {})
    assert row.status == terminal and row.result_json == {'original': True}
    assert not db.commit.called

@pytest.mark.parametrize('field,value', [('latency', float('nan')), ('jitter', True), ('test_duration', -1)])
def test_optional_go_measurements_are_validated(memory, field, value):
    row, db = memory
    payload = deepcopy(GO); payload['servers'][0][field] = value
    svc.finish_iperf(db, 7, 'done', payload)
    assert row.status == 'failed'


def test_selected_server_must_match_report(memory):
    row, db = memory
    row.speedtest_server = '999'
    svc.finish_iperf(db, 7, 'done', deepcopy(GO))
    assert row.status == 'failed'


@pytest.mark.parametrize('parser', ['_parse_receiver_line', '_parse_sender_line'])
@pytest.mark.parametrize('counts,expected', [('0/0 (0%)', None), ('0/10 (0%)', 0), ('1/10 (10%)', 10), ('1/4 (0%)', 25)])
def test_final_udp_loss_uses_packet_denominator(agent, parser, counts, expected):
    role = 'receiver' if 'receiver' in parser else 'sender'
    result = getattr(agent, parser)(f'[ 5] 0.00-1.00 sec 0 Bytes 0 bits/sec 0.000 ms {counts} {role}')
    assert result.get('lost_pct') == expected


def test_agent_rejects_invalid_go_optional_and_identity(agent, monkeypatch):
    for field, value in [('latency', 'bad'), ('jitter', -1), ('test_duration', True), ('id', '999')]:
        payload = deepcopy(GO); payload['servers'][0][field] = value
        monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: ToolProcess(__import__('json').dumps(payload)))
        result = agent._run_speedtest_once('/fixture/speedtest-go', {'id': 7, 'speedtest_server': '42'}, None)
        assert result.get('error'), (field, result)


@pytest.mark.parametrize('field', ['peak_bitrate', 'send_avg_bitrate', 'jitter_ms'])
def test_forward_cannot_hide_invalid_result_field(memory, field):
    row, db = memory; row.mode = 'iperf3'
    svc.finish_iperf(db, 7, 'done', dict(IPERF, **{field: -1}))
    assert row.status == 'failed'


def test_full_zero_packet_client_result_keeps_unknown(agent):
    result = agent._iperf_client_stream(dict(id=7, parallel=1, udp=True, direction='forward'),
        StreamProcess('[ 5] 0.00-1.00 sec 0 Bytes 0 bits/sec 0.000 ms 0/0 (0%) receiver\n'))
    assert result['lost_pct'] is None
    assert result['avg_bitrate'] == 0 and result['total_bytes'] == 0
    assert svc._validate_iperf_result('iperf3', result)['lost_pct'] is None
