"""R1: complete raw scope admission; owned SQLite/HTTP, never network probes."""
from datetime import datetime, timezone
from unittest.mock import Mock
import importlib.util
from pathlib import Path
import pytest
from test_node_monitor_policy import db, node


@pytest.fixture
def agent():
    spec = importlib.util.spec_from_file_location('scope_agent', Path(__file__).parents[1] / 'agent/stella_agent.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.Agent.__new__(mod.Agent)


INVALID_SCOPES = [
    pytest.param({'targets': [], 'approved_ranges': ranges}, '192.168.1.2', id='cidr-' + position)
    for position, ranges in (
        ('prefix', ['NOT-A-CIDR', '192.168.0.0/16', 'fd00::/64']),
        ('middle', ['192.168.0.0/16', 'NOT-A-CIDR', 'fd00::/64']),
        ('suffix', ['192.168.0.0/16', 'fd00::/64', 'NOT-A-CIDR']))
] + [
    pytest.param({'targets': value, 'approved_ranges': ['0.0.0.0/0']}, '8.8.8.8', id='targets-' + name)
    for name, value in (
        ('null', None), ('int', 3), ('dict', {'8.8.8.8': True}), ('scalar', '8.8.8.8'),
        ('bool', True), ('null-member', ['8.8.8.8', None]),
        ('int-member', ['8.8.8.8', 3]), ('dict-member', ['8.8.8.8', {}]),
        ('bad-prefix', ['NOT-AN-IP', '8.8.8.8']), ('bad-middle', ['8.8.8.8', 'bad', 'fd00::2']),
        ('bad-suffix', ['8.8.8.8', 'bad']), ('zone', ['8.8.8.8', 'fe80::1%eth0']),
        ('budget', ['8.8.8.8'] * 65), ('string-bound', ['8.8.8.8', 'x' * 65]))
] + [
    pytest.param({'targets': ['8.8.8.8'], 'approved_ranges': value}, '8.8.8.8', id='ranges-' + name)
    for name, value in (
        ('null', None), ('int', 3), ('dict', {}), ('scalar', '0.0.0.0/0'),
        ('null-member', ['0.0.0.0/0', None]), ('int-member', ['0.0.0.0/0', 3]),
        ('dict-member', ['0.0.0.0/0', {}]), ('bad-member', ['0.0.0.0/0', 'bad']),
        ('host-bits', ['0.0.0.0/0', '192.168.1.2/16']),
        ('budget', ['0.0.0.0/0'] * 17), ('string-bound', ['x' * 65]))
]


def sample(entry, ip):
    return dict(entry_id=entry['entry_id'], version=entry['version'], hostname=entry['hostname'],
                sampled_at=datetime.now(timezone.utc).isoformat(), status='complete',
                results=[dict(ip=ip, family=4, status='up', latency_ms=1, loss_pct=0)])


@pytest.mark.parametrize('scope,ip', [
    pytest.param({'targets': [], 'approved_ranges': ['192.168.0.0/16', 'NOT-A-CIDR']}, '192.168.1.2', id='bad-cidr-suffix'),
    pytest.param({'targets': None}, '8.8.8.8', id='explicit-null'),
    *INVALID_SCOPES,
])
def test_raw_scope_rejected_before_agent_dispatch_and_http_storage(db, agent, monkeypatch, scope, ip):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import Integer
    from app.database import get_db
    from app.models.monitor import Monitor, MonitorCheck
    from app.routers.monitor import agent_router
    from app.services import entry_monitoring as svc, entry_registry
    from app.services.entry_targets import _entry_ip_allowed
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example'}})
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', Integer())
    from app.models.alert import AlertRule
    MonitorCheck.__table__.create(db.get_bind())
    AlertRule.__table__.create(db.get_bind(), checkfirst=True)
    n = node(db, token='owned-scope-token', status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['ping'], **scope}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n); db.commit()
    before = n.control_channel
    entry = svc.manifest(n, db=db)['entries'][0]
    mod, obj = agent
    obj._entry_manifest = dict(icmp_available=True, entries=[entry], **scope)
    obj._entry_resolve = Mock(return_value=[ip])
    obj._entry_ping = Mock(return_value=sample(entry, ip)['results'][0])
    obj.run_entry_probes()
    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        config = client.get('/agent/config', headers={'Authorization': 'Bearer ' + n.token})
        assert config.status_code == 200
        wire = config.json()['entry_monitoring']
        assert wire['icmp_available'] is False and wire['targets'] == [] and wire['approved_ranges'] == []
        # Explicit lifecycle reconciliation above creates identities; config GET is read-only.
        logical_before = [(m.id, m.target, m.status, m.last_check_at, m.last_latency_ms)
                          for m in db.query(Monitor).order_by(Monitor.id)]
        assert len(logical_before) == 1
        assert logical_before[0][1:] == ('main.example', 'unknown', None, None)
        response = client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token},
                               json={'components': n.components, 'control_channel': {'icmp': [sample(entry, ip)]}})
    db.expire_all()
    observed = dict(http_status=response.status_code, ping_calls=obj._entry_ping.call_count,
                    monitors=db.query(Monitor).count(), checks=db.query(MonitorCheck).count(),
                    channel_unchanged=n.control_channel == before)
    print('R1 observed:', observed)
    assert observed == dict(http_status=422, ping_calls=0, monitors=1, checks=0, channel_unchanged=True)
    assert [(m.id, m.target, m.status, m.last_check_at, m.last_latency_ms)
            for m in db.query(Monitor).order_by(Monitor.id)] == logical_before
    assert obj._entry_samples[0]['status'] == 'outside_scope'
    obj._entry_resolve.assert_not_called()
    if scope.get('targets') is not None:
        assert not _entry_ip_allowed(ip, scope['targets'], scope['approved_ranges'])
        assert not mod._entry_ip_allowed(ip, scope['targets'], scope['approved_ranges'])

    from app.services.entry_targets import _entry_scope
    for parse in (_entry_scope, mod._entry_scope):
        with pytest.raises((ValueError, TypeError)):
            parse(scope)
    plan = svc.manifest(n)
    assert plan['icmp_available'] is False
    assert plan['targets'] == [] and plan['approved_ranges'] == []


def test_absent_scope_survives_actual_config_serialization_and_dispatch(db, agent, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.monitor import agent_router
    from app.services import entry_registry
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example'}})
    n = node(db, token='owned-config-token', status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['ping']}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n); db.commit()
    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get('/agent/config', headers={'Authorization': 'Bearer ' + n.token})
    assert response.status_code == 200
    plan = response.json()['entry_monitoring']
    # None is a trusted internal sentinel, not a valid raw wire value.
    assert 'targets' not in plan
    mod, obj = agent
    obj._entry_manifest = plan
    obj._entry_resolve = Mock(return_value=['8.8.8.8'])
    obj._entry_ping = Mock(return_value=sample(plan['entries'][0], '8.8.8.8')['results'][0])
    obj.run_entry_probes()
    assert obj._entry_samples[0]['status'] == 'complete'
    assert obj._entry_ping.call_count == 1


@pytest.mark.parametrize('ip,targets,ranges,allowed', [
    ('8.8.8.8', None, [], True), ('192.168.1.2', None, [], False),
    ('8.8.8.8', [], [], False), ('192.168.1.2', [], [], False),
    ('192.168.1.2', ['192.168.1.2', 'fd00::2'], [], True),
    ('fd00::2', ['192.168.1.2', 'fd00::2'], [], True),
    ('192.168.1.2', [], ['fd00::/64', '192.168.0.0/16'], True),
    ('fd00::2', [], ['192.168.0.0/16', 'fd00::/64'], True),
    ('8.8.8.8', ['8.8.8.8'], [], True), ('1.1.1.1', ['8.8.8.8'], [], False),
    ('::ffff:192.168.1.2', ['192.168.1.2'], [], True),
    ('192.168.1.2', ['::ffff:192.168.1.2'], [], False),
    ('169.254.169.254', ['169.254.169.254'], ['0.0.0.0/0'], False),
    ('127.0.0.1', ['127.0.0.1'], ['0.0.0.0/0'], False),
    ('::ffff:127.0.0.1', None, ['0.0.0.0/0'], False),
    ('100.100.100.200', None, ['0.0.0.0/0'], False),
    ('168.63.129.16', None, ['0.0.0.0/0'], False),
    ('fd00:ec2::254', None, ['fd00::/8'], False),
    ('fe80::1', ['fe80::1'], ['::/0'], False),
    ('fe80::1%eth0', None, [], False), ('0.0.0.0', None, [], False),
    ('ff02::1', None, ['::/0'], False), ('224.0.0.1', None, ['0.0.0.0/0'], False),
])
def test_numeric_scope_compatibility_and_special_destinations(agent, ip, targets, ranges, allowed):
    from app.services.entry_targets import _entry_ip_allowed
    mod, _ = agent
    assert _entry_ip_allowed(ip, targets, ranges) is allowed
    assert mod._entry_ip_allowed(ip, targets, ranges) is allowed


def test_agent_server_scope_helpers_are_exact_ast_mirrors(agent):
    import ast
    import inspect
    from app.services import entry_targets
    mod, _ = agent
    for name in ('_parse_entry_scope', '_entry_scope', '_entry_ip_allowed'):
        assert ast.dump(ast.parse(inspect.getsource(getattr(mod, name)))) == ast.dump(
            ast.parse(inspect.getsource(getattr(entry_targets, name))))


@pytest.mark.parametrize('scope,ip,allowed', [
    ({}, '8.8.8.8', True), ({}, '192.168.1.2', False),
    ({'targets': []}, '8.8.8.8', False),
    ({'targets': []}, '192.168.1.2', False),
    ({'targets': ['192.168.1.2', 'fd00::2']}, '192.168.1.2', True),
    ({'targets': [], 'approved_ranges': ['fd00::/64', '192.168.0.0/16']}, '192.168.1.2', True),
])
def test_legitimate_scope_agent_and_actual_http_storage(db, agent, monkeypatch, scope, ip, allowed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import Integer
    from app.database import get_db
    from app.models.monitor import Monitor, MonitorCheck
    from app.models.alert import AlertRule
    from app.routers.monitor import agent_router
    from app.services import entry_monitoring as svc, entry_registry, node_monitor_policy
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example'}})
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', Integer())
    MonitorCheck.__table__.create(db.get_bind())
    AlertRule.__table__.create(db.get_bind(), checkfirst=True)
    n = node(db, token='owned-legitimate-token', status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['ping'], **scope}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n); db.commit()
    entry = svc.manifest(n, db=db)['entries'][0]
    mod, obj = agent
    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        plan = client.get('/agent/config', headers={'Authorization': 'Bearer ' + n.token}).json()['entry_monitoring']
        obj._entry_manifest = plan
        obj._entry_resolve = Mock(return_value=[ip])
        obj._entry_ping = Mock(return_value=sample(entry, ip)['results'][0])
        obj.run_entry_probes()
        response = client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token},
                               json={'control_channel': {'icmp': [sample(entry, ip)]}})
    assert obj._entry_ping.call_count == int(allowed)
    assert response.status_code == (200 if allowed else 422)
    db.expire_all()
    assert db.query(Monitor).count() == 1  # stable node × entry regardless of scope
    assert db.query(MonitorCheck).count() == int(allowed)
    assert node_monitor_policy.dispatched(db, db.query(Monitor).all()) == []
    if not allowed:
        assert n.control_channel is None
        logical = db.query(Monitor).one()
        assert (logical.target, logical.status, logical.last_check_at, logical.last_latency_ms) == ('main.example', 'unknown', None, None)
    else:
        assert n.control_channel['icmp'][0]['results'][0]['ip'] == ip
        assert svc.current_ids(db)
        n.components = {'monitoring': {'ready': True, 'types': ['ping'], 'targets': None}}
        db.commit()
        assert svc.current_ids(db) == set()
        assert node_monitor_policy.dispatched(db, db.query(Monitor).all()) == []
        assert db.query(Monitor).count() == 1 and db.query(MonitorCheck).count() == 1


@pytest.mark.parametrize('cap', [None, 1, [], 'bad'])
def test_non_object_raw_capability_is_closed(db, monkeypatch, cap):
    from app.services import entry_monitoring as svc, entry_registry
    from app.schemas.control_channel import ControlChannel
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example'}})
    n = node(db, components={'monitoring': cap})
    plan = svc.manifest(n)
    assert plan['icmp_available'] is False
    assert plan['targets'] == [] and plan['approved_ranges'] == []
    with pytest.raises(ValueError):
        svc.save_channel(db, n, ControlChannel(icmp=[sample(plan['entries'][0], '8.8.8.8')]))
    assert n.control_channel is None


def test_invalid_scope_does_not_disable_nullable_report_only_channel(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.models.alert import AlertRule
    from app.models.monitor import Monitor
    from app.routers.monitor import agent_router
    from app.services import entry_registry
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example'}})
    AlertRule.__table__.create(db.get_bind(), checkfirst=True)
    n = node(db, token='owned-report-only-token', status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['ping'], 'targets': None}})
    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token},
                           json={'control_channel': None}).status_code == 200
        report = dict(entry_id=None, origin='https://main.example', duration_ms=4, status='ok',
                      http_status=200, error=None, sampled_at=datetime.now(timezone.utc).isoformat())
        response = client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token},
                               json={'control_channel': {'report': report}})
        assert response.status_code == 200
        db.expire_all()
        before = n.control_channel
        from app.schemas.control_channel import ReportTransaction
        assert before['report'] == ReportTransaction.model_validate(report).model_dump(mode='json')
        logical_before = [(m.id, m.target, m.status, m.last_check_at, m.last_latency_ms)
                          for m in db.query(Monitor).order_by(Monitor.id)]
        assert len(logical_before) == 1
        assert logical_before[0][1:] == ('main.example', 'unknown', None, None)
        from app.services.entry_monitoring import manifest
        entry = manifest(n)['entries'][0]
        # Reject the whole telemetry transaction, including a newer report.
        report = {**report, 'duration_ms': 8, 'sampled_at': datetime.now(timezone.utc).isoformat()}
        assert client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token},
                           json={'control_channel': {'report': report, 'icmp': [sample(entry, '8.8.8.8')]}}).status_code == 422
        db.expire_all()
        assert n.control_channel == before
        assert [(m.id, m.target, m.status, m.last_check_at, m.last_latency_ms)
                for m in db.query(Monitor).order_by(Monitor.id)] == logical_before
    from app.schemas.public_node import Components
    assert Components.model_validate(n.components).monitoring.targets is None
