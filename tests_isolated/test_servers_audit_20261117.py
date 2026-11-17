"""Candidate regressions: no production DB, nodes or component installs."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import importlib.util
from pathlib import Path
import threading
import pytest
from app.services import task

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('capability', [False, {'installed': False}])
@pytest.mark.parametrize('entry', ['monitor', 'single', 'multi'])
def test_missing_mtr_rejected_before_any_task_write(monkeypatch, capability, entry):
    node = SimpleNamespace(id=1, status='online', last_seen_at=datetime.now(timezone.utc), components={'mtr': capability})
    monkeypatch.setattr(task.node_repo, 'get_by_id', lambda *args: node)
    create = Mock(); job = Mock()
    monkeypatch.setattr(task.repo, 'create_mtr', create)
    monkeypatch.setattr(task.repo, 'create_mtr_job', job)
    with pytest.raises(ValueError, match='未安装 MTR'):
        if entry == 'monitor':
            task.create_mtr_for_monitor(Mock(), SimpleNamespace(node_id=1, id=2, type='ping', target='example.test'))
        elif entry == 'single': task.create_mtr(Mock(), 1, 'example.test', 'icmp')
        else: task.create_mtr_job(Mock(), [1, 2], 'example.test', 'icmp')
    create.assert_not_called(); job.assert_not_called()

@pytest.mark.parametrize('capability', [True, {'installed': True}, None])
def test_unknown_legacy_capability_still_admits_online_node(monkeypatch, capability):
    node = SimpleNamespace(id=1, status='online', last_seen_at=datetime.now(timezone.utc), components={'mtr': capability})
    monkeypatch.setattr(task.node_repo, 'get_by_id', lambda *args: node)
    create = Mock(return_value=[object()]); monkeypatch.setattr(task.repo, 'create_mtr_job', create)
    assert task.create_mtr(Mock(), 1, 'example.test', 'icmp') is create.return_value[0]

@pytest.mark.parametrize('status', ['offline', 'removed', 'pending'])
def test_monitor_mtr_checks_source_liveness(monkeypatch, status):
    node = SimpleNamespace(id=1, status=status, last_seen_at=None, components={'mtr': True})
    monkeypatch.setattr(task.node_repo, 'get_by_id', lambda *args: node)
    create = Mock(); monkeypatch.setattr(task.repo, 'create_mtr', create)
    with pytest.raises(ValueError, match='不在线'):
        task.create_mtr_for_monitor(Mock(), SimpleNamespace(node_id=1))
    create.assert_not_called()

@pytest.mark.parametrize('trigger', ['periodic', 'failure'])
def test_automatic_missing_mtr_reports_failure_without_spawning_binary(monkeypatch, trigger):
    spec = importlib.util.spec_from_file_location('audit_agent', ROOT/'agent/stella_agent.py')
    assert spec is not None and spec.loader is not None
    agent = importlib.util.module_from_spec(spec); spec.loader.exec_module(agent)
    obj = agent.Agent.__new__(agent.Agent); obj.token='fixture-only'
    done = threading.Event(); reports=[]
    def report(*args, **kwargs): reports.append((args, kwargs)); done.set()
    obj._post=report; obj._mtr_stream=Mock()
    monkeypatch.setattr(agent.shutil, 'which', lambda name: None)
    obj._run_mtr_for_monitor(7, {'mtr_host':'example.test'}, trigger)
    assert done.wait(2)
    obj._mtr_stream.assert_not_called()
    assert reports[0][0] == ('/agent/mtr-report',)
    payload=reports[0][1]['json_body']
    assert payload['ok'] is False and payload['trigger']==trigger and payload['monitor_id']==7
    assert '未安装 MTR' in payload['error']
