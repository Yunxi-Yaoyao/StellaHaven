"""附件上传/读取/引用清理"""
import io
from uuid import uuid4

import pytest


@pytest.fixture
def doc_id(client):
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "附件测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "附件测试工作区"
    }).json()
    doc = client.post("/documents/", json={
        "title": "带图文档",
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws["id"],
        "content": "",
    }).json()
    return doc["id"]


# 一个 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


def upload(client, doc_id):
    return client.post(
        f"/attachments/{doc_id}",
        files={"file": ("test.png", io.BytesIO(PNG), "image/png")},
    )


def test_upload_and_serve(client, doc_id):
    """上传 → 返回引用路径 → GET 能读回同样的字节"""
    r = upload(client, doc_id)
    assert r.status_code == 200
    url = r.json()["url"]

    g = client.get(url)
    assert g.status_code == 200
    assert g.content == PNG
    assert g.headers["content-type"] == "image/png"


def test_unreferenced_attachment_deleted_on_save(client, doc_id):
    """老婆的规则：保存时正文不再引用的附件 → 连文件带记录删"""
    url = upload(client, doc_id).json()["url"]

    # 保存一次带引用的正文 → 附件活着
    doc = client.get(f"/documents/{doc_id}").json()
    client.put(f"/documents/{doc_id}", json={
        "updated_at": doc["updated_at"],
        "content": f"看图：![]({url})",
    })
    assert client.get(url).status_code == 200

    # 保存一次去掉引用的正文 → 附件被清
    doc2 = client.get(f"/documents/{doc_id}").json()
    client.put(f"/documents/{doc_id}", json={
        "updated_at": doc2["updated_at"],
        "content": "没图了",
    })
    assert client.get(url).status_code == 404


def test_attachment_follows_doc_physical_delete(client, doc_id):
    """彻底删文档 → 附件跟着没"""
    url = upload(client, doc_id).json()["url"]

    client.delete(f"/documents/{doc_id}")  # 进回收站
    assert client.get(url).status_code == 200  # 回收站阶段还在

    client.delete(f"/documents/{doc_id}")  # 物理删
    assert client.get(url).status_code == 404


def test_non_image_file_upload(client, doc_id):
    """非图片文件（任意附件）也能上传下载"""
    r = client.post(
        f"/attachments/{doc_id}",
        files={"file": ("笔记导出.txt", io.BytesIO("你好 Stella".encode()), "text/plain")},
    )
    assert r.status_code == 200
    url = r.json()["url"]
    g = client.get(url)
    assert g.status_code == 200
    assert g.content.decode() == "你好 Stella"
