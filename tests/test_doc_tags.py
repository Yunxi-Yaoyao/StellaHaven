from uuid import uuid4

import pytest


@pytest.fixture
def doc_and_tag(client):
    """建 user → workspace → document + tag，返回 (doc_id, tag_id)"""
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "标签测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "标签测试工作区"
    }).json()
    doc = client.post("/documents/", json={
        "title": "被打标签的文档",
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws["id"],
        "content_hash": uuid4().hex,
    }).json()
    tag = client.post("/tags/", json={
        "name": f"tag_{uuid4().hex[:8]}"
    }).json()
    return doc["id"], tag["id"]


def test_add_tag_to_doc(client, doc_and_tag):
    """给文档打标签 → 201 + 复合主键正确"""
    doc_id, tag_id = doc_and_tag
    response = client.post("/doc-tags/", json={"doc_id": doc_id, "tag_id": tag_id})
    assert response.status_code == 201
    data = response.json()
    assert data["doc_id"] == doc_id
    assert data["tag_id"] == tag_id


def test_list_tags_of_doc(client, doc_and_tag):
    """查出文档的所有标签"""
    doc_id, tag_id = doc_and_tag
    client.post("/doc-tags/", json={"doc_id": doc_id, "tag_id": tag_id})

    response = client.get(f"/doc-tags/?doc_id={doc_id}")
    assert response.status_code == 200
    tag_ids = {r["tag_id"] for r in response.json()}
    assert tag_id in tag_ids


def test_remove_tag_from_doc(client, doc_and_tag):
    """摘掉标签 → 204，再查就没了"""
    doc_id, tag_id = doc_and_tag
    client.post("/doc-tags/", json={"doc_id": doc_id, "tag_id": tag_id})

    response = client.delete(f"/doc-tags/?doc_id={doc_id}&tag_id={tag_id}")
    assert response.status_code == 204

    remaining = client.get(f"/doc-tags/?doc_id={doc_id}").json()
    assert tag_id not in {r["tag_id"] for r in remaining}


def test_remove_tag_purges_orphan(client, doc_and_tag):
    """摘掉最后一个引用 → 标签本体也被自动删掉"""
    doc_id, tag_id = doc_and_tag
    client.post("/doc-tags/", json={"doc_id": doc_id, "tag_id": tag_id})

    # 摘掉后，这标签没有任何文档引用了 → 应该连本体一起没
    client.delete(f"/doc-tags/?doc_id={doc_id}&tag_id={tag_id}")

    assert client.get(f"/tags/{tag_id}").status_code == 404


def test_delete_doc_purges_orphan_tags(client):
    """删文档 → 它独占的标签本体被清掉；共享的标签保留"""
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "删档测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "删档工作区"
    }).json()

    # 两个文档 + 两个标签：独享标签 + 共享标签
    a = client.post("/documents/", json={
        "title": "文档A", "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws["id"], "content_hash": uuid4().hex,
    }).json()
    b = client.post("/documents/", json={
        "title": "文档B", "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws["id"], "content_hash": uuid4().hex,
    }).json()
    only_a = client.post("/tags/", json={"name": f"only_a_{uuid4().hex[:8]}"}).json()
    shared = client.post("/tags/", json={"name": f"shared_{uuid4().hex[:8]}"}).json()

    client.post("/doc-tags/", json={"doc_id": a["id"], "tag_id": only_a["id"]})
    client.post("/doc-tags/", json={"doc_id": a["id"], "tag_id": shared["id"]})
    client.post("/doc-tags/", json={"doc_id": b["id"], "tag_id": shared["id"]})

    # 删 A（软删），再清空回收站（触发物理删除 + 孤儿清理）
    client.delete(f"/documents/{a['id']}?cascade=true")
    client.post(f"/documents/trash/empty?workspace_id={ws['id']}")

    # A 独占的标签没了，共享的还在
    assert client.get(f"/tags/{only_a['id']}").status_code == 404
    assert client.get(f"/tags/{shared['id']}").status_code == 200
