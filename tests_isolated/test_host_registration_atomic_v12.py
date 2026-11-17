"""Atomic register transaction and receipt completion, real memory SQL + HTTP."""
import json
from unittest.mock import Mock
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from fastapi import FastAPI, BackgroundTasks
from fastapi.testclient import TestClient
from test_node_monitor_policy import db
from test_install_binding_v12 import approved
from app.models.config import AppConfig
from app.services import node as svc


@pytest.mark.parametrize('fault', ['pin', 'session', 'commit'])
def test_failed_registration_rolls_back_pin_user_session_and_can_retry(db, approved, monkeypatch, fault):
    from app.database import get_db
    from app.routers.auth import router
    from app.models.user import User, AuthSession
    from app.services.admin_security import STATE_KEY
    for table in (User.__table__, AuthSession.__table__):
        table.create(db.get_bind())
    monkeypatch.setattr(svc.host_svc, 'supports_local_install', lambda: False)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    def reject(*args):
        raise RuntimeError('isolated transaction fault')
    def reject_pin(mapper, connection, target):
        if target.key == STATE_KEY:
            reject()
    target, name, handler = ((AppConfig, 'before_update', reject_pin) if fault == 'pin' else
                             (AuthSession, 'before_insert', reject) if fault == 'session' else
                             (db, 'before_commit', reject))
    event.listen(target, name, handler)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            failed = c.post('/auth/register', json={'username': 'owner', 'password': 'fixture-atomic-password'})
        assert failed.status_code == 500
        assert not failed.headers.get_list('set-cookie')
    finally:
        event.remove(target, name, handler)
    # No caller rollback here: register itself must restore a usable transaction.
    with Session(bind=db.get_bind()) as readback:
        assert readback.query(User).count() == readback.query(AuthSession).count() == 0
        assert readback.get(AppConfig, STATE_KEY) is None
        assert readback.get(AppConfig, svc.HOST_INSTALL_KEY) is None
    with TestClient(app) as c:
        retry = c.post('/auth/register', json={'username': 'owner', 'password': 'fixture-atomic-password'})
        assert retry.status_code == 201, retry.text
        assert c.get('/auth/me').json()['id'] == retry.json()['id']
        assert c.post('/auth/register', json={'username': 'another', 'password': 'fixture-atomic-password'}).status_code == 403
    assert db.query(User).count() == db.query(AuthSession).count() == 1
    assert json.loads(db.get(AppConfig, STATE_KEY).value)['owner_id'] == retry.json()['id']


def test_stale_queue_during_explicit_retry_cannot_release_or_mutate_current_receipt(db, approved, monkeypatch):
    monkeypatch.setattr(svc.host_svc, 'supports_local_install', lambda: True)
    tasks = BackgroundTasks(); svc.initialize_host_install(db, tasks)
    task = tasks.tasks[0]
    old_id = task.args[2]
    row = db.get(AppConfig, svc.HOST_INSTALL_KEY)
    queued = json.loads(row.value); queued['updated_at'] -= 300
    row.value = json.dumps(queued); db.commit()
    def installer(*args):
        with Session(bind=db.get_bind()) as check:
            before = check.get(AppConfig, svc.HOST_INSTALL_KEY).value
            assert json.loads(before)['attempt_id'] != old_id
            task.func(*task.args)
            assert check.get(AppConfig, svc.HOST_INSTALL_KEY, populate_existing=True).value == before
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as busy:
                svc.install_host_node(check)
            assert busy.value.status_code == 409
        return {'installed': True}
    install = Mock(side_effect=installer)
    monkeypatch.setattr(svc.host_svc, 'install_host', install)
    result = svc.install_host_node(db)
    assert install.call_count == 1 and result.installed
    assert svc.host_installation(db)['status'] == 'installed'


def test_completion_receipt_fault_cannot_partially_commit_node_flags(db, approved, monkeypatch):
    target = svc.ensure_host_node(db)
    identity = target.id
    monkeypatch.setattr(svc.host_svc, 'install_host', Mock(return_value={'installed': True}))
    def reject_terminal(mapper, connection, record):
        if record.key == svc.HOST_INSTALL_KEY and json.loads(record.value)['status'] == 'installed':
            raise RuntimeError('isolated terminal write fault')
    event.listen(AppConfig, 'before_update', reject_terminal)
    try:
        with pytest.raises(RuntimeError, match='terminal write fault'):
            svc.install_host_node(db)
    finally:
        event.remove(AppConfig, 'before_update', reject_terminal)
        db.rollback()
    with Session(bind=db.get_bind()) as readback:
        current = svc.get_host_node(readback)
        assert current.id == identity and not current.installed
        assert svc.host_installation(readback)['status'] == 'installing'
