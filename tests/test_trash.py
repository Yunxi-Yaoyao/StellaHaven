from datetime import datetime, timedelta
from uuid import uuid4, UUID

import pytest

from app.models.document import Document


@pytest.fixture
def workspace_id(client):
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "回收站测试"
    }).json()
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


def test_expired_trash_lazy_purged(client, db_session, workspace_id):
    """超过 30 天的回收站内容：看回收站时被顺手物理清掉（惰性清理）"""
    doc = make_doc(client, workspace_id, "过期垃圾").json()
    client.delete(f"/documents/{doc['id']}")

    # 手动把删除时间改成 31 天前
    row = db_session.get(Document, UUID(doc["id"]))
    row.deleted_at = datetime.now() - timedelta(days=31)
    db_session.commit()
    db_session.expire_all()

    # 访问回收站 → 触发惰性清理
    trash = client.get(f"/documents/trash?workspace_id={workspace_id}").json()
    assert doc["id"] not in {d["id"] for d in trash}

    # 物理上也真没了
    assert db_session.get(Document, UUID(doc["id"])) is None
