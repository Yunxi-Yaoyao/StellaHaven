"""V12 throughput: real method bodies with bounded fake tools; no live state."""
import ast
import json
import re
import os
import time
import math
import threading
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def agent():
    tree = ast.parse((ROOT / 'agent/stella_agent.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Agent')
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
               (n.name.startswith(('_iperf', '_run_iperf', '_run_speedtest', '_emit_', '_parse_sender', '_parse_receiver', '_norm_units', '_to_bits', '_to_bytes', '_watch_cancel', '_terminate_proc', '_kill_stale_server', '_wait_server_ready', '_is_retryable', '_throughput')))]
    scope = dict(re=re, os=os, time=time, math=math, json=json, threading=threading, subprocess=subprocess, shutil=shutil,
                 datetime=datetime, timezone=timezone, socket=SimpleNamespace(create_connection=Mock()))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Agent', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])), '<actual-throughput-methods>', 'exec'), scope)
    obj = scope['Agent']()
    obj.token = 'fixture-only'
    obj._post = Mock()
    obj._get = Mock(return_value={'status': 'running'})
    obj._agent_bin = lambda: '/fixture/not-installed'
    return obj


def test_stage_note_uses_authorized_client_role(agent):
    agent._emit_stage_note(7, '选择测速服务器…')
    params = agent._post.call_args.kwargs
    assert params['role'] == 'client'  # stage is rejected by authorize_agent_task
    assert params['note'] == '选择测速服务器…'
    assert params['bitrate'] == 0


class ToolProcess:
    def __init__(self, out='', err='', code=0, blocked=False, stubborn=False):
        self.out, self.err, self.code = out, err, code
        self.returncode = None if blocked else code
        self.blocked, self.stubborn = blocked, stubborn
        self.communications = self.terminations = self.kills = self.waits = 0
    def poll(self): return self.returncode
    def communicate(self, timeout=None):
        self.communications += 1
        if self.blocked and self.returncode is None:
            raise subprocess.TimeoutExpired('fake-tool', timeout)
        self.returncode = self.code if self.returncode is None else self.returncode
        return self.out, self.err
    def terminate(self):
        self.terminations += 1
        if not self.stubborn: self.returncode = -15
    def kill(self):
        self.kills += 1
        self.returncode = -9
    def wait(self, timeout=None):
        self.waits += 1
        if self.returncode is None: raise subprocess.TimeoutExpired('fake-tool', timeout)
        return self.returncode


def go_result():
    return {'servers': [{'id': '42', 'dl_speed': 12500000, 'ul_speed': 6250000, 'latency': 12000000, 'jitter': 2000000}]}


def test_speedtest_communicates_before_poll_exit_and_keeps_go_json(agent, monkeypatch):
    proc = ToolProcess(json.dumps(go_result()), blocked=True)
    original = proc.communicate
    def communicate(timeout=None):
        proc.blocked = False
        return original(timeout)
    proc.communicate = communicate
    monkeypatch.setattr(subprocess, 'Popen', Mock(return_value=proc))
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    # Old poll-only loop reaches 90s and kills even though draining pipes finishes.
    result = agent._run_speedtest_once('/fixture/speedtest-go', {'id': 7, 'speedtest_server': '42'}, None)
    assert result == go_result()
    assert proc.communications >= 1
    assert proc.kills == 0
    argv = subprocess.Popen.call_args.args[0]
    assert argv == ['/fixture/speedtest-go', '--json', '-s', '42']


@pytest.mark.parametrize('out', ['not json', '[]', '{}', '{"servers": []}', '{"servers": [{"dl_speed": -1, "ul_speed": 5}]}'])
def test_speedtest_invalid_or_missing_measurements_fail(agent, monkeypatch, out):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: ToolProcess(out))
    assert agent._run_speedtest_once('speedtest-go', {'id': 7}, None).get('error')


def test_speedtest_nonzero_preserves_stderr(agent, monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: ToolProcess('', 'connection refused', code=2))
    assert 'connection refused' in agent._run_speedtest_once('speedtest-go', {'id': 7}, None)['error']


def test_speedtest_cancel_stops_and_reaps_without_retry(agent, monkeypatch):
    proc = ToolProcess(blocked=True, stubborn=True)
    monkeypatch.setattr(subprocess, 'Popen', Mock(return_value=proc))
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    agent._get.return_value = {'status': 'cancelled'}
    result = agent._run_speedtest_once('speedtest-go', {'id': 7}, None)
    assert 'error' in result
    assert proc.terminations == 1 and proc.kills == 1
    assert proc.waits >= 2 and proc.poll() is not None


def test_speedtest_timeout_reaps(agent, monkeypatch):
    proc = ToolProcess(blocked=True)
    monkeypatch.setattr(subprocess, 'Popen', Mock(return_value=proc))
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr(time, 'monotonic', lambda: next(clock))
    result = agent._run_speedtest_once('speedtest-go', {'id': 7}, None)
    assert '超时' in result['error']
    assert proc.waits and proc.poll() is not None


def test_speedtest_uses_only_go_and_no_silent_proxy_fallback(agent, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda x: '/bin/' + x if x == 'speedtest-go' else None)
    agent._run_speedtest_once = Mock(return_value={'error': 'network unreachable'})
    agent._proxy_reachable = Mock(return_value=True)
    assert agent._run_speedtest({'id': 7}) == {'error': 'network unreachable'}
    assert agent._run_speedtest_once.call_count == 1
    assert agent._run_speedtest_once.call_args.args[-1] is None


@pytest.mark.parametrize('status', ['cancelled', 'done', 'failed'])
def test_terminal_watcher_reaps_owned_process(agent, monkeypatch, status):
    proc = ToolProcess(blocked=True)
    agent._get.return_value = {'status': status}
    calls = []
    def bounded_sleep(_):
        calls.append(1)
        assert len(calls) <= 2, 'watcher ignored terminal state'
    monkeypatch.setattr(time, 'sleep', bounded_sleep)
    agent._watch_cancel(7, proc)
    assert proc.poll() is not None and proc.waits


class StreamProcess(ToolProcess):
    def __init__(self, lines, code=0):
        super().__init__(code=code)
        self.stdout = iter(lines.splitlines(True))
        from io import StringIO
        self.stderr = StringIO('fixture stderr' if code else '')


def client_task(**kw):
    return dict(id=7, mode='iperf3', role='client', server_host='fixture.invalid', port=5201,
                duration=10, parallel=2, direction='forward', **kw)


def test_iperf_parallel_sum_not_counted_twice_and_binary_bytes(agent, monkeypatch):
    lines = '''[  5] 0.00-1.00 sec 1.00 MBytes 8.39 Mbits/sec
[  7] 0.00-1.00 sec 1.00 MBytes 8.39 Mbits/sec
[SUM] 0.00-1.00 sec 2.00 MBytes 16.78 Mbits/sec
[SUM] 0.00-1.00 sec 2.00 MBytes 16.78 Mbits/sec 0 sender
[SUM] 0.00-1.00 sec 2.00 MBytes 16.78 Mbits/sec receiver
'''
    proc = StreamProcess(lines)
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    agent._wait_server_ready = lambda *a, **kw: True
    monkeypatch.setattr(subprocess, 'Popen', Mock(return_value=proc))
    result = agent._iperf_client(client_task(bytes='1G', omit=3))
    points = [c.kwargs for c in agent._post.call_args_list if '/progress' in c.args[0]]
    assert [p['bitrate'] for p in points] == [16780000]
    assert result['total_bytes'] == 2097152
    assert result['duration'] == 1
    cmd = subprocess.Popen.call_args.args[0]
    assert cmd[cmd.index('-n') + 1] == '1G'
    assert '-t' not in cmd and '--forceflush' in cmd
    assert proc.waits


def test_server_udp_empty_interval_does_not_abort_reader(agent):
    agent._emit_server_progress(7, '[ 5] 0.00-1.00 sec 0 Bytes 0 bits/sec 0.000 ms 0/0 (0%)')
    assert agent._post.call_count == 1
    assert 'lost_pct' not in agent._post.call_args.kwargs


def test_server_parallel_emits_only_sum(agent):
    # Server knows stream count via task; a single aggregate per interval.
    agent._emit_server_progress(7, '[ 5] 0.00-1.00 sec 1 MBytes 8 Mbits/sec', parallel=2)
    agent._emit_server_progress(7, '[SUM] 0.00-1.00 sec 2 MBytes 16 Mbits/sec', parallel=2)
    assert agent._post.call_count == 1
    assert agent._post.call_args.kwargs['bitrate'] == 16000000


def test_iperf_error_and_missing_summary_fail(agent, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    agent._wait_server_ready = lambda *a, **kw: True
    for lines, code in [('', 1), ('iperf3: error - invalid argument\n', 0), ('', 0)]:
        proc = StreamProcess(lines, code)
        monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
        assert agent._iperf_client(client_task()).get('error')
        assert proc.waits


def test_server_never_kills_other_instances_and_no_fixed_timer(agent, monkeypatch):
    proc = StreamProcess('Server listening on 5201\n')
    monkeypatch.setattr(subprocess, 'Popen', Mock(return_value=proc))
    monkeypatch.setattr(subprocess, 'run', Mock(side_effect=AssertionError('pkill forbidden')))
    monkeypatch.setattr(threading, 'Timer', Mock(side_effect=AssertionError('fixed timer forbidden')))
    # Real background watcher would use real task status calls; keep this fake bounded.
    monkeypatch.setattr(threading, 'Thread', lambda *a, **kw: SimpleNamespace(start=lambda: None))
    agent._iperf_server(dict(id=7, port=5201, duration=10, bytes='1G', parallel=1))
    assert subprocess.run.call_count == 0
    assert threading.Timer.call_count == 0


def test_iperf_retry_does_not_restart_cancelled_task(agent, monkeypatch):
    agent._iperf_client = Mock(return_value={'error': 'Connection reset by peer'})
    agent._get.return_value = {'status': 'cancelled'}
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    agent._run_iperf(client_task())
    assert agent._iperf_client.call_count <= 1
    assert not agent._post.called  # no late failed/done writes to terminal task


@pytest.mark.parametrize('kw', [dict(mode='bogus'), dict(duration=0), dict(parallel=0), dict(port=65536),
    dict(omit=-1), dict(bytes='0'), dict(bytes='nan'), dict(bitrate='--help'), dict(window='1;bad'),
    dict(length='-1'), dict(speedtest_server='1,2'), dict(speedtest_server='--help'),
    dict(mode='speedtest', bytes='10M'), dict(mode='speedtest', direction='reverse'),
    dict(mode='speedtest', server_node_id=2), dict(mode='speedtest', parallel=4)])
def test_task_create_rejects_invalid_or_unmapped_parameters(kw):
    from app.schemas.monitor import IperfTaskCreate
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        IperfTaskCreate(client_node_id=1, **kw)


def test_task_create_accepts_existing_product_contract():
    from app.schemas.monitor import IperfTaskCreate
    for data in (dict(mode='speedtest', speedtest_server='42'),
                 dict(mode='iperf3', server_node_id=2, bytes='1G', udp=True, bitrate='10M', window='256K', length='1400')):
        assert IperfTaskCreate(client_node_id=1, **data).client_node_id == 1


def test_server_start_failure_is_terminal_but_auxiliary_success_is_not(monkeypatch):
    from app.services import task as svc
    row = SimpleNamespace(status='pending', mode='iperf3', server_started=True, result_json=None)
    db = SimpleNamespace(get=lambda *a: row, commit=Mock())
    svc.finish_iperf(db, 7, 'done', {'role': 'server'})
    assert row.status == 'pending' and not db.commit.called
    svc.finish_iperf(db, 7, 'failed', {'role': 'server', 'error': 'address already in use'})
    assert row.status == 'failed' and row.result_json['error'] == 'address already in use'
    svc.finish_iperf(db, 7, 'done', go_result())
    assert row.status == 'failed'


def test_cancel_takes_same_row_lock_as_report_and_preserves_terminals():
    from app.services import task as svc
    row = SimpleNamespace(status='running')
    db = Mock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = row
    svc.cancel_iperf(db, 7)
    assert db.query.return_value.filter.return_value.with_for_update.called
    assert row.status == 'cancelled'
    svc.finish_iperf(db, 7, 'done', go_result())
    assert row.status == 'cancelled'


def test_watchdog_accounts_for_omit_and_data_budget():
    from app.services.task import _iperf_timeout_sec
    assert _iperf_timeout_sec(SimpleNamespace(mode='iperf3', bytes=None, duration=10, omit=60)) == 130
    assert _iperf_timeout_sec(SimpleNamespace(mode='iperf3', bytes='1G', duration=10, omit=0)) == 3660


def test_stage_point_real_authorization_and_invalid_progress(monkeypatch, agent):
    from app.services import task as svc
    from fastapi import HTTPException
    row = SimpleNamespace(status='running', mode='speedtest', client_node_id=1, server_node_id=None)
    db = Mock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = row
    monkeypatch.setattr(svc.node_repo, 'get_by_token', lambda *a: SimpleNamespace(id=1, status='active'))
    agent._emit_stage_note(7, 'fixture stage')
    point = dict(agent._post.call_args.kwargs)
    assert svc.authorize_agent_task(db, 'fixture', 'iperf', 7, role=point['role']) is row
    with pytest.raises(HTTPException) as err:
        svc.authorize_agent_task(db, 'fixture', 'iperf', 7, role='stage')
    assert err.value.status_code == 422
    monkeypatch.setattr(svc.repo, 'append_iperf_progress', Mock())
    for bad in (dict(bitrate=float('nan')), dict(bitrate=-1), dict(lost_pct=101), dict(jitter_ms=float('inf'))):
        with pytest.raises(ValueError):
            svc.append_iperf_progress(db, 7, dict(ts='fixture', role='client', **bad))
    assert not svc.repo.append_iperf_progress.called
    svc.append_iperf_progress(db, 7, dict(ts='fixture', role='client', bitrate=0, note='running'))
    assert svc.repo.append_iperf_progress.called


def test_short_data_result_keeps_actual_fractional_duration_and_valid_high_rate(agent, monkeypatch):
    proc = StreamProcess('[ 5] 0.00-0.25 sec 1.00 GBytes 34.36 Gbits/sec 0 sender\n'
                         '[ 5] 0.00-0.25 sec 1.00 GBytes 34.36 Gbits/sec receiver\n')
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    agent._wait_server_ready = lambda *a, **kw: True
    result = agent._iperf_client(dict(client_task(bytes='1G'), parallel=1))
    assert result['duration'] == 0.25
    assert not result.get('suspicious'), '1Gbps is not a physical limit for arbitrary nodes'
    from app.schemas.public_task import project_iperf_result
    assert project_iperf_result(result, 'iperf3').duration == 0.25


def test_cancel_during_server_wait_never_spawns_client(agent, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    agent._get.return_value = {'status': 'cancelled'}
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=AssertionError('cancelled task spawned')))
    agent._wait_server_ready = Mock(return_value=True)
    assert agent._iperf_client(client_task()).get('error')
    assert not subprocess.Popen.called


def test_client_reader_exception_always_reaps(agent, monkeypatch):
    proc = StreamProcess('')
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    agent._wait_server_ready = lambda *a, **kw: True
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    def broken_reader(*a): raise RuntimeError('fixture reader failure')
    agent._iperf_client_stream = broken_reader
    with pytest.raises(RuntimeError, match='fixture reader failure'):
        agent._iperf_client(client_task())
    assert proc.waits


def test_server_reader_survives_probe_and_reports_real_bind_failure(agent, monkeypatch):
    proc = StreamProcess('iperf3: error - unable to start listener: Address already in use\n', code=1)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    targets = []
    monkeypatch.setattr(threading, 'Thread', lambda *a, **kw: SimpleNamespace(start=lambda: targets.append(kw['target'])))
    agent._iperf_server(dict(id=7, port=5201, duration=10, parallel=1))
    targets[-1]()  # actual reader callback; cancellation watcher isn't launched
    assert proc.waits
    payload = agent._post.call_args.kwargs
    assert payload['status'] == 'failed' and payload['json_body']['role'] == 'server'
    assert 'Address already in use' in payload['json_body']['error']


def test_speedtest_summary_uses_bytes_per_second_and_nanoseconds():
    from app.services.task import repo
    assert repo._iperf_summary(SimpleNamespace(mode='speedtest'), go_result()) == {
        'avg_mbps': 100.0, 'peak_mbps': 50.0, 'lost_pct': None, 'jitter_ms': 2.0}


def test_forward_peak_is_not_fabricated_from_receiver_average(agent, monkeypatch):
    proc = StreamProcess('[ 5] 0.00-2.00 sec 2 MBytes 8 Mbits/sec 0 sender\n'
                         '[ 5] 0.00-2.00 sec 2 MBytes 8 Mbits/sec receiver\n')
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    agent._wait_server_ready = lambda *a, **kw: True
    result = agent._iperf_client(dict(client_task(), parallel=1))
    assert result['avg_bitrate'] == 8000000
    assert result['peak_bitrate'] is None


def test_service_derives_forward_peak_only_from_actual_receiver_intervals(monkeypatch):
    from app.services import task as svc
    row = SimpleNamespace(status='running', mode='iperf3', direction='forward',
        progress_json=[{'role': 'server', 'bitrate': 9e6}, {'role': 'server', 'bitrate': 11e6},
                       {'role': 'client', 'bitrate': 999e6}, {'role': 'client', 'bitrate': 0, 'note': 'stage'}])
    db = SimpleNamespace(get=lambda *a: row)
    captured = Mock()
    monkeypatch.setattr(svc.repo, 'finish_iperf', captured)
    svc.finish_iperf(db, 7, 'done', {'role': 'client', 'peak_bitrate': None})
    assert captured.call_args.args[-1]['peak_bitrate'] == 11e6


def test_server_probe_then_udp_receiver_progress_survives_zero_packets(agent, monkeypatch):
    proc = StreamProcess('Server listening on 5201\n'
        'iperf3: error - unable to receive cookie\nServer listening on 5201\n'
        'Accepted connection from fixture\n'
        '[ 5] 0.00-1.00 sec 0 Bytes 0 bits/sec 0.000 ms 0/0 (0%)\n'
        '[ 5] 1.00-2.00 sec 1 MBytes 8 Mbits/sec 0.123 ms 1/10 (10%)\n')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    targets = []
    monkeypatch.setattr(threading, 'Thread', lambda *a, **kw: SimpleNamespace(start=lambda: targets.append(kw['target'])))
    agent._get.side_effect = [{'status': 'running'}, {'status': 'running'}, {'status': 'done'}]
    agent._iperf_server(dict(id=7, duration=10, parallel=1))
    targets[-1]()
    points = [c.kwargs for c in agent._post.call_args_list]
    assert len(points) == 2
    assert points[-1]['lost_pct'] == 10 and points[-1]['jitter_ms'] == 0.123
    assert all(p['role'] == 'server' for p in points)
    assert proc.waits


def test_reverse_udp_flags_and_receiver_metrics(agent, monkeypatch):
    proc = StreamProcess('[ 5] 0.00-1.00 sec 1 MBytes 8 Mbits/sec 0.123 ms 1/10 (10%)\n'
        '[ 5] 0.00-1.00 sec 1 MBytes 8 Mbits/sec 0.123 ms 1/10 (10%) receiver\n')
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    popen = Mock(return_value=proc)
    monkeypatch.setattr(subprocess, 'Popen', popen)
    agent._wait_server_ready = lambda *a, **kw: True
    task = dict(client_task(), direction='reverse', udp=True, parallel=1, omit=2, bitrate=None)
    result = agent._iperf_client(task)
    argv = popen.call_args.args[0]
    assert '-R' in argv and '-u' in argv and argv[argv.index('-b')+1] == '100M'
    assert argv[argv.index('-O')+1] == '2' and '-n' not in argv
    assert result['lost_pct'] == 10 and result['jitter_ms'] == 0.123
    assert agent._post.call_args.kwargs['lost_pct'] == 10


def test_reverse_subsecond_result_uses_receiver_summary_not_zero_average(agent, monkeypatch):
    proc = StreamProcess('[ 5] 0.00-0.25 sec 1 MBytes 32 Mbits/sec receiver\n')
    monkeypatch.setattr(shutil, 'which', lambda _: '/fixture/iperf3')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: proc)
    agent._wait_server_ready = lambda *a, **kw: True
    result = agent._iperf_client(dict(client_task(bytes='1M'), direction='reverse', parallel=1))
    assert result['avg_bitrate'] == 32000000
    assert result['peak_bitrate'] is None
