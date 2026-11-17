"""Binary business availability is read-only, distinct from target samples."""
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import Integer
from test_node_monitor_policy import db, node
from test_monitor_lifecycle_v7 import client_for
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.models.config import AppConfig


def fixture(db, monkeypatch):
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', Integer())
    MonitorCheck.__table__.create(db.get_bind())
    source = node(db, status='online', last_seen_at=datetime.now(timezone.utc))
    item = Monitor(name='retained probe', node_id=source.id, type='ping', target='192.168.160.4',
                   interval=60, timeout=2, status='up', last_check_at=datetime.now(timezone.utc), last_latency_ms=3)
    group = MonitorGroup(name='retained group')
    db.add_all([item, group]); db.flush()
    db.add(MonitorGroupMember(group_id=group.id, monitor_id=item.id, position=0))
    db.add(MonitorCheck(monitor_id=item.id, ts=item.last_check_at, success=True, latency_ms=3, loss_pct=0))
    db.commit()
    return source, item, group


def snapshot(db):
    return {model.__tablename__: [tuple(getattr(row, c.name) for c in model.__table__.columns)
            for row in db.query(model).all()]
            for model in (Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember, AppConfig)}


@pytest.mark.parametrize('case,status,reason', [
    ('fresh', 'up', 'healthy'), ('target_down', 'down', 'failure'),
    ('no_sample', 'down', 'pending'), ('unknown_sample', 'down', 'pending'),
    ('stale', 'down', 'stale'), ('source_offline', 'down', 'source_offline'),
    ('heartbeat_expired', 'down', 'source_offline'), ('source_pending', 'down', 'source_pending'),
    ('restricted', 'down', 'restricted'), ('unsupported', 'down', 'unsupported'),
    ('outside_scope', 'down', 'outside_scope'), ('invalid', 'down', 'invalid_target'),
    ('unavailable', 'down', 'unavailable'),
])
def test_real_api_binary_cause_counts_and_unchanged_samples(db, monkeypatch, case, status, reason):
    source, item, group = fixture(db, monkeypatch)
    if case == 'target_down': item.status = 'down'
    if case == 'no_sample': item.last_check_at = None; item.status = 'unknown'
    if case == 'unknown_sample': item.status = 'unknown'
    if case == 'stale': item.last_check_at -= timedelta(days=1)
    if case == 'source_offline': source.status = 'offline'
    if case == 'source_pending': source.status = 'pending'
    if case == 'heartbeat_expired': source.last_seen_at -= timedelta(seconds=121)
    if case == 'restricted':
        from app.services import node_monitor_policy as policy
        policy._save(db, {'enabled': False, 'managed': {'target': {
            'monitor_id': item.id, 'source_node_id': source.id, 'target_node_id': source.id}}})
    if case == 'unsupported': source.components = {'monitoring': {'ready': True, 'types': []}}
    if case == 'outside_scope': source.components = {'monitoring': {'ready': True, 'types': ['ping'], 'targets': []}}
    if case == 'invalid': item.target = 'bad:target'
    if case == 'unavailable': source.components = {'monitoring': {'ready': False}}
    db.commit(); before = snapshot(db)
    client = client_for(db)
    from sqlalchemy import event
    sql = []
    def read_only(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)
        assert statement.lstrip().upper().startswith('SELECT'), statement
    event.listen(db.get_bind(), 'before_cursor_execute', read_only)
    for _ in range(2):
        response = client.get('/monitors/'); assert response.status_code == 200, response.text
        projected = response.json()[0]
        assert (projected['status'], projected['status_reason']) == (status, reason)
        assert projected['last_latency_ms'] == (3 if status == 'up' else None)
        response = client.get('/monitors/groups'); assert response.status_code == 200, response.text
        result = response.json()[0]
        assert result['status'] == status
        assert result['up_count'] + result['down_count'] == len(result['child_ids']) == 1
        assert result['unknown_count'] == 0  # deprecated wire count, never a business state
    assert sql
    event.remove(db.get_bind(), 'before_cursor_execute', read_only)
    assert snapshot(db) == before
    assert db.get(MonitorGroup, group.id).stable_uuid == group.stable_uuid


@pytest.mark.parametrize('policy,expected', [('any', 'down'), ('all', 'up')])
def test_group_binary_counts_preserve_policy_and_hide_empty_group(db, monkeypatch, policy, expected):
    source, item, group = fixture(db, monkeypatch)
    group.failure_policy = policy
    missing = Monitor(name='no result', node_id=source.id, type='ping', target='192.168.160.5', interval=60, timeout=2)
    db.add_all([missing, MonitorGroup(name='empty hidden')]); db.flush()
    db.add(MonitorGroupMember(group_id=group.id, monitor_id=missing.id, position=1)); db.commit()
    before = snapshot(db)
    payload = client_for(db).get('/monitors/groups').json()
    assert len(payload) == 1
    assert (payload[0]['status'], payload[0]['up_count'], payload[0]['down_count']) == (expected, 1, 1)
    assert snapshot(db) == before


def test_public_monitor_and_group_schema_only_advertise_binary_status():
    from app.schemas.monitor import MonitorRead, MonitorGroupRead
    assert MonitorRead.model_json_schema()['properties']['status']['enum'] == ['up', 'down']
    # V11 fixed system groups may be empty: null is absence, not a third health state.
    assert MonitorGroupRead.model_json_schema()['properties']['status']['anyOf'] == [
        {'enum': ['up', 'down'], 'type': 'string'}, {'type': 'null'}]
    from pydantic import TypeAdapter, ValidationError
    for dto in (MonitorRead, MonitorGroupRead):
        status = TypeAdapter(dto.model_fields['status'].annotation)
        assert [status.validate_python(v) for v in ('up', 'down')] == ['up', 'down']
        for invalid in ('unknown', 'pending', 'healthy', ''):
            with pytest.raises(ValidationError): status.validate_python(invalid)
        if dto is MonitorGroupRead:
            assert status.validate_python(None) is None
        else:
            with pytest.raises(ValidationError): status.validate_python(None)
