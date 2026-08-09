from uuid import uuid4

import pytest


@pytest.fixture
def two_docs(client):
    """建 user → workspace → 两篇文档，返回 (source_id, target_id)"""
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "链接测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "链接测试工作区"
    }).json()

    def doc(title):
        return client.post("/documents/", json={
            "title": title,
            "file_path": f"/notes/{uuid4().hex[:8]}.md",
            "workspace_id": ws["id"],
            "content_hash": uuid4().hex,
        }).json()

    return doc("来源文档")["id"], doc("目标文档")["id"]


def test_create_link(client, two_docs):
    """建双链 → 201 + 默认 link_type=ref"""
    source_id, target_id = two_docs
    response = client.post("/document-links/", json={
        "source_id": source_id, "target_id": target_id
    })
    assert response.status_code == 201
    data = response.json()
    assert data["source_id"] == source_id
    assert data["target_id"] == target_id
    assert data["link_type"] == "ref"


def test_create_link_custom_type(client, two_docs):
    """自定义 link_type"""
    source_id, target_id = two_docs
    response = client.post("/document-links/", json={
        "source_id": source_id, "target_id": target_id, "link_type": "embed"
    })
    assert response.status_code == 201
    assert response.json()["link_type"] == "embed"


def test_list_links(client, two_docs):
    """查出文档的出链"""
    source_id, target_id = two_docs
    client.post("/document-links/", json={
        "source_id": source_id, "target_id": target_id
    })

    response = client.get(f"/document-links/?doc_id={source_id}")
    assert response.status_code == 200
    targets = {r["target_id"] for r in response.json()}
    assert target_id in targets


def test_remove_link(client, two_docs):
    """删链接 → 204，再查就没了"""
    source_id, target_id = two_docs
    client.post("/document-links/", json={
        "source_id": source_id, "target_id": target_id
    })

    response = client.delete(
        f"/document-links/?source_id={source_id}&target_id={target_id}"
    )
    assert response.status_code == 204

    remaining = client.get(f"/document-links/?doc_id={source_id}").json()
    assert target_id not in {r["target_id"] for r in remaining}
