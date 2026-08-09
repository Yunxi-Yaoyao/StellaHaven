from hashlib import sha256
from uuid import uuid4

import pytest


@pytest.fixture
def workspace_id(client):
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "正文测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "正文测试工作区"
    }).json()
    return ws["id"]


def make_doc(client, workspace_id, **kw):
    payload = {
        "title": "正文测试文档",
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": workspace_id,
    }
    payload.update(kw)
    return client.post("/documents/", json=payload)


def test_create_with_content(client, workspace_id):
    """带正文创建 → 服务端自动算 sha256，不用前端传 hash"""
    response = make_doc(client, workspace_id, content="# 你好 Stella")
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "# 你好 Stella"
    assert data["content_hash"] == sha256("# 你好 Stella".encode()).hexdigest()


def test_create_without_content(client, workspace_id):
    """不带正文 → hash 是空串的 sha256，不为 NULL"""
    response = make_doc(client, workspace_id)
    assert response.status_code == 201
    data = response.json()
    assert data["content"] is None
    assert data["content_hash"] == sha256("".encode()).hexdigest()


def test_update_content_rehashes(client, workspace_id):
    """更新正文 → hash 跟着变"""
    doc = make_doc(client, workspace_id, content="旧内容").json()
    old_hash = doc["content_hash"]

    r = client.put(f"/documents/{doc['id']}", json={
        "updated_at": doc["updated_at"],
        "content": "新内容覆盖了",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "新内容覆盖了"
    assert data["content_hash"] == sha256("新内容覆盖了".encode()).hexdigest()
    assert data["content_hash"] != old_hash


def test_update_metadata_keeps_hash(client, workspace_id):
    """只改标题不动正文 → hash 不变"""
    doc = make_doc(client, workspace_id, content="正文不动").json()

    r = client.put(f"/documents/{doc['id']}", json={
        "updated_at": doc["updated_at"],
        "title": "只改标题",
    })
    assert r.status_code == 200
    assert r.json()["content_hash"] == doc["content_hash"]
