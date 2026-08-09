import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.models.document import Document


@pytest.fixture
def doc_id(client):
    """建 user → workspace → document，返回 doc_id"""
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "草稿测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "草稿测试工作区"
    }).json()
    doc = client.post("/documents/", json={
        "title": "有草稿的文档",
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws["id"],
        "content_hash": uuid4().hex,
    }).json()
    return doc["id"]


def send_draft(client, doc_id, content, device="苏菲"):
    """模拟前端 debounce 后通过 WS 推草稿"""
    with client.websocket_connect(f"/ws/{doc_id}?device={device}") as ws:
        ws.send_text(json.dumps({"type": "draft", "content": content}))


def test_ws_draft_sync(client, db_session, doc_id):
    """WS 推草稿 → 草稿槽写入 → GET 文档带 has_draft + 设备名"""
    send_draft(client, doc_id, "还没写完的半句话", device="苏菲")

    db_session.expire_all()  # 草稿是另一条 session 写的，强制重读
    doc = client.get(f"/documents/{doc_id}").json()
    assert doc["has_draft"] is True
    assert doc["draft_device"] == "苏菲"
    assert doc["draft_updated_at"] is not None


def test_draft_slot_overwrite(client, db_session, doc_id):
    """槽位覆写：连推两份草稿，只留最新一份"""
    send_draft(client, doc_id, "第一版草稿")
    send_draft(client, doc_id, "覆写后的草稿")

    db_session.expire_all()
    draft = client.get(f"/documents/{doc_id}/draft").json()
    assert draft["content"] == "覆写后的草稿"


def test_read_draft_content(client, db_session, doc_id):
    """查看草稿端点返回内容 + 时间 + 设备"""
    send_draft(client, doc_id, "给老婆看的草稿", device="台式机")

    db_session.expire_all()
    response = client.get(f"/documents/{doc_id}/draft")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "给老婆看的草稿"
    assert data["device"] == "台式机"


def test_stale_draft_hidden(client, db_session, doc_id):
    """超过 10 分钟没动的草稿 → 惰性隐藏：has_draft=False，读草稿 404"""
    send_draft(client, doc_id, "一份会过期的草稿")

    # 手动把草稿时间戳改成 11 分钟前
    doc = db_session.get(Document, uuid4().__class__(doc_id))
    doc.draft_updated_at = datetime.now() - timedelta(minutes=11)
    db_session.commit()
    db_session.expire_all()

    doc_json = client.get(f"/documents/{doc_id}").json()
    assert doc_json["has_draft"] is False

    response = client.get(f"/documents/{doc_id}/draft")
    assert response.status_code == 404


def test_manual_save_clears_draft(client, db_session, doc_id):
    """手动保存成功 → 草稿槽清空"""
    send_draft(client, doc_id, "马上要被保存的草稿")

    db_session.expire_all()
    doc = client.get(f"/documents/{doc_id}").json()
    assert doc["has_draft"] is True

    # 手动保存（乐观锁：带当前 updated_at）
    r = client.put(f"/documents/{doc_id}", json={
        "updated_at": doc["updated_at"],
        "title": "保存后的标题",
    })
    assert r.status_code == 200

    db_session.expire_all()
    doc2 = client.get(f"/documents/{doc_id}").json()
    assert doc2["has_draft"] is False
    assert doc2["draft_updated_at"] is None


def test_draft_no_doc(client):
    """给不存在的文档推草稿 → 不炸，安静忽略"""
    send_draft(client, uuid4(), "幽灵草稿")  # 不断言异常，只要不 500
