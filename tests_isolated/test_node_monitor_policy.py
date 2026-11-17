"""Policy tests use only in-memory SQLite; never the configured/live database."""
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from app.models.node import Node
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig
from app.models.alert import AlertRule, AlertState

@compiles(JSONB, 'sqlite')
def sqlite_jsonb(element, compiler, **kw):
    return 'JSON'

@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    for table in (Node.__table__, Monitor.__table__, AppConfig.__table__, MonitorGroup.__table__, MonitorGroupMember.__table__, AlertRule.__table__, AlertState.__table__):
        table.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()

def node(db, name='owned', host='192.168.160.3', **kw):
    obj = Node(name=name, host=host, platform='linux', **kw)
    db.add(obj); db.commit()
    return obj

def test_names_and_loopback_cannot_uninstall_the_host(db, monkeypatch):
    from app.services import node as svc
    uninstall = Mock()
    monkeypatch.setattr(svc.host_svc, 'uninstall_host', uninstall)
    for name, host in [('Stella', '192.168.160.3'), ('other', '127.0.0.1')]:
        obj = node(db, name, host)
        svc.remove_node(db, obj.id)
    uninstall.assert_not_called()


def test_existing_local_service_is_not_claimed_by_preview_install(db, monkeypatch):
    # Existing global/foreign service is not ownership. Exercise real admission,
    # role binding and route serialization, mocking only the OS installer edge.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import monitor
    from app.services import node as svc, request_security
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://new.example')
    monkeypatch.setattr(request_security, 'trusted_origins', lambda: {'https://new.example'})
    monkeypatch.setattr(monitor.host_svc, 'supports_local_install', lambda: True)
    probe = Mock(side_effect=AssertionError('global process cannot establish ownership'))
    monkeypatch.setattr(monitor.host_svc, 'is_agent_installed', probe)
    foreign = node(db, name='Stella', host='127.0.0.1', token='foreign-fixture-token',
                   installed=True, status='online')
    foreign_id = foreign.id
    install = Mock(return_value={'installed': True})
    monkeypatch.setattr(monitor.host_svc, 'install_host', install)
    app = FastAPI(); app.include_router(monitor.node_router)
    app.dependency_overrides[monitor.get_db] = lambda: db
    app.dependency_overrides[monitor.current_user] = lambda: None
    app.dependency_overrides[monitor.admin_user] = lambda: None
    with TestClient(app) as client:
        response = client.post('/nodes/host/install')
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'pending' and 'token' not in response.json()
    owned = svc.get_host_node(db)
    assert owned.id != foreign_id
    install.assert_called_once_with(owned.token, 'https://new.example')
    assert svc.host_installation(db)['status'] == 'installed'
    db.expire_all()
    foreign = db.get(Node, foreign_id)
    assert (foreign.name, foreign.host, foreign.token, foreign.installed, foreign.status) == (
        'Stella', '127.0.0.1', 'foreign-fixture-token', True, 'online')
    probe.assert_not_called()


def test_explicit_online_capable_source_creates_once_and_never_self_monitors(db):
    from app.services import node_monitor_policy as policy
    source = node(db, 'not-named-Stella', '192.168.160.2', status='online',
                  last_seen_at=datetime.now(timezone.utc),
                  components={'monitoring': {'ready': True, 'types': ['ping'],
                              'targets': ['192.168.160.2', '192.168.160.3']}})
    target = node(db)
    saved = policy.update(db, {'revision': 0, 'enabled': True,
                         'source_node_id': source.id, 'host_node_id': None, 'interval': 60})
    policy.reconcile(db)
    rows = db.query(Monitor).all()
    assert len(rows) == 1
    assert (rows[0].node_id, rows[0].target, rows[0].interval) == (source.id, target.host, 60)
    assert saved['source_ready'] is True
    assert policy.read(db)['managed'][0]['target_node_id'] == target.id
    # A user deleting the item must not have it resurrected on the next heartbeat.
    db.delete(rows[0]); db.commit()
    policy.reconcile(db)
    assert db.query(Monitor).count() == 0


def test_policy_source_waits_for_real_capability_and_scoped_targets(db):
    from app.services import node_monitor_policy as p
    source = node(db, 'Stella', '192.168.160.2')
    target = node(db)
    other = node(db, 'not owned', '192.168.160.4')
    node(db, 'unsafe loopback', '127.0.0.1')
    p.update(db, {'revision': 0, 'enabled': True, 'source_node_id': source.id,
                 'host_node_id': None, 'interval': 60})
    assert db.query(Monitor).count() == 0
    source.status = 'online'; source.last_seen_at = datetime.now(timezone.utc)
    source.components = {'mtr': {'installed': True}}
    db.commit(); p.reconcile(db)
    assert db.query(Monitor).count() == 0
    source.components = {'monitoring': {'ready': True, 'types': ['ping'], 'targets': [target.host]}}
    db.commit(); p.reconcile(db)
    assert [m.target for m in db.query(Monitor)] == [target.host]
    assert {'node_id': other.id, 'reason': 'outside_source_scope'} in p.read(db)['pending']
    # A heartbeat/source address is neither a host role nor an authorized target.
    from app.services.node import get_host_node
    assert get_host_node(db) is None


def test_explicit_host_binding_survives_rename_but_does_not_install(db, monkeypatch):
    from app.services import node_monitor_policy as p, node as n
    obj = node(db, 'actual host', '192.168.160.3')
    install = Mock(); monkeypatch.setattr(n.host_svc, 'install_host', install)
    p.update(db, {'revision': 0, 'enabled': False, 'source_node_id': None,
                 'host_node_id': obj.id, 'interval': 60})
    obj.name = 'renamed'; db.commit()
    assert n.get_host_node(db).id == obj.id
    install.assert_not_called()


def test_container_source_cannot_be_bound_as_the_real_host(db):
    from app.services import node_monitor_policy as p
    from fastapi import HTTPException
    obj=node(db,components={'monitoring':{'scope':'container','ready':True,'types':['ping']}})
    with pytest.raises(HTTPException) as exc:
        p.update(db,{'revision':0,'enabled':True,'source_node_id':obj.id,'host_node_id':obj.id,'interval':60})
    assert exc.value.status_code==422


def test_suppression_and_global_pause_stop_dispatch_without_erasing_history(db):
    from app.services import node_monitor_policy as p
    source = node(db, 'source', '192.168.160.2', status='online',
                  last_seen_at=datetime.now(timezone.utc),
                  components={'monitoring': {'ready': True, 'types': ['ping']}})
    target = node(db)
    p.update(db, {'revision': 0, 'enabled': True, 'source_node_id': source.id,
                 'host_node_id': None, 'interval': 60})
    items = db.query(Monitor).all(); identity = items[0].id
    p.suppress(db, target.id, True); p.reconcile(db)
    assert p.dispatched(db, items) == []
    items[0].status='up';items[0].last_check_at=datetime.now(timezone.utc);db.commit()
    from app.services.monitor import list_monitors
    assert (list_monitors(db)[0].status, list_monitors(db)[0].status_reason)==('down','restricted')
    assert db.get(Monitor, identity) is not None
    p.suppress(db, target.id, False)
    assert [m.id for m in p.dispatched(db, items)] == [identity]
    source.components = {'monitoring': {'ready': True, 'types': ['ping'], 'targets': []}}
    db.commit()
    assert p.dispatched(db, items) == []
    manual=Monitor(name='manual',node_id=source.id,type='tcp',target=target.host+':8080',interval=60,timeout=2,status='unknown')
    db.add(manual);db.commit()
    p.update(db,{'revision':p.read(db)['revision'],'enabled':False,'source_node_id':source.id,'host_node_id':None,'interval':60})
    assert p.dispatched(db,items+[manual]) == [manual]
    p.reconcile(db)
    assert db.query(Monitor).count()==2


def test_policy_cas_and_creation_hook(db):
    from app.services import node_monitor_policy as p, node as n
    from fastapi import HTTPException
    source = node(db, 'source', '192.168.160.2', status='online',
                  last_seen_at=datetime.now(timezone.utc),
                  components={'monitoring': {'ready': True, 'types': ['ping']}})
    fields = {'revision': 0, 'enabled': True, 'source_node_id': source.id,
              'host_node_id': None, 'interval': 60}
    p.update(db, fields)
    with pytest.raises(HTTPException) as exc:
        p.update(db, fields)
    assert exc.value.status_code == 409
    obj = n.create_node(db, 'new', 'linux', '192.168.160.3')
    assert db.query(Monitor).filter(Monitor.target == obj.host).count() == 1


def test_create_and_auto_monitor_failure_are_atomic(db, monkeypatch):
    from app.services import node_monitor_policy as p, node as n
    def fail(*args):raise RuntimeError('isolated failure')
    monkeypatch.setattr(p, '_reconcile', fail)
    with pytest.raises(RuntimeError):n.create_node(db,'new','linux','192.168.160.3')
    assert db.query(Node).count()==0


def test_policy_http_requires_admin_and_rejects_unknown_keys(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import node_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    app = FastAPI(); app.include_router(node_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        body = {'revision': 0, 'enabled': False, 'source_node_id': None, 'host_node_id': None, 'interval': 60}
        assert client.put('/nodes/monitoring-policy', json=body).status_code == 401
        app.dependency_overrides[current_user] = lambda: object()
        response = client.get('/nodes/monitoring-policy')
        assert response.status_code == 200
        assert response.json()['source_ready'] is False
        app.dependency_overrides[admin_user] = lambda: object()
        assert client.put('/nodes/monitoring-policy', json={**body, 'interval': 1}).status_code == 422
        assert client.put('/nodes/monitoring-policy', json={**body, 'token': 'do-not-accept'}).status_code == 422
        assert client.put('/nodes/monitoring-policy', json=body).status_code == 200
        assert client.get('/nodes/monitoring-policy').json()['enabled'] is False


def test_agent_reports_real_local_ping_capability_only(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('isolated_policy_agent', Path(__file__).parents[1] / 'agent/stella_agent.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    obj = mod.Agent.__new__(mod.Agent)
    monkeypatch.setattr(mod.shutil, 'which', lambda name: '/usr/bin/ping' if name == 'ping' else None)
    calls = []
    def run(argv, **kw):
        calls.append(argv); return Mock(returncode=0)
    monkeypatch.setattr(mod.subprocess, 'run', run)
    result = obj._monitoring_capability()
    assert result == {'ready': True, 'types': ['tcp', 'ping']}
    assert calls == [['/usr/bin/ping', '-c', '1', '-W', '1', '127.0.0.1']]
    monkeypatch.setattr(mod.subprocess, 'run', lambda *a, **kw: Mock(returncode=1))
    assert obj._monitoring_capability() == {'ready': True, 'types': ['tcp']}
