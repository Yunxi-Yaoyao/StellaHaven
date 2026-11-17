"""Offline response-model serialization; no app config, agent execution or DB."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.schemas.monitor import NodeDetail

STAMP = '2026-10-10T00:00:00+00:00'

def node(**extra):
    return dict(id=1, name='fixture', platform='linux', host='offline.invalid',
                status='online', created_at=datetime(2026, 10, 10, tzinfo=timezone.utc), **extra)

def http(model, data):
    app = FastAPI()
    @app.get('/fixture', response_model=model)
    def response():
        return data
    with TestClient(app) as client:
        response = client.get('/fixture')
    assert response.status_code == 200
    return response.json()

def test_node_projects_malformed_hardware_and_excludes_credentials_in_real_http():
    data = node(token='NODE_SECRET', interfaces={'eth0': {'up': 'yes', 'ip': '192.0.2.1', 'token': 'IF_SECRET'}},
        components={'iperf3': True, 'docker': {'installed': 'yes', 'version': '27', 'password': 'COMP_SECRET'}},
        storage=[{'device': 'sda', 'total': True, 'used': 0, 'percent': float('inf'), 'token': 'DISK_SECRET'}],
        monitored_ifaces={'eth0': {'display': 'custom', 'options': [1, True, None]}},
        sys_info={'cpu_cores': True, 'load1': float('nan'), 'token': 'SYS_SECRET', 'hardware': {
            'sampled_at': STAMP, 'cpu': {'temperature_c': float('inf'), 'logical_cores': True},
            'sensors': [{'name': 'future sensor', 'kind': 'voltage', 'value': 1.25, 'unit': 'V', 'source': 'legacy'}],
            'future_device': {'reading': 5, 'token': 'EXT_SECRET'}, 'command': 'CMD_SECRET'}})
    before = deepcopy(data)
    out = http(NodeDetail, data)
    assert 'SECRET' not in json.dumps(out)
    assert out['interfaces']['eth0'] == {'up': None, 'ip': '192.0.2.1'}
    assert out['storage'][0]['used'] == 0
    assert out['storage'][0]['total'] is None
    assert out['storage'][0]['percent'] is None
    assert out['sys_info']['load1'] is None
    assert out['sys_info']['cpu_cores'] is None
    assert out['sys_info']['hardware']['cpu']['logical_cores'] is None
    assert out['sys_info']['hardware']['sensors'][0]['kind'] == 'voltage'
    assert out['sys_info']['hardware']['legacy_extensions']['future_device'] == {'reading': 5}
    assert out['monitored_ifaces'] == before['monitored_ifaces']
    assert data['token'] == before['token']
    assert data['storage'][0]['total'] is True


def test_inventory_scope_does_not_claim_container_host_dmi_as_physical():
    hardware = {'machine': {'kind': 'container'}, 'physical_inventory': {'board': {'model': 'host'},
        'memory_modules': [{'capacity_bytes': 99}]},
        'platform_inventory': {'source': 'sysfs.dmi', 'scope': 'host_visible', 'state': 'available',
            'sampled_at': STAMP, 'board': {'model': 'host'}, 'memory_modules': [{'capacity_bytes': 99}]},
        'memory': {'total_bytes': 123, 'available_bytes': 0, 'used_bytes': None, 'scope': 'host_visible',
            'state': 'query_failed', 'sampled_at': STAMP, 'attempted_at': '2026-10-10T01:00:00Z',
            'cgroup': {'total_bytes': 100, 'used_bytes': 5, 'scope': 'cgroup', 'state': 'available', 'source': 'cgroup.v2'}},
        'cpu': {'temperature_c': 0, 'future_sensor': {'sample': 4, 'password': 'SECRET'}},
        'sensors': [{'name': 'extra', 'value': 0, 'vendor_mode': 'uncalibrated'}]}
    out = http(NodeDetail, node(sys_info={'hardware': hardware}))['sys_info']['hardware']
    assert out['physical_inventory'] is None
    assert out['platform_inventory']['board']['model'] == 'host'
    assert out['platform_inventory']['memory_modules'] is None
    assert out['memory'] == hardware['memory']
    assert out['cpu']['legacy_extensions']['future_sensor'] == {'sample': 4}
    assert out['sensors'][0]['legacy_extensions'] == {'vendor_mode': 'uncalibrated'}
    assert hardware['physical_inventory'] is not None


import pytest
from app.schemas.monitor import NetTaskRead, MtrTaskRead, IperfTaskRead

NET_CASES = {
    'ip_change': ({'iface': 'eth0', 'new_ip': '192.0.2.3', 'prefix': 24, 'gateway': None, 'ping_target': '192.0.2.1'},
                  {'ok': True, 'old_ip': '192.0.2.2', 'new_ip': '192.0.2.3', 'persisted': False, 'backend': 'netplan'}),
    'firewall_scan': (None, {'ufw': {'installed': False}, 'iptables': {'installed': True, 'raw': '',
        'tables': {'filter': {'chains': [{'name': 'INPUT', 'policy': 'ACCEPT', 'packets': 0, 'bytes': 0}], 'rules': []}}}}),
    'docker_scan': (None, {'installed': True, 'containers': [{'id': 'abc', 'name': 'web', 'image': 'nginx',
        'status': 'Up', 'state': 'running', 'ports': '', 'created': 'today'}]}),
    'docker_ctl': ({'action': 'start', 'container': 'web'}, {'ok': True, 'action': 'start', 'container': 'web'}),
    'docker_logs': ({'container': 'web', 'tail': 150}, {'container': 'web', 'tail': 150, 'lines': 'literal tool log'}),
    'docker_inspect': ({'container': 'web'}, {'container': 'web', 'image': 'nginx', 'created': STAMP,
        'cmd': 'nginx', 'entrypoint': None, 'env': ['API_TOKEN=tool-owned-value'], 'mounts': [
            {'source': '/data', 'target': '/data', 'mode': 'rw', 'rw': True}],
        'ports': [{'container': '80/tcp', 'host': '8080'}], 'restart_policy': 'always', 'networks': ['bridge'], 'state': 'running'}),
    'pbr_scan': (None, {'rules': [{'pref': 1, 'mark': None, 'table': 'main', 'raw': '1: from all lookup main', 'from': 'all'}],
        'tables': {'main': [{'dst': 'default', 'via': '192.0.2.1', 'dev': 'eth0', 'scope': None, 'raw': 'default via 192.0.2.1'}]},
        'marks': [{'chain': 'OUTPUT', 'uid': '1000', 'mark': '1', 'raw': 'rule'}]}),
}

@pytest.mark.parametrize('kind', NET_CASES)
def test_net_kind_specific_projection_preserves_current_fields_and_payload(kind):
    payload, result = deepcopy(NET_CASES[kind])
    original = deepcopy(result)
    result['token'] = 'RESULT_SECRET'
    data = dict(id=1, node_id=2, kind=kind, status='done', created_at=STAMP,
                payload=payload, result_json=result, token='ORM_SECRET')
    out = http(NetTaskRead, data)
    assert out['result_json'] == original
    assert out['payload'] == payload
    assert 'SECRET' not in json.dumps(out)
    schema = NetTaskRead.model_json_schema(mode='serialization')
    assert schema['discriminator']['propertyName'] == 'kind'


def test_net_malformed_measurements_and_mtr_hops_are_unknown_not_zero():
    out = http(NetTaskRead, dict(id=1, node_id=2, kind='docker_logs', status='done',
        created_at=STAMP, result_json={'tail': True, 'lines': ['bad'], 'container': 'web'}))
    assert out['result_json'] == {'tail': None, 'lines': None, 'container': 'web'}


def test_mtr_hops_are_typed_unknown_not_zero():
    hop = {'count': 1, 'host': '???', 'snt': True, 'loss%': float('nan'), 'last': None, 'avg': 0, 'token': 'SECRET'}
    mtr = http(MtrTaskRead, dict(id=1, node_id=2, target='192.0.2.1', protocol='icmp', status='done', created_at=STAMP,
        result_json={'report': {'mtr': {'dst': '192.0.2.1', 'tests': 10}, 'hubs': [hop]}}, live_json={'hops': [hop]},
        params_json={'count': 10, 'future_option': {'keep': True}}))
    for row in (mtr['result_json']['report']['hubs'][0], mtr['live_json']['hops'][0]):
        assert row['snt'] is None and row['loss%'] is None and row['last'] is None
        assert row['avg'] == 0 and 'token' not in row
    assert mtr['params_json']['future_option'] == {'keep': True}


def iperf(mode='iperf3', **fields):
    return dict(id=1, client_node_id=2, mode=mode, direction='forward', duration=10, parallel=1,
                status='done', created_at=STAMP, **fields)


@pytest.mark.parametrize('mode,result,origin', [
    ('iperf3', {'avg_bitrate': True, 'peak_bitrate': float('inf'), 'total_bytes': 0, 'role': 'client', 'suspicious': True}, 'stella_iperf_summary'),
    ('iperf3', {'start': {'version': '3.1'}, 'end': {'sum_received': {'bits_per_second': 123}}, 'future': {'flag': True}}, 'iperf_tool_json'),
    ('speedtest', {'servers': [{'dl_speed': 100, 'ul_speed': 50, 'latency': 1000000, 'jitter': 200000, 'name': 'test', 'country': 'CN', 'vendor_extra': [1]}], 'via_proxy': True}, 'speedtest_tool_json'),
    ('speedtest', {'download': {'bandwidth': 123, 'bytes': 10}, 'upload': {'bandwidth': 0}, 'ping': {'latency': 4, 'jitter': 0}, 'server': {'name': 'test'}}, 'speedtest_tool_json'),
    ('speedtest', {'download': 123456.0, 'upload': 54321.0, 'ping': 12.0, 'future': [None, 'raw']}, 'speedtest_tool_json'),
])
def test_iperf_typed_result_has_honest_raw_origin_without_breaking_legacy_ui(mode, result, origin):
    out = http(IperfTaskRead, iperf(mode, result_json=result))['result_json']
    assert out['raw_origin'] == origin
    assert out['raw_payload']['role' if 'role' in result else next(iter(result))] is not None
    if 'avg_bitrate' in result:
        assert out['avg_bitrate'] is None and out['peak_bitrate'] is None
        assert out['total_bytes'] == 0 and out['suspicious'] is True
        assert out['raw_payload']['avg_bitrate'] is True  # raw is not a normalized measurement
    else:
        for key in ('end', 'servers', 'download', 'upload', 'ping', 'server', 'via_proxy'):
            if key in result:
                assert out[key] == result[key]
    assert 'raw_origin' not in result


def test_progress_retry_stage_null_and_invalid_numbers_preserve_indices():
    points = [{'ts': STAMP, 'bitrate': 0, 'role': 'stage', 'note': 'selecting'},
              {'ts': STAMP, 'bitrate': 0, 'role': 'client', 'retry': True, 'attempt': 2, 'reason': 'connection reset'},
              {'ts': STAMP, 'bitrate': True, 'lost_pct': float('nan'), 'role': 'server'}, None,
              {'ts': STAMP, 'bitrate': 42, 'role': 'client'}]
    out = http(IperfTaskRead, iperf(result_json=None, progress_json=points, avg_mbps=True, jitter_ms=float('inf')))
    assert out['result_json'] is None
    assert out['avg_mbps'] is None and out['jitter_ms'] is None
    assert out['progress_json'][:2] == points[:2]
    assert out['progress_json'][2]['bitrate'] is None
    assert out['progress_json'][2]['lost_pct'] is None
    assert out['progress_json'][3] == {'ts': None, 'bitrate': None, 'role': None}
    assert out['progress_json'][4] == points[4]


def test_legacy_mtr_uppercase_fields_and_top_level_hubs_survive():
    hop = {'count': 1, 'host': '192.0.2.1', 'Loss%': 0, 'Snt': 10, 'Avg': 2, 'Last': None, 'Best': 1, 'Wrst': 3, 'StDev': 0.1}
    data = dict(id=1, node_id=2, target='192.0.2.1', protocol='icmp', status='done', created_at=STAMP, result_json={'hubs': [hop]})
    out = http(MtrTaskRead, data)
    assert out['result_json']['hubs'] == [hop]


def source_function(relative, name, namespace):
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / relative
    tree = ast.parse(path.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def test_iperf_read_routes_do_not_mutate_persisted_progress():
    from types import SimpleNamespace
    from fastapi import Depends, HTTPException
    original = [{'ts': STAMP, 'bitrate': 1, 'role': 'client'}, {'ts': STAMP, 'bitrate': 2, 'role': 'client'}]
    row = SimpleNamespace(**iperf(progress_json=deepcopy(original)))
    ns = dict(User=object, Session=object, Depends=Depends, current_user=lambda: None, get_db=lambda: None,
              HTTPException=HTTPException, IperfTaskRead=IperfTaskRead,
              task_svc=SimpleNamespace(list_iperf=lambda db: [row], get_iperf=lambda db, task_id: row))
    get = source_function('app/routers/task.py', 'get_iperf', ns)
    listed = source_function('app/routers/task.py', 'list_iperf', ns)
    assert http(IperfTaskRead, get(1, progress_after=1, user=None, db=None))['progress_json'] == original[1:]
    assert row.progress_json == original
    assert http(list[IperfTaskRead], listed(user=None, db=None))[0]['progress_json'] is None
    assert row.progress_json == original


def test_real_poll_keeps_agent_instructions_and_extensions_byte_semantics():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from app.schemas import public_task
    model = getattr(public_task, 'AgentTasksRead', None)
    assert model is not None, 'Agent polling needs a typed envelope, NOT a public-result filter'
    client = SimpleNamespace(**iperf(), server_node_id=3, bytes='5M', udp=True, bitrate='2M', port=5202,
        window='1M', length='1200', omit=2, zerocopy=True, speedtest_server='123', started_at=None)
    nets = [SimpleNamespace(id=i, kind=kind, payload=deepcopy(payload), status='pending')
            for i, (kind, (payload, _)) in enumerate(NET_CASES.items(), 1)]
    # Instruction payloads are deliberately not run through public telemetry redaction.
    nets.append(SimpleNamespace(id=99, kind='future_tool', status='pending', payload={'command': 'tool --token INSTRUCTION_ONLY', 'nested': [True, None, {'flag': 2}]}))
    commands = [SimpleNamespace(id=1, command='printf INSTRUCTION_ONLY', status='pending')]
    mtrs = [SimpleNamespace(id=2, target='192.0.2.1', protocol='udp', params_json={'count': 5, 'future_option': ['keep']}, status='pending')]
    node_obj = SimpleNamespace(id=2, status='online', uninstall_status=None)
    repo = SimpleNamespace(pending_iperf_server=lambda *a: [], pending_iperf_client=lambda *a: [client],
        pending_mtr_for_node=lambda *a: mtrs, pending_commands_for_node=lambda *a: commands,
        pending_components_for_node=lambda *a: [], pending_net_tasks=lambda *a: nets)
    ns = dict(Session=object, datetime=datetime, timezone=timezone, repo=repo,
        node_repo=SimpleNamespace(get_by_token=lambda *a: node_obj, get_by_id=lambda *a: SimpleNamespace(host='192.0.2.2')))
    poll = source_function('app/services/task.py', 'poll_tasks', ns)
    result = poll(SimpleNamespace(commit=lambda: None), 'synthetic')
    assert http(model, result) == result
    path = Path(__file__).resolve().parents[1] / 'app/routers/task.py'
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'poll_tasks')
    assert any(k.arg == 'response_model' and ast.unparse(k.value) == 'AgentTasksRead'
               for dec in fn.decorator_list for k in dec.keywords)


def test_bad_inventory_row_does_not_erase_other_real_sensor_or_storage_rows():
    out = http(NodeDetail, node(storage=[{'device': 'a', 'used': 0}, 'bad', {'device': 'b', 'used': None}],
        interfaces={'good': {'up': True}, 'bad': False},
        sys_info={'hardware': {'sensors': [{'name': 'valid', 'kind': 'voltage', 'value': 1.2}, False,
            {'name': 'second', 'value': 0}], 'platform_inventory': {'board': {'model': 'unscoped'}}}}))
    assert out['storage'] == [{'device': 'a', 'used': 0}, {}, {'device': 'b', 'used': None}]
    assert out['interfaces'] == {'good': {'up': True}, 'bad': {}}
    sensors = out['sys_info']['hardware']['sensors']
    assert sensors[0]['value'] == 1.2 and sensors[1] == {} and sensors[2]['value'] == 0
def test_unscoped_platform_inventory_does_not_promote_unknown_board():
    out = http(NodeDetail, node(sys_info={'hardware': {'platform_inventory': {'board': {'model': 'unscoped'}}}}))
    assert out['sys_info']['hardware']['platform_inventory'] is None


@pytest.mark.parametrize('kind', ['physical', 'virtual', 'container', 'unknown', None])
def test_inventory_scope_old_agent_and_missing_measurements_stay_explicit(kind):
    hw = {'memory': {'total_bytes': 123, 'scope': 'os_visible', 'state': 'available', 'source': 'psutil', 'sampled_at': STAMP},
          'physical_inventory': {'board': {'model': 'fixture'}, 'disks': None}, 'cpu': {'temperature_c': None}}
    if kind is not None:
        hw['machine'] = {'kind': kind}
    out = http(NodeDetail, node(sys_info={'hardware': hw}))['sys_info']['hardware']
    assert out['memory'] == hw['memory']
    assert 'used_bytes' not in out['memory']
    assert out['cpu'] == {'temperature_c': None}
    assert out['physical_inventory'] == (hw['physical_inventory'] if kind == 'physical' else None)
    assert ('machine' in out) == (kind is not None)


@pytest.mark.parametrize('kind', NET_CASES)
@pytest.mark.parametrize('result', [None, {'error': 'tool absent'}, {}])
def test_net_null_error_empty_results_remain_distinct(kind, result):
    out = http(NetTaskRead, dict(id=1, node_id=2, kind=kind, status='failed', created_at=STAMP, result_json=result))
    assert out['result_json'] == result


def test_unsupported_net_task_has_explicit_origin_without_public_instruction_leak():
    out = http(NetTaskRead, dict(id=1, node_id=2, kind='future', status='done', created_at=STAMP,
        payload={'command': 'SECRET'}, result_json={'future': [1, True, None], 'token': 'SECRET'}))
    assert out['kind'] == 'unknown' and out['reported_kind'] == 'future'
    assert out['payload'] is None
    assert out['result_json'] == {'raw_origin': 'legacy_unknown_net_task', 'raw_payload': {'future': [1, True, None]}}


@pytest.mark.parametrize('fixture_name', ['node-55.captured.json', 'node-57.captured.json',
                                        'node-55.contract-fixture.json', 'node-57.contract-fixture.json'])
def test_existing_frontend_hardware_fixture_fields_survive(fixture_name):
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'frontend/src/modules/servers/fixtures' / fixture_name
    data = json.loads(path.read_text())
    out = http(NodeDetail, data)
    for key in ('interfaces', 'components', 'storage', 'sys_info', 'monitored_ifaces'):
        assert out[key] == data[key], (fixture_name, key)


def test_all_public_models_generate_valid_schemas_and_outputs_validate():
    from jsonschema import Draft202012Validator
    from app.schemas.monitor import NodeRead
    from app.schemas.public_task import AgentTasksRead
    for model in (NodeRead, NodeDetail, NetTaskRead, MtrTaskRead, IperfTaskRead, AgentTasksRead):
        schema = model.model_json_schema(mode='serialization')
        Draft202012Validator.check_schema(schema)
    for kind, (payload, result) in NET_CASES.items():
        out = http(NetTaskRead, dict(id=1, node_id=2, kind=kind, status='done', created_at=STAMP, payload=payload, result_json=result))
        Draft202012Validator(NetTaskRead.model_json_schema(mode='serialization')).validate(out)
    out = http(IperfTaskRead, iperf('speedtest', result_json={'download': {'bandwidth': 1}}))
    Draft202012Validator(IperfTaskRead.model_json_schema(mode='serialization')).validate(out)
    assert 'token' not in NodeRead.model_json_schema(mode='serialization')['properties']


@pytest.mark.parametrize('mode', ['iperf3', 'speedtest'])
def test_task_error_origin_does_not_falsely_claim_external_tool_success(mode):
    out = http(IperfTaskRead, iperf(mode, result_json={'error': 'watchdog timeout'}))['result_json']
    assert out['raw_origin'] == 'task_error'
    assert out['error'] == 'watchdog timeout'
    assert out['raw_payload'] == {'error': 'watchdog timeout'}


def test_literal_unknown_legacy_kind_retains_raw_result_and_does_not_500():
    out = http(NetTaskRead, dict(id=1, node_id=2, kind='unknown', status='done', created_at=STAMP,
                                result_json={'legacy': 'value'}))
    assert out['result_json']['raw_payload'] == {'legacy': 'value'}


@pytest.mark.parametrize('key', ['access_token', 'refreshToken', 'client_secret', 'ssh_private_key', 'installCommand', 'api-key', 'Authorization'])
def test_legacy_hardware_extension_cannot_bypass_private_key_filter(key):
    out = http(NodeDetail, node(sys_info={'hardware': {'vendor_extension': {key: 'PRIVATE_MARKER', 'reading': 4}}}))
    assert 'PRIVATE_MARKER' not in json.dumps(out)
    assert out['sys_info']['hardware']['legacy_extensions']['vendor_extension']['reading'] == 4
