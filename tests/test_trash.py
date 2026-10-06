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


def test_delete_trashed_purges(client, workspace_id):
    """对回收站里的再删一次 → 物理删除，回收站也没了"""
    doc = make_doc(client, workspace_id).json()
    client.delete(f"/documents/{doc['id']}")   # 进回收站
    client.delete(f"/documents/{doc['id']}")   # 物理删

    trash = client.get(f"/documents/trash?workspace_id={workspace_id}").json()
    assert doc["id"] not in {d["id"] for d in trash}


def test_expired_trash_readonly_until_explicit_elevated_purge(client, db_session, workspace_id):
    """GET is read-only even after retention; only explicit elevated purge deletes."""
    from tests.conftest import ADMIN_PASSWORD
    doc = make_doc(client, workspace_id, '保留过期回收站').json()
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    row = db_session.get(Document, UUID(doc['id']))
    row.deleted_at = datetime.now() - timedelta(days=31)
    db_session.commit(); db_session.expire_all()
    assert client.post('/auth/admin/lock').status_code == 200
    response = client.get(f'/documents/trash?workspace_id={workspace_id}')
    assert response.status_code == 200
    assert doc['id'] in {d['id'] for d in response.json()}
    assert db_session.get(Document,UUID(doc['id'])) is not None
    assert client.post(f'/documents/trash/empty?workspace_id={workspace_id}').status_code == 403
    assert db_session.get(Document,UUID(doc['id'])) is not None
    assert client.post('/auth/admin/unlock',json={'password':ADMIN_PASSWORD}).status_code == 200
    assert client.post(f'/documents/trash/empty?workspace_id={workspace_id}').json()['purged'] == 1
    assert db_session.get(Document,UUID(doc['id'])) is None
