import importlib.util
from uuid import uuid4, UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.models import Document, Workspace
from app.models.config import AppConfig
from app.models.node import Node, NodeStatusEvent
from app.models.alert import AlertRule, AlertEvent
from app.models.task import MtrTask


def client_for(db):
    app = FastAPI()
    for name in ['notes_tools', 'unified_search', 'timeline']:
        if importlib.util.find_spec('app.routers.' + name):
            mod = importlib.import_module('app.routers.' + name)
            app.include_router(mod.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_quick_record_creates_dedicated_inbox_only_on_post(db, workspace, make_doc):
    client = client_for(db)
    r = client.post('/notes-tools/quick-record', json={'workspace_id': str(workspace.id), 'title': 'idea', 'content': 'capture'})
    assert r.status_code == 201, r.text
    first = r.json()
    r = client.post('/notes-tools/quick-record', json={'workspace_id': str(workspace.id), 'title': 'second', 'content': 'capture'})
    assert r.status_code == 201
    assert first['parent_id'] == r.json()['parent_id']
    folder = db.get(Document, UUID(first['parent_id']))
    assert folder.is_folder and folder.workspace_id == workspace.id
    assert db.query(Document).filter(Document.is_folder.is_(True)).count() == 1
    other = Workspace(id=uuid4(), name='other', user_id=uuid4()); db.add(other); db.commit()
    assert client.post('/notes-tools/quick-record', json={'workspace_id': str(other.id), 'title': 'no', 'content': ''}).status_code == 404


def test_search_scopes_notes_and_never_returns_content(db, workspace, make_doc):
    d = make_doc(draft_content='draft secret'); d.title = 'needle'; db.commit()
    other = Workspace(id=uuid4(), name='other', user_id=uuid4()); db.add(other); db.commit()
    foreign = make_doc(); foreign.title = 'needle hidden'; foreign.workspace_id = other.id; db.commit()
    r = client_for(db).get('/search', params={'q': 'needle', 'workspace_id': str(workspace.id)})
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 1
    assert r.json()['items'][0]['kind'] == 'note'
    assert 'content' not in r.text and 'secret' not in r.text and 'hidden' not in r.text
    assert client_for(db).get('/search', params={'q': 'needle', 'workspace_id': str(other.id)}).status_code == 404


def test_timeline_links_real_node_alert_task_and_note_records(db, workspace, make_doc):
    from datetime import datetime, timezone
    node = Node(id=1, name='edge', host='isolated.invalid', platform='linux', status='online')
    db.add(node); db.commit()
    now = datetime.now(timezone.utc)
    db.add(NodeStatusEvent(id=1, node_id=1, status='offline', ts=now, reason='heartbeat timeout'))
    rule = AlertRule(id=1, kind='node_offline', target='1', label='edge', link='/status/1')
    db.add(rule); db.commit()
    db.add(AlertEvent(id=1, rule_id=1, event='fired', ts=now, message='edge down'))
    db.add(MtrTask(id=1, node_id=1, target='probe.invalid', status='done', created_at=now))
    db.commit()
    d = make_doc()
    client = client_for(db)
    r = client.put(f'/notes-tools/documents/{d.id}/node', json={'node_id': 1})
    assert r.status_code == 200, r.text
    r = client.get('/timeline', params={'node_id': 1, 'workspace_id': str(workspace.id)})
    assert r.status_code == 200, r.text
    assert {item['kind'] for item in r.json()['items']} == {'node_status', 'alert', 'mtr_task', 'note_updated'}
    assert len(r.json()['items']) == 4
    assert client.get(f'/notes-tools/documents/{d.id}/node').json()['node_id'] == 1
    assert client.put(f'/notes-tools/documents/{d.id}/node', json={'node_id': 999}).status_code == 404
    assert client.get('/search', params={'q': 'heartbeat', 'workspace_id': str(workspace.id)}).json()['items'][0]['kind'] == 'node_status'
    assert client.put(f'/notes-tools/documents/{d.id}/node', json={'node_id': None}).status_code == 200
    assert client.get(f'/notes-tools/documents/{d.id}/node').json()['node_id'] is None
    assert len(client.get('/timeline', params={'node_id': 1, 'workspace_id': str(workspace.id)}).json()['items']) == 3


def test_timeline_includes_monitor_alerts_for_source_node(db, workspace):
    from datetime import datetime, timezone
    from app.models.monitor import Monitor
    db.add(Node(id=1, name='source', host='isolated.invalid', platform='linux', status='online')); db.commit()
    db.add(Monitor(id=1, name='probe', node_id=1, type='ping', target='isolated.invalid')); db.commit()
    db.add(AlertRule(id=1, kind='monitor_down', target='1', label='probe', link='/status/1')); db.commit()
    db.add(AlertEvent(id=1, rule_id=1, event='fired', ts=datetime.now(timezone.utc), message='probe down')); db.commit()
    r = client_for(db).get('/timeline', params={'node_id': 1, 'workspace_id': str(workspace.id)})
    assert r.status_code == 200
    assert [item['label'] for item in r.json()['items']] == ['probe down']


def test_stale_associations_cannot_hide_current_workspace_note(db, workspace, make_doc):
    import json
    db.add(Node(id=1, name='source', host='isolated.invalid', platform='linux', status='online')); db.commit()
    value = json.dumps({'node_id': 1})
    db.add_all([AppConfig(key='note-node:' + str(uuid4()), value=value) for _ in range(1000)]); db.commit()
    d = make_doc(); db.add(AppConfig(key='note-node:' + str(d.id), value=value)); db.commit()
    r = client_for(db).get('/timeline', params={'node_id': 1, 'workspace_id': str(workspace.id)})
    assert r.status_code == 200
    assert [item['kind'] for item in r.json()['items']] == ['note_updated']
