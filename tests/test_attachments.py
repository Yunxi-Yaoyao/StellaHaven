"""附件上传/读取/引用清理"""
import io
from uuid import uuid4

import pytest


@pytest.fixture
def doc_id(client):
    user = client.get("/auth/me").json()
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


def test_unreferenced_attachment_deleted_on_save(client, doc_id, db_session, tmp_path, monkeypatch):
    """Retain the original case ID as the explicit file-backend regression."""
    _version_protected_bytes(client, doc_id, db_session, tmp_path, monkeypatch, 'file')


@pytest.mark.parametrize('mode', ['file', 'postgres'])
def test_version_protected_attachment_storage_modes(client, doc_id, db_session, tmp_path, monkeypatch, mode):
    _version_protected_bytes(client, doc_id, db_session, tmp_path, monkeypatch, mode)


def _version_protected_bytes(client, doc_id, db_session, tmp_path, monkeypatch, mode):
    """Removing a current reference keeps version-referenced physical bytes."""
    from app.routers import attachment as storage
    monkeypatch.setenv('STELLA_BLOB_STORAGE', mode)
    monkeypatch.setattr(storage, 'STORAGE', tmp_path)
    response = upload(client, doc_id)
    assert response.status_code == 200
    url = response.json()["url"]

    # 保存一次带引用的正文 → 附件活着
    doc = client.get(f"/documents/{doc_id}").json()
    saved = client.put(f"/documents/{doc_id}", json={
        "updated_at": doc["updated_at"],
        "content": f"看图：![]({url})",
    })
    assert saved.status_code == 200, saved.text
    assert client.get(url).status_code == 200

    # Removing the current reference must not break retained historical versions.
    doc2 = client.get(f"/documents/{doc_id}").json()
    saved = client.put(f"/documents/{doc_id}", json={
        "updated_at": doc2["updated_at"],
        "content": "没图了",
    })
    assert saved.status_code == 200, saved.text
    assert client.get(f"/documents/{doc_id}").json()['content'] == '没图了'
    assert client.get(url).status_code == 200
    from sqlalchemy.orm import Session
    from uuid import UUID
    from app.models.document_version import DocumentVersion
    from app.models.attachment import Attachment
    from app.models.blob import BlobObject
    assert client.get(url).content == PNG
    with Session(db_session.get_bind()) as fresh:
        assert any(url in (v.content or '') for v in fresh.query(DocumentVersion).filter_by(doc_id=UUID(doc_id)))
        attachment = fresh.query(Attachment).filter_by(doc_id=UUID(doc_id)).one()
        key = 'attachments/' + str(attachment.id)
        if mode == 'postgres':
            from app.services import blob_store
            assert fresh.get(BlobObject, key) is not None
            assert b''.join(blob_store.read_range(fresh, key, 0, len(PNG))) == PNG
            assert not (tmp_path / str(attachment.id)).exists()
        else:
            assert (tmp_path / str(attachment.id)).read_bytes() == PNG
            assert fresh.get(BlobObject, key) is None


def test_attachment_follows_doc_physical_delete(client, doc_id, db_session):
    """彻底删文档 → 附件跟着没"""
    url = upload(client, doc_id).json()["url"]

    client.delete(f"/documents/{doc_id}")  # 进回收站
    assert client.get(url).status_code == 200  # 回收站阶段还在

    assert client.delete(f"/documents/{doc_id}").status_code == 204  # soft retry
    assert client.get(url).content == PNG
    from sqlalchemy.orm import Session
    from uuid import UUID
    from app.models.document import Document
    from app.models.attachment import Attachment
    from app.models.blob import BlobObject
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc_id)).deleted_at is not None
        ident = fresh.query(Attachment).filter_by(doc_id=UUID(doc_id)).one().id
    assert client.delete(f"/documents/{doc_id}/permanent").status_code == 204
    assert client.get(url).status_code == 404
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(Document, UUID(doc_id)) is None
        assert fresh.get(Attachment, ident) is None
        assert fresh.get(BlobObject, 'attachments/' + str(ident)) is None
    assert client.delete(f"/documents/{doc_id}/permanent").status_code == 204


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
