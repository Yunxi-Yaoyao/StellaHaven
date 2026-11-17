"""Ordinary ping artifact regressions; only process/HTTP/MTR IO is mocked."""
import importlib.util
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('STELLA_PING_AGENT_SOURCE', ROOT / 'agent/stella_agent.py'))
spec = importlib.util.spec_from_file_location('ping_artifact_agent', SOURCE)
assert spec and spec.loader
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def scheduler(monkeypatch):
    obj = agent.Agent.__new__(agent.Agent)
    obj.token = 'synthetic-ping-test-token'
    obj.monitors = {7: dict(type='ping', target='192.0.2.1', timeout=1,
        interval=60, next_run=0, next_mtr=2000, last_fail_mtr=0)}
    obj.run_entry_probes = Mock()
    obj._post = Mock(return_value={})
    obj._run_mtr_for_monitor = Mock()
    monkeypatch.setattr(agent.time, 'time', lambda: 1000)
    monkeypatch.setattr(agent.platform, 'system', lambda: 'Linux')
    return obj


def test_no_statistics_does_not_post_or_trigger_failure_mtr(monkeypatch):
    obj = scheduler(monkeypatch)
    run = Mock(return_value=subprocess.CompletedProcess([], 2, '', 'ping: permission denied'))
    monkeypatch.setattr(agent.subprocess, 'run', run)
    obj.run_due_probes()
    obj._post.assert_not_called()
    obj._run_mtr_for_monitor.assert_not_called()
    assert obj.monitors[7]['next_run'] == 1060
    assert obj.monitors[7]['next_mtr'] == 2000
    assert obj.monitors[7]['last_fail_mtr'] == 0
    obj.run_entry_probes.assert_called_once_with()
    run.assert_called_once()


def linux_output(loss: int | str = 0, received=10, latency='2.0'):
    return (f'10 packets transmitted, {received} received, {loss}% packet loss, time 9000ms\n'
            f'rtt min/avg/max/mdev = 1.0/{latency}/3.0/0.1 ms\n')


@pytest.mark.parametrize('platform_name,stdout,code,expected', [
    ('Linux', linux_output(), 0, (True, 2.0, 0.0)),
    ('Linux', linux_output(30, 7), 0, (True, 2.0, 30.0)),
    ('Linux', linux_output(100, 0), 1, (False, 2.0, 100.0)),
    ('Linux', '10 packets transmitted, 0 received, 100% packet loss\n', 1, (False, None, 100.0)),
    ('Windows', 'Packets: Sent = 10, Received = 7, Lost = 3 (30% loss),\n'
     'Minimum = 1ms, Maximum = 3ms, Average = 2ms\n', 0, (True, 2.0, 30.0)),
    ('Windows', '数据包: 已发送 = 10，已接收 = 10，丢失 = 0 (0% 丢失)，\n'
     '最短 = 1ms，最长 = 3ms，平均 = 2ms\n', 0, (True, 2.0, 0.0)),
    ('Windows', 'Packets: Sent = 10, Received = 0, Lost = 10 (100% loss),\n', 1, (False, None, 100.0)),
])
def test_verified_packet_statistics(monkeypatch, platform_name, stdout, code, expected):
    obj = scheduler(monkeypatch)
    monkeypatch.setattr(agent.platform, 'system', lambda: platform_name)
    run = Mock(return_value=subprocess.CompletedProcess([], code, stdout, ''))
    monkeypatch.setattr(agent.subprocess, 'run', run)
    assert obj.probe('ping', '192.0.2.1', 2) == expected
    argv = run.call_args.args[0]
    if platform_name == 'Windows':
        assert argv == ['ping', '-n', '10', '-w', '2000', '192.0.2.1']
    else:
        assert argv == ['ping', '-c', '10', '-W', '2', '192.0.2.1']
        assert run.call_args.kwargs['env']['LC_ALL'] == 'C'


@pytest.mark.parametrize('stdout,code', [
    ('', 0), ('', 1), ('', 2), ('unknown host', 2),
    ('reply: time=2ms', 0), ('unsupported localized summary', 0),
    (linux_output(0, 10), 2), (linux_output(0, 10), 1),
    (linux_output(100, 0), 0), (linux_output(30, 7), 1),
    (linux_output('-1', 10), 0), (linux_output('101', 0), 1),
    (linux_output('NaN', 10), 0), (linux_output('inf', 10), 0),
    (linux_output(0, 10, 'nan'), 0), (linux_output(0, 10, 'inf'), 0),
    (linux_output(0, 10, '-2'), 0), (linux_output(50, 7), 0),
    ('0 packets transmitted, 0 received, 100% packet loss\n', 1),
    (linux_output(0, 11), 0), (linux_output() + linux_output(100, 0), 0),
    (linux_output('99.9', 0), 0), (linux_output('.1', 10), 0),
    ('0% packet loss\nrtt min/avg/max/mdev = 1/2/3/0 ms', 0),
])
def test_unverified_or_contradictory_statistics_are_unknown(monkeypatch, stdout, code):
    obj = scheduler(monkeypatch)
    monkeypatch.setattr(agent.subprocess, 'run', Mock(return_value=
        subprocess.CompletedProcess([], code, stdout, '')))
    assert obj.probe('ping', '192.0.2.1', 1) == (None, None, None)


@pytest.mark.parametrize('error', [FileNotFoundError('no ping'), PermissionError('denied'),
    OSError('local tool error'), subprocess.TimeoutExpired('ping', 1), ValueError('bad output')])
def test_ping_source_exceptions_are_unknown_not_remote_failure(monkeypatch, error):
    obj = scheduler(monkeypatch)
    monkeypatch.setattr(agent.subprocess, 'run', Mock(side_effect=error))
    assert obj.probe('ping', '192.0.2.1', 1) == (None, None, None)
    obj.run_due_probes()
    obj._post.assert_not_called()
    obj._run_mtr_for_monitor.assert_not_called()


@pytest.mark.parametrize('stdout,code', [
    ('Packets: Sent = 10, Received = 10, Lost = 0 (0% loss),\nDestination host unreachable.', 0),
    ('Packets: Sent = 10, Received = 7, Lost = 3 (0% loss),\nAverage = 2ms', 0),
    ('Pakete: Gesendet = 10, Empfangen = 10, Verloren = 0 (0% Verlust)', 0),
    ('Packets: Sent = 10, Received = 0, Lost = 10 (100% loss),', 0),
])
def test_windows_unsupported_or_non_echo_statistics_are_unknown(monkeypatch, stdout, code):
    obj = scheduler(monkeypatch)
    monkeypatch.setattr(agent.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(agent.subprocess, 'run', Mock(return_value=
        subprocess.CompletedProcess([], code, stdout, '')))
    assert obj.probe('ping', '192.0.2.1', 1) == (None, None, None)
    obj.run_due_probes()
    obj._post.assert_not_called()
    obj._run_mtr_for_monitor.assert_not_called()


@pytest.mark.parametrize('loss,received,code,success', [(0, 10, 0, True), (30, 7, 0, True), (100, 0, 1, False)])
def test_scheduler_posts_exactly_one_boolean_check_for_measured_loss(monkeypatch, loss, received, code, success):
    obj = scheduler(monkeypatch)
    monkeypatch.setattr(agent.subprocess, 'run', Mock(return_value=
        subprocess.CompletedProcess([], code, linux_output(loss, received), '')))
    obj.run_due_probes()
    obj._post.assert_called_once()
    args, kwargs = obj._post.call_args
    assert args == ('/agent/monitor-check',)
    payload = kwargs['json_body']
    assert payload['monitor_id'] == 7 and payload['success'] is success
    assert type(payload['success']) is bool
    assert payload['loss_pct'] == loss and payload['latency_ms'] == 2.0
    assert kwargs['token'] == obj.token and payload['ts']
    if success:
        obj._run_mtr_for_monitor.assert_not_called()
    else:
        obj._run_mtr_for_monitor.assert_called_once_with(7, obj.monitors[7], 'failure')
        assert obj.monitors[7]['last_fail_mtr'] == 1000
        assert obj.monitors[7]['next_mtr'] == 1000 + agent.MTR_INTERVAL
    obj.run_due_probes()  # not due: no duplicate check
    obj._post.assert_called_once()


def test_unknown_keeps_periodic_mtr_and_next_valid_sample_recovers(monkeypatch):
    obj = scheduler(monkeypatch)
    obj.monitors[7]['next_mtr'] = 0
    run = Mock(side_effect=[subprocess.CompletedProcess([], 2, '', 'local error'),
        subprocess.CompletedProcess([], 0, linux_output(), '')])
    monkeypatch.setattr(agent.subprocess, 'run', run)
    obj.run_due_probes()
    obj._post.assert_not_called()
    obj._run_mtr_for_monitor.assert_called_once_with(7, obj.monitors[7], 'periodic')
    assert obj.monitors[7]['next_mtr'] == 1000 + agent.MTR_INTERVAL
    assert obj.monitors[7]['last_fail_mtr'] == 0
    obj.run_due_probes()
    assert run.call_count == 1
    monkeypatch.setattr(agent.time, 'time', lambda: 1060)
    obj.run_due_probes()
    assert run.call_count == 2
    obj._post.assert_called_once()
    assert obj._post.call_args.kwargs['json_body']['success'] is True
    assert obj._post.call_args.kwargs['json_body']['loss_pct'] == 0.0
    assert obj.monitors[7]['next_run'] == 1120
    assert obj._run_mtr_for_monitor.call_count == 1


def test_unknown_first_monitor_does_not_starve_next_monitor(monkeypatch):
    obj = scheduler(monkeypatch)
    obj.monitors[8] = dict(obj.monitors[7])
    run = Mock(side_effect=[subprocess.CompletedProcess([], 0, '', ''),
        subprocess.CompletedProcess([], 0, linux_output(30, 7), '')])
    monkeypatch.setattr(agent.subprocess, 'run', run)
    obj.run_due_probes()
    assert run.call_count == 2
    obj._post.assert_called_once()
    assert obj._post.call_args.kwargs['json_body']['monitor_id'] == 8
    obj._run_mtr_for_monitor.assert_not_called()


@pytest.mark.parametrize('mtype,method', [('tcp', '_probe_tcp'), ('http', '_probe_http'),
    ('https', '_probe_http'), ('udp', '_probe_udp')])
def test_non_ping_probe_exception_contract_is_unchanged(monkeypatch, mtype, method):
    obj = scheduler(monkeypatch)
    monkeypatch.setattr(obj, method, Mock(side_effect=OSError('existing non-ping behavior')))
    assert obj.probe(mtype, 'fixture.invalid', 1) == (False, None, None)
    obj.monitors[7]['type'] = mtype
    obj.run_due_probes()
    obj._post.assert_called_once()
    assert obj._post.call_args.kwargs['json_body']['success'] is False
    obj._run_mtr_for_monitor.assert_called_once_with(7, obj.monitors[7], 'failure')
