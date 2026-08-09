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
