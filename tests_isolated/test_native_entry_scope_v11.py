"""Native wire scope and deployment-only CIDR consent, isolated HTTP/SQLite."""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_node_monitor_policy import db, node


def native_scope():
    source = ast.parse((Path(__file__).parents[1] / 'agent/stella_agent.py').read_text())
    names = {'_entry_scope', '_parse_entry_scope', '_entry_ip_allowed'}
    namespace = {}
    exec(compile(ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), '<native-scope>', 'exec'), namespace)
    return namespace


def setup_http(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import Integer
    from app.database import get_db
    from app.models.monitor import MonitorCheck
    from app.routers.monitor import agent_router
    from app.services import entry_registry
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://center.example'}})
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', Integer())
    MonitorCheck.__table__.create(db.get_bind())
    n = node(db, token='owned-native-scope', status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['ping']}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n)
    db.commit()
    app = FastAPI()
    app.include_router(agent_router)
    app.dependency_overrides[get_db] = lambda: db
    return n, TestClient(app)


def test_native_absent_targets_actual_wire(db, monkeypatch):
    monkeypatch.delenv('STELLA_ENTRY_APPROVED_RANGES', raising=False)
    n, client = setup_http(db, monkeypatch)
    with client:
        response = client.get('/agent/config', headers={'Authorization': 'Bearer ' + n.token})
    assert response.status_code == 200
    wire = response.json()['entry_monitoring']
    assert 'targets' not in wire
    assert wire['icmp_available'] is True
    native_scope()['_entry_scope'](wire)
    assert native_scope()['_entry_ip_allowed']('8.8.8.8', wire.get('targets'), wire['approved_ranges'])
    assert not native_scope()['_entry_ip_allowed']('192.168.0.103', wire.get('targets'), wire['approved_ranges'])
    assert response.json().get('report_channel') is None


def test_deployment_exact_private_scope_actual_wire_report_and_health(db, monkeypatch):
    from app.models.monitor import Monitor, MonitorCheck
    from app.services import entry_monitoring as svc
    monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES', '["192.168.0.103/32"]')
    n, client = setup_http(db, monkeypatch)
    with client:
        wire = client.get('/agent/config', headers={'Authorization': 'Bearer ' + n.token}).json()['entry_monitoring']
        assert wire['approved_ranges'] == ['192.168.0.103/32']
        native_scope()['_entry_scope'](wire)
        allowed = native_scope()['_entry_ip_allowed']
        for ip, expected in [('192.168.0.103', True), ('192.168.0.104', False), ('169.254.169.254', False), ('127.0.0.1', False)]:
            assert allowed(ip, wire.get('targets'), wire['approved_ranges']) is expected
        entry = wire['entries'][0]
        sample = {k: entry[k] for k in ('entry_id', 'version', 'hostname')}
        sample.update(sampled_at=datetime.now(timezone.utc).isoformat(), status='complete', results=[dict(ip='192.168.0.103', family=4, status='up', latency_ms=1, loss_pct=0)])
        response = client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token}, json={'control_channel': {'icmp': [sample]}})
        assert response.status_code == 200, response.text
        db.expire_all()
        assert db.query(MonitorCheck).count() == 1
        assert svc.entry_reason(db, db.query(Monitor).one()) == 'healthy'
        before = n.control_channel
        for ip in ('192.168.0.104', '169.254.169.254'):
            sample['results'][0]['ip'] = ip
            response = client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token}, json={'control_channel': {'icmp': [sample]}})
            assert response.status_code == 422
            db.expire_all()
            assert n.control_channel == before
            assert db.query(MonitorCheck).count() == 1
        monkeypatch.delenv('STELLA_ENTRY_APPROVED_RANGES')
        assert svc.entry_reason(db, db.query(Monitor).one()) == 'outside_scope'
        # Deployment permission is not a repair mechanism for malformed raw caps,
        # and invalid deployment input rejects even otherwise valid public IPs.
        for env, cap in [('["192.168.0.103/32"]', {'targets': None}), ('null', {})]:
            monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES', env)
            n.components = {'monitoring': {'ready': True, 'types': ['ping'], **cap}}
            db.commit()
            sample['results'][0]['ip'] = '8.8.8.8'
            response = client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token}, json={'control_channel': {'icmp': [sample]}})
            assert response.status_code == 422
            db.expire_all()
            assert n.control_channel == before
            assert db.query(MonitorCheck).count() == 1
            report = dict(entry_id=None, origin='https://center.example', duration_ms=2, status='ok', http_status=200, sampled_at=datetime.now(timezone.utc).isoformat())
            assert client.post('/agent/report', headers={'Authorization': 'Bearer ' + n.token}, json={'control_channel': {'report': report}}).status_code == 200
            db.expire_all()
            before = n.control_channel


def test_deployment_and_capability_ranges_merge_without_mutating_source(db, monkeypatch):
    from app.services import entry_monitoring as svc
    monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES', '["192.168.0.103/32"]')
    cap = {'ready': True, 'types': ['ping'], 'targets': [], 'approved_ranges': ['10.9.8.7/32']}
    n = node(db, components={'monitoring': cap})
    plan = svc.manifest(n)
    assert plan['icmp_available'] is True
    assert plan['targets'] == []
    assert plan['approved_ranges'] == ['10.9.8.7/32', '192.168.0.103/32']
    assert n.components['monitoring'] == cap
    assert cap['approved_ranges'] == ['10.9.8.7/32']
    allowed = native_scope()['_entry_ip_allowed']
    assert allowed('10.9.8.7', plan['targets'], plan['approved_ranges'])
    assert allowed('192.168.0.103', plan['targets'], plan['approved_ranges'])
    assert not allowed('8.8.8.8', plan['targets'], plan['approved_ranges'])
    assert not allowed('192.168.0.104', plan['targets'], plan['approved_ranges'])


@pytest.mark.parametrize('raw', ['null', '{}', '"192.168.0.103/32"', '[null]', '["192.168.0.103"]', '[' * 1500 + ']' * 1500, '["192.168.0.103/24"]', '["bad"]', json.dumps(['192.168.0.103/32'] * 17), 'not-json'])
def test_invalid_deployment_consent_closes_scope(db, monkeypatch, raw):
    from app.services import entry_monitoring as svc
    monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES', raw)
    n = node(db, components={'monitoring': {'ready': True, 'types': ['ping']}})
    plan = svc.manifest(n)
    assert plan['icmp_available'] is False
    assert plan['targets'] == [] and plan['approved_ranges'] == []


@pytest.mark.parametrize('scope', [{'targets': None}, {'targets': ['bad']}, {'approved_ranges': ['bad']}, {'approved_ranges': ['10.0.0.0/8'] * 16}])
def test_deployment_consent_cannot_rescue_invalid_or_overbudget_cap(db, monkeypatch, scope):
    from app.services import entry_monitoring as svc
    monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES', '["192.168.0.103/32"]')
    n = node(db, components={'monitoring': {'ready': True, 'types': ['ping'], **scope}})
    plan = svc.manifest(n)
    assert plan['icmp_available'] is False
    assert plan['targets'] == [] and plan['approved_ranges'] == []
