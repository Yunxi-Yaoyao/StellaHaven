from datetime import datetime, timedelta
from uuid import uuid4, UUID

import pytest

from app.models.document import Document


@pytest.fixture
def workspace_id(client):
    user = client.get("/auth/me").json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "回收站测试工作区"
    }).json()
    return ws["id"]


def make_doc(client, workspace_id, title="回收站测试文档"):
    return client.post("/documents/", json={
        "title": title,
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": workspace_id,
        "content": "一些内容",
    })


def test_soft_delete_hides_document(client, workspace_id):
    """删除 → 软删：GET 404，正常列表消失"""
    doc = make_doc(client, workspace_id).json()

    r = client.delete(f"/documents/{doc['id']}")
    assert r.status_code == 204

    assert client.get(f"/documents/{doc['id']}").status_code == 404
    listed = client.get(f"/documents/?workspace_id={workspace_id}").json()
    assert doc["id"] not in {d["id"] for d in listed}


def test_trash_list_shows_deleted(client, workspace_id):
    """回收站列表能看到被删的"""
    doc = make_doc(client, workspace_id, "删掉我").json()
    client.delete(f"/documents/{doc['id']}")

    trash = client.get(f"/documents/trash?workspace_id={workspace_id}").json()
    assert doc["id"] in {d["id"] for d in trash}


def test_restore_from_trash(client, workspace_id):
    """还原 → 文档回来了，能正常 GET"""
    doc = make_doc(client, workspace_id).json()
    client.delete(f"/documents/{doc['id']}")

    r = client.post(f"/documents/{doc['id']}/restore")
    assert r.status_code == 200
    body = r.json()
    assert body["doc"]["id"] == doc["id"]
    assert body["reattached"] is False
    assert body["restored"] == 1

    assert client.get(f"/documents/{doc['id']}").status_code == 200


def test_delete_trashed_purges(client, workspace_id, db_session):
    """Historical ID: repeated DELETE stays soft; explicit permanent removes it."""
    doc = make_doc(client, workspace_id).json()
    client.delete(f"/documents/{doc['id']}")   # 进回收站
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    assert doc['id'] in {d['id'] for d in client.get(f"/documents/trash?workspace_id={workspace_id}").json()}
    from sqlalchemy.orm import Session
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc['id'])).deleted_at is not None
    assert client.delete(f"/documents/{doc['id']}/permanent").status_code == 204
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc['id'])) is None
    assert client.delete(f"/documents/{doc['id']}/permanent").status_code == 204

    trash = client.get(f"/documents/trash?workspace_id={workspace_id}").json()
    assert doc["id"] not in {d["id"] for d in trash}


def test_expired_trash_readonly_until_explicit_elevated_purge(client, db_session, workspace_id):
    """GET stays read-only; explicit owner purge needs no elevation, not anonymous/foreign."""
    doc = make_doc(client, workspace_id, '保留过期回收站').json()
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    row = db_session.get(Document, UUID(doc['id']))
    row.deleted_at = datetime.now() - timedelta(days=31)
    db_session.commit(); db_session.expire_all()
    assert client.post('/auth/admin/lock').status_code == 410
    response = client.get(f'/documents/trash?workspace_id={workspace_id}')
    assert response.status_code == 200
    assert doc['id'] in {d['id'] for d in response.json()}
    assert db_session.get(Document,UUID(doc['id'])) is not None
    from sqlalchemy.orm import Session
    from fastapi.testclient import TestClient
    from app.models.user import User
    from app.models.workspace import Workspace
    from main import app
    assert client.get('/auth/security').json()['elevated'] is True
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc['id'])) is not None
        foreign = User(username='retained-'+uuid4().hex, display_name='retained')
        fresh.add(foreign); fresh.flush()
        workspace = Workspace(user_id=foreign.id, name='foreign')
        fresh.add(workspace); fresh.commit(); foreign_id = workspace.id
    with TestClient(app, headers={'Origin': 'http://testserver'}) as anonymous:
        assert anonymous.post(f'/documents/trash/empty?workspace_id={workspace_id}').status_code == 401
    assert client.post(f'/documents/trash/empty?workspace_id={foreign_id}').status_code == 404
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc['id'])) is not None
    response = client.post(f'/documents/trash/empty?workspace_id={workspace_id}')
    assert response.status_code == 200 and response.json()['purged'] == 1
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc['id'])) is None
        assert fresh.get(Workspace, foreign_id) is not None
