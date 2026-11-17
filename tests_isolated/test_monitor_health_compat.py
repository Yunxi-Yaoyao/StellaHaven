"""Stored legacy HTTP targets: read-only compatibility, never write admission."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import Integer, event

from test_node_monitor_policy import db, node
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig
from app.services import monitor as svc


def test_legacy_bare_https_survives_real_config_and_health_reads_without_writes(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.monitor import agent_router, monitor_router
    from app.routers.auth import current_user

    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', Integer())
    MonitorCheck.__table__.create(db.get_bind())
    n = node(db, token='owned-compat', status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['tcp', 'ping'], 'targets': ['e-hentai.org']}})
    m = Monitor(id=45, name='retained', type='https', target='e-hentai.org', node_id=n.id,
                interval=60, timeout=5, status='up', last_check_at=datetime.now(timezone.utc), last_latency_ms=3)
    g = MonitorGroup(name='retained-group')
    db.add_all([m, g]); db.flush()
    db.add_all([MonitorGroupMember(group_id=g.id, monitor_id=m.id, position=0),
                MonitorCheck(monitor_id=m.id, ts=m.last_check_at, success=True, latency_ms=3)])
    db.commit()

    def snapshot():
        return {model.__tablename__: [tuple(repr(getattr(row, c.name)) for c in model.__table__.columns)
                                     for row in db.query(model).order_by(*model.__table__.primary_key.columns)]
                for model in (Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember, AppConfig)}

    before = snapshot()
    app = FastAPI(); app.include_router(agent_router); app.include_router(monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: object()
    statements = []
    def only_select(conn, cursor, statement, *args):
        statements.append(statement)
        assert statement.lstrip().upper().startswith('SELECT'), statement
    event.listen(db.get_bind(), 'before_cursor_execute', only_select)
    try:
        with TestClient(app) as client:
            for _ in range(2):
                response = client.get('/agent/config', headers={'Authorization': 'Bearer owned-compat'})
                assert response.status_code == 200, response.text
                wire = response.json()['monitors']
                assert len(wire) == 1, wire
                assert wire[0] == dict(id=45, type='https', target='https://e-hentai.org', interval=60,
                                      timeout=5, mtr_host='e-hentai.org', mtr_proto='tcp', mtr_port=443)
                response = client.get('/monitors/')
                assert response.status_code == 200, response.text
                item = response.json()[0]
                assert (item['id'], item['target'], item['status'], item['status_reason']) == (
                    45, 'e-hentai.org', 'up', 'healthy')
                response = client.get('/monitors/groups')
                assert response.status_code == 200, response.text
                group = response.json()[0]
                assert (group['child_ids'], group['up_count'], group['down_count']) == ([45], 1, 0)
        assert svc.mtr_spec('https', m.target) == ('e-hentai.org', 'tcp', 443)
        assert snapshot() == before
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', only_select)
    assert statements


@pytest.mark.parametrize('kind,target,normalized,host,port', [
    ('https', 'e-hentai.org', 'https://e-hentai.org', 'e-hentai.org', 443),
    ('http', 'nas/health?q=1', 'http://nas/health?q=1', 'nas', 80),
    ('https', 'nas:8443/path', 'https://nas:8443/path', 'nas', 8443),
    ('https', '[2001:db8::1]:8443/path', 'https://[2001:db8::1]:8443/path', '2001:db8::1', 8443),
    ('https', '例子.测试/path', 'https://xn--fsqu00a.xn--0zwm56d/path', 'xn--fsqu00a.xn--0zwm56d', 443),
    ('http', '192.168.1.2/status', 'http://192.168.1.2/status', '192.168.1.2', 80),
    ('https', 'httpbin.example/path', 'https://httpbin.example/path', 'httpbin.example', 443),
])
def test_legacy_shape_is_only_accepted_on_stored_read_paths(db, kind, target, normalized, host, port):
    from app.monitor_targets import parse_target, parse_stored_target
    from app.schemas.monitor import MonitorCreate, MonitorGroupItemCreate, MonitorUpdate
    from app.routers.monitor import _monitor_for_agent
    with pytest.raises(ValueError): parse_target(kind, target)
    for dto in (MonitorCreate, MonitorGroupItemCreate):
        with pytest.raises(ValueError): dto(name='new', type=kind, target=target, node_id=1)
    with pytest.raises(ValueError): MonitorUpdate(type=kind, target=target)
    parsed = parse_stored_target(kind, target)
    assert (parsed.value, parsed.host, parsed.port) == (normalized, host, port)
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc))
    m = Monitor(name='stored', type=kind, target=target, node_id=n.id, interval=60, timeout=5)
    db.add(m); db.commit()
    with pytest.raises(ValueError): svc.create_monitor(db, 'new', kind, target, 60, 5, n.id)
    with pytest.raises(ValueError): svc.update_monitor(db, m.id, {'target': target})
    db.rollback()
    assert [v.id for v in svc.list_monitors_for_node(db, n.id)] == [m.id]
    assert _monitor_for_agent(m).target == normalized
    assert svc.mtr_spec(kind, target) == (host, 'tcp', port)
    assert (svc.present_monitor(db, m).status, svc.present_monitor(db, m).status_reason) == ('down', 'pending')
    assert db.get(Monitor, m.id).target == target
    assert db.query(Monitor).count() == 1


@pytest.mark.parametrize('target', [
    'http://nas', 'ftp://nas', 'https:/nas', 'https:nas', 'https://', '//nas/path', '/nas',
    'user:secret@nas/path', 'user@nas/path', 'https://user:secret@nas',
    'nas:0', 'nas:65536', 'nas:', 'nas:abc', 'bad_host/path', '123', '999.1.2.3/path',
    'nas\\evil', 'nas\n', 'nas/\x00path', ' nas', 'nas ', 'na s',
    '[fe80::1%eth0]/path', '[192.168.1.2]/path', 'nas?query=1',
    '[v1.example]/health', '[v1.example]:8443/health',
    'https://[v1.example]/health', 'https://[v1.example]:8443/health',
])
def test_malformed_stored_target_is_not_repaired_or_dispatched(db, target):
    from app.monitor_targets import parse_stored_target
    with pytest.raises(ValueError): parse_stored_target('https', target)
    with pytest.raises(ValueError): svc.mtr_spec('https', target)
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc))
    m = Monitor(name='bad-stored', type='https', target=target, node_id=n.id,
                interval=60, timeout=5, status='up', last_check_at=datetime.now(timezone.utc))
    db.add(m); db.commit()
    assert svc.list_monitors_for_node(db, n.id) == []
    assert (svc.present_monitor(db, m).status, svc.present_monitor(db, m).status_reason) == ('down', 'invalid_target')
    assert db.get(Monitor, m.id).target == target


def test_legacy_target_scope_and_stale_evidence_still_gate_health(db):
    from datetime import timedelta
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc),
             components={'monitoring': {'ready': True, 'types': ['tcp'], 'targets': ['other.example']}})
    m = Monitor(name='retained', type='https', target='e-hentai.org', node_id=n.id,
                interval=60, timeout=5, status='up', last_check_at=datetime.now(timezone.utc))
    db.add(m); db.commit()
    assert svc.present_monitor(db, m).status_reason == 'outside_scope'
    n.components = {'monitoring': {'ready': False}}; db.commit()
    assert svc.present_monitor(db, m).status_reason == 'unavailable'
    n.components = None; m.last_check_at -= timedelta(seconds=181); db.commit()
    assert svc.present_monitor(db, m).status_reason == 'stale'
    n.status = 'offline'; db.commit()
    assert svc.present_monitor(db, m).status_reason == 'source_offline'
    assert svc.present_monitor(db, m).status == 'down'
    assert m.status == 'up' and m.target == 'e-hentai.org'
