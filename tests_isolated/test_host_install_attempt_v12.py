"""Attempt ownership and stable host slot; memory DB and fake OS boundary only."""
import json
from unittest.mock import Mock
import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from test_node_monitor_policy import db, node
from test_install_binding_v12 import approved, client
from app.models.config import AppConfig
from app.services import node as svc


def queue(db, monkeypatch):
    monkeypatch.setattr(svc.host_svc, 'supports_local_install', lambda: True)
    tasks = BackgroundTasks()
    svc.initialize_host_install(db, tasks)
    return tasks.tasks[0]


@pytest.mark.parametrize('outcome', ['success', 'error'])
def test_superseded_running_attempt_cannot_finalize_node_or_receipt(db, approved, monkeypatch, outcome):
    task = queue(db, monkeypatch)
    target = svc.get_host_node(db)
    identity = target.id
    replacement = None
    def installer(*args):
        nonlocal replacement
        with Session(bind=db.get_bind()) as other:
            svc._host_install_state(other, 'installing', 'replacement owns task', identity)
            replacement = other.get(AppConfig, svc.HOST_INSTALL_KEY).value
        if outcome == 'error':
            raise ValueError('obsolete failure')
        return {'installed': True}
    monkeypatch.setattr(svc.host_svc, 'install_host', installer)
    task.func(*task.args)
    db.expire_all()
    assert db.get(AppConfig, svc.HOST_INSTALL_KEY).value == replacement
    assert not db.get(type(target), identity).installed


def test_expired_real_queued_callback_is_exact_read_only(db, approved, monkeypatch):
    task = queue(db, monkeypatch)
    row = db.get(AppConfig, svc.HOST_INSTALL_KEY)
    state = json.loads(row.value)
    state['updated_at'] -= 300
    row.value = json.dumps(state)
    db.commit()
    before = row.value
    install = Mock()
    monkeypatch.setattr(svc.host_svc, 'install_host', install)
    task.func(*task.args)
    db.expire_all()
    assert db.get(AppConfig, svc.HOST_INSTALL_KEY).value == before
    install.assert_not_called()


def test_queued_attempt_identity_is_carried_and_only_consumed_once(db, approved, monkeypatch):
    task = queue(db, monkeypatch)
    queued = svc.host_installation(db)
    assert isinstance(queued.get('attempt_id'), str) and queued['attempt_id']
    assert task.args[2] == queued['attempt_id']
    install = Mock(return_value={'installed': True})
    monkeypatch.setattr(svc.host_svc, 'install_host', install)
    task.func(*task.args)
    done = svc.host_installation(db)
    assert done['status'] == 'installed' and done['attempt_id'] == queued['attempt_id']
    stored = db.get(AppConfig, svc.HOST_INSTALL_KEY).value
    task.func(*task.args)
    assert db.get(AppConfig, svc.HOST_INSTALL_KEY, populate_existing=True).value == stored
    assert install.call_count == 1


def test_replaced_binding_callback_does_not_write_failure_or_create_role(db, approved, monkeypatch):
    task = queue(db, monkeypatch)
    first = svc.get_host_node(db)
    first.status = 'removed'
    db.commit()
    before = db.get(AppConfig, svc.HOST_INSTALL_KEY).value
    count = db.query(type(first)).count()
    task.func(*task.args)
    db.expire_all()
    assert db.get(AppConfig, svc.HOST_INSTALL_KEY).value == before
    assert db.query(type(first)).count() == count


def test_real_host_boundary_uses_explicit_stable_slot(monkeypatch):
    import subprocess
    from app.services import host
    monkeypatch.setattr(host, 'supports_local_install', lambda: True)
    monkeypatch.setattr(host.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(host.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(host.shutil, 'which', lambda name: '/usr/bin/' + name)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, 'stella-agent-' + 'a' * 24, ''))
    monkeypatch.setattr(host.subprocess, 'run', run)
    host.install_host('fixture-token', 'https://new.example')
    argv = run.call_args.args[0]
    assert '--instance' in argv
    assert argv[argv.index('--instance') + 1] == 'host'
    assert '--no-deps' in argv
    assert 'fixture-token' not in argv


@pytest.mark.parametrize('platform', ['linux', 'windows'])
def test_host_manual_command_uses_same_explicit_slot_only_for_role(client, db, approved, platform):
    target = svc.ensure_host_node(db)
    target.platform = platform
    db.commit()
    r = client.post(f'/nodes/{target.id}/install-command')
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
    command = r.json()['command']
    assert ('-Instance \'host\'' if platform == 'windows' else '--instance host') in command
    foreign = node(db, token='fixture-foreign-token')
    foreign.platform = platform
    db.commit()
    foreign_command = client.post(f'/nodes/{foreign.id}/install-command').json()['command']
    assert '--instance' not in foreign_command and '-Instance' not in foreign_command
