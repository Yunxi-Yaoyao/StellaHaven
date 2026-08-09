from uuid import uuid4

import pytest


@pytest.fixture
def workspace_id(client):
    """建 user → 建 workspace，返回 workspace_id（documents 的 FK 需要）"""
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "文档测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "文档测试工作区"
    }).json()
    return ws["id"]


def make_doc(client, workspace_id, title="测试文档"):
    return client.post("/documents/", json={
        "title": title,
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": workspace_id,
        "content_hash": uuid4().hex,
    })


def test_create_document(client, workspace_id):
    """创建 document → 201 + 字段正确 + 默认状态 draft"""
    response = make_doc(client, workspace_id)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "测试文档"
    assert data["workspace_id"] == workspace_id
    assert data["status"] == "draft"
    assert data["is_folder"] is False
    assert "updated_at" in data  # 乐观锁的版本令牌


def test_get_document(client, workspace_id):
    """创建后能按 id 读回来"""
    created = make_doc(client, workspace_id).json()
    response = client.get(f"/documents/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_list_documents(client, workspace_id):
    """按 workspace 列出文档"""
    make_doc(client, workspace_id, "文档A")
    make_doc(client, workspace_id, "文档B")

    response = client.get(f"/documents/?workspace_id={workspace_id}")
    assert response.status_code == 200
    titles = {d["title"] for d in response.json()}
    assert {"文档A", "文档B"} <= titles


def test_update_document_ok(client, workspace_id):
    """带正确 updated_at 更新 → 200，乐观锁放行"""
    doc = make_doc(client, workspace_id).json()

    response = client.put(f"/documents/{doc['id']}", json={
        "updated_at": doc["updated_at"],
        "title": "改过的标题",
        "status": "published",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "改过的标题"
    assert data["status"] == "published"


def test_update_document_conflict(client, workspace_id):
    """拿着过期的 updated_at 更新 → 409（乐观锁拦住 stale 写）"""
    doc = make_doc(client, workspace_id).json()
    stale = doc["updated_at"]

    # 第一次更新成功，updated_at 变了
    r1 = client.put(f"/documents/{doc['id']}", json={
        "updated_at": stale, "title": "第一次改"
    })
    assert r1.status_code == 200

    # 拿旧令牌再改 → 冲突
    r2 = client.put(f"/documents/{doc['id']}", json={
        "updated_at": stale, "title": "用过期令牌改"
    })
    assert r2.status_code == 409


def test_update_document_not_found(client):
    """更新不存在的文档 → 4xx"""
    response = client.put(f"/documents/{uuid4()}", json={
        "updated_at": "2026-01-01T00:00:00", "title": "幽灵"
    })
    assert response.status_code in (404, 409)


def test_delete_document(client, workspace_id):
    """删除文档"""
    doc = make_doc(client, workspace_id).json()
    response = client.delete(f"/documents/{doc['id']}")
    assert response.status_code in (200, 204)


def test_favorite_toggle_keeps_updated_at(client, workspace_id):
    """星标切换：翻转 is_favorite，但不动 updated_at（点赞不是保存正文）"""
    doc = make_doc(client, workspace_id).json()
    assert doc["is_favorite"] is False

    r = client.post(f"/documents/{doc['id']}/favorite")
    assert r.status_code == 200
    assert r.json()["is_favorite"] is True
    assert r.json()["updated_at"] == doc["updated_at"]  # 关键：不许变

    r2 = client.post(f"/documents/{doc['id']}/favorite")
    assert r2.json()["is_favorite"] is False
