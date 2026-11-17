"""Round seven: actual HTTP + SQLite, no configured database or live probes."""
from datetime import datetime, timezone
from types import SimpleNamespace

from test_node_monitor_policy import db, node
from test_entry_monitor_groups import tables
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember


def client_for(db):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.routers.monitor import monitor_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    app = FastAPI(); app.include_router(monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    def signed(request: Request):
        request.state.auth_session = SimpleNamespace(id='v7-isolated-owner')
        return object()
    app.dependency_overrides[current_user] = signed
    app.dependency_overrides[admin_user] = signed
    return TestClient(app)


def test_standalone_post_readback_has_no_implicit_group_or_membership(db):
    n = node(db, status='online', last_seen_at=datetime.now(timezone.utc))
    client = client_for(db)
    body = dict(name='独立监控项', type='tcp', target='solo.example:443', node_id=n.id, interval=60, timeout=5)
    response = client.post('/monitors/', json=body)
    assert response.status_code == 201, response.text
    mid = response.json()['id']
    actual = next(m for m in client.get('/monitors/').json() if m['id'] == mid)
    assert {k: actual[k] for k in body} == body
    # API business result is binary; storage remains a sample-free unknown.
    assert actual['status'] == 'down' and actual['status_reason'] == 'pending'
    assert db.get(Monitor, mid).status == 'unknown' and db.get(Monitor, mid).last_check_at is None
    assert client.get('/monitors/groups').json() == []
    assert db.query(MonitorGroup).count() == db.query(MonitorGroupMember).count() == db.query(MonitorCheck).count() == 0


def test_group_mode_keeps_atomic_two_item_creation_and_receipt(db):
    n = node(db); client = client_for(db)
    body = dict(name='两项组', items=[dict(name='一', type='ping', target='one.example', node_id=n.id), dict(name='二', type='tcp', target='two.example:443', node_id=n.id)], request_key='77777777-7777-4777-8777-777777777777', failure_policy='any', rotation_seconds=0)
    invalid = body | {'items': [body['items'][0], body['items'][1] | {'node_id': 999}]}
    assert client.post('/monitors/groups', json=invalid).status_code == 400
    assert db.query(Monitor).count() == db.query(MonitorGroup).count() == 0
    response = client.post('/monitors/groups', json=body)
    assert response.status_code == 201, response.text
    group = response.json()
    assert len(group['child_ids']) == 2
    assert client.get('/monitors/groups/receipts/' + body['request_key']).json() == dict(group_id=group['id'], monitor_ids=group['child_ids'])
    assert client.post('/monitors/groups', json=body).json()['id'] == group['id']
    assert db.query(Monitor).count() == db.query(MonitorGroupMember).count() == 2
    assert db.query(MonitorGroup).count() == 1
