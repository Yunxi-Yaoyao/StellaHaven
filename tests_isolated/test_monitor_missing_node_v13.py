"""Real monitor router/service and memory SQLite; run with owned offline runner.

The original 404 test is AST-loaded byte-for-byte, never imported via conftest.
Only authenticated positive transport is supplied; anonymous requests exercise
real current_user/admin_user. No configured DB, startup, network or services.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import event

from test_node_monitor_policy import db, node
from test_entry_monitor_groups import tables

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api(db):
    from app.database import get_db
    from app.routers import monitor
    from app.routers.auth import current_user, admin_user
    app = FastAPI()
    app.include_router(monitor.monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    def signed(request: Request):
        request.state.auth_session = SimpleNamespace(id='monitor404-owner')
        return object()
    app.dependency_overrides[current_user] = signed
    app.dependency_overrides[admin_user] = signed
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, current_user=current_user,
                              admin_user=admin_user, db=db, route=monitor)


def snapshot(db):
    from app.models.monitor import Monitor, MonitorCheck
    from app.models.config import AppConfig
    db.expire_all()
    return ([(m.id, m.node_id, m.name, m.target, m.status) for m in db.query(Monitor).order_by(Monitor.id)],
            db.query(MonitorCheck).count(),
            [(c.key, c.value) for c in db.query(AppConfig).order_by(AppConfig.key)])


def payload(node_id):
    return dict(name='probe', type='tcp', target='1.1.1.1:80', node_id=node_id)


def assert_rejected_without_write(api, body, status):
    before = snapshot(api.db)
    writes = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
            writes.append(statement)
    engine = api.db.get_bind()
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        response = api.client.post('/monitors/', json=body)
        assert snapshot(api.db) == before
        assert writes == []
        assert response.status_code == status, response.text
        return response
    finally:
        event.remove(engine, 'before_cursor_execute', observe)


def test_original_create_monitor_bad_node_unchanged(api):
    path = ROOT / 'tests/test_monitor_items.py'
    tree = ast.parse(path.read_text())
    original = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'test_create_monitor_bad_node')
    namespace = {}
    exec(compile(ast.Module(body=[original], type_ignores=[]), str(path), 'exec'), namespace)
    before = snapshot(api.db)
    try:
        namespace['test_create_monitor_bad_node'](api.client)
    finally:
        assert snapshot(api.db) == before


@pytest.mark.parametrize('state', ['missing', 'removed'])
def test_missing_or_removed_node_is_404_without_writes(api, state):
    node_id = 999999 if state == 'missing' else node(api.db, status='removed').id
    assert_rejected_without_write(api, payload(node_id), 404)


def test_valid_node_creates_exactly_one_monitor_and_bumps_version(api):
    from app.models.monitor import Monitor, MonitorCheck
    from app.repositories.config import get_monitors_version
    n = node(api.db)
    version = get_monitors_version(api.db)
    response = api.client.post('/monitors/', json=payload(n.id))
    assert response.status_code == 201, response.text
    api.db.expire_all()
    monitor = api.db.query(Monitor).one()
    assert monitor.id == response.json()['id']
    assert (monitor.node_id, monitor.target, monitor.status) == (n.id, '1.1.1.1:80', 'unknown')
    assert api.db.query(MonitorCheck).count() == 0
    assert get_monitors_version(api.db) == version + 1


@pytest.mark.parametrize('state', ['missing', 'removed', 'valid'])
@pytest.mark.parametrize('invalid', [dict(type='bogus'), dict(target='bad:port'),
                                    dict(interval=0), dict(timeout=0), dict(name=' '),
                                    dict(node_id=0), dict(node_id='not-an-id'), dict(node_id=None)])
def test_malformed_body_remains_422_before_node_lookup(api, state, invalid, monkeypatch):
    node_id = 999999 if state == 'missing' else node(api.db, status='removed' if state == 'removed' else 'pending').id
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid request reached node lookup/service')
    monkeypatch.setattr(api.route.node_svc, 'get_node', forbidden)
    monkeypatch.setattr(api.route.monitor_svc, 'create_monitor', forbidden)
    assert_rejected_without_write(api, payload(node_id) | invalid, 422)


def test_service_value_error_stays_400_without_writes(api, monkeypatch):
    n = node(api.db)
    def rejected(*args, **kwargs):
        raise ValueError('independent validation rejection')
    monkeypatch.setattr(api.route.monitor_svc, 'create_monitor', rejected)
    response = assert_rejected_without_write(api, payload(n.id), 400)
    assert response.json() == {'detail': 'independent validation rejection'}


@pytest.mark.parametrize('state', ['missing', 'removed', 'valid'])
@pytest.mark.parametrize('malformed', [False, True])
def test_anonymous_real_auth_is_401_before_resource_lookup(api, state, malformed, monkeypatch):
    node_id = 999999 if state == 'missing' else node(api.db, status='removed' if state == 'removed' else 'pending').id
    api.app.dependency_overrides.pop(api.current_user)
    api.app.dependency_overrides.pop(api.admin_user)
    def forbidden(*args, **kwargs):
        raise AssertionError('anonymous request reached node lookup/service')
    monkeypatch.setattr(api.route.node_svc, 'get_node', forbidden)
    monkeypatch.setattr(api.route.monitor_svc, 'create_monitor', forbidden)
    body = payload(node_id) | ({'type': 'bogus'} if malformed else {})
    assert_rejected_without_write(api, body, 401)
