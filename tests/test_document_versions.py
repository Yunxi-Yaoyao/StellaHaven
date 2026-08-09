from uuid import uuid4

import pytest


@pytest.fixture
def doc_id(client):
    """建 user → workspace → document，返回 doc_id"""
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "版本测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "版本测试工作区"
    }).json()
    doc = client.post("/documents/", json={
        "title": "有版本的文档",
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws["id"],
        "content_hash": uuid4().hex,
    }).json()
    return doc["id"]


def test_create_version(client, doc_id):
    """存一个版本 → 201 + 字段正确"""
    response = client.post("/document-versions/", json={
        "doc_id": doc_id,
        "content": "# 第一版内容",
        "diff": "+# 第一版内容",
        "version_no": 1,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["doc_id"] == doc_id
    assert data["version_no"] == 1
    assert "created_at" in data


def test_get_version(client, doc_id):
    """按 id 读回版本"""
    created = client.post("/document-versions/", json={
        "doc_id": doc_id, "content": "v1", "diff": "+v1", "version_no": 1
    }).json()

    response = client.get(f"/document-versions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["content"] == "v1"


def test_list_versions_of_doc(client, doc_id):
    """列出一篇文档的版本链，按号可查"""
    client.post("/document-versions/", json={
        "doc_id": doc_id, "content": "v1", "diff": "+v1", "version_no": 1
    })
    client.post("/document-versions/", json={
        "doc_id": doc_id, "content": "v2", "diff": "+v2", "version_no": 2
    })

    response = client.get(f"/document-versions/?doc_id={doc_id}")
    assert response.status_code == 200
    version_nos = {v["version_no"] for v in response.json()}
    assert {1, 2} <= version_nos
