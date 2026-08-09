from datetime import datetime
from hashlib import sha256
from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.document import (
    get_by_id, list_by_workspace, list_trash, purge_expired_trash, search,
    create, update, delete,
)
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.models.document import Document

# 草稿新鲜度：超过 10 分钟没再编辑的草稿视为不存在（惰性判断，不做物理删除）
DRAFT_TTL_SECONDS = 600

# 回收站保留期：软删超过 30 天的，下次有人看回收站时物理清除（惰性清理）
TRASH_RETENTION_DAYS = 30


def _hash_content(content: str) -> str:
    return sha256(content.encode()).hexdigest()


def get_document(db: Session, doc_id: UUID) -> Document | None:
    return get_by_id(db, doc_id)


def list_documents(db: Session, workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20) -> list[Document]:
    return list_by_workspace(db, workspace_id, parent_id, skip, limit)


def create_document(db: Session, data: DocumentCreate) -> Document:
    # 服务端权威算 hash：有正文算正文的，没正文用调用方给的，都没有算空串的
    if data.content is not None:
        data.content_hash = _hash_content(data.content)
    elif not data.content_hash:
        data.content_hash = _hash_content("")
    return create(db, data)


def update_document(db: Session, doc_id: UUID, data: DocumentUpdate) -> Document:
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
    # 正文变了 → 服务端重算 hash，不信前端算的
    if data.content is not None:
        data.content_hash = _hash_content(data.content)
    result = update(db, doc_id, data)
    if result is None:
        raise ValueError("Conflict")
    # 手动保存成功 → 草稿槽清空（草稿已被 promote 成正文）
    result.draft_content = None
    result.draft_updated_at = None
    result.draft_device = None
    db.commit()
    db.refresh(result)
    return result


def delete_document(db: Session, doc_id: UUID) -> str:
    """两级删除：正常文档 → 软删进回收站；已在回收站的 → 物理删除"""
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
    if doc.deleted_at is None:
        doc.deleted_at = datetime.now()
        db.commit()
        return "trashed"
    delete(db, doc)
    return "purged"


def restore_document(db: Session, doc_id: UUID) -> Document:
    doc = get_by_id(db, doc_id)
    if doc is None or doc.deleted_at is None:
        raise ValueError("Document not found in trash")
    doc.deleted_at = None
    db.commit()
    db.refresh(doc)
    return doc


def list_trash_documents(db: Session, workspace_id: UUID) -> list[Document]:
    """看回收站 = 惰性清理时机：先顺手清掉过期的，再返回剩下的"""
    purge_expired_trash(db, TRASH_RETENTION_DAYS)
    return list_trash(db, workspace_id)


def search_documents(db: Session, workspace_id: UUID, keyword: str, limit: int = 50) -> list[Document]:
    return search(db, workspace_id, keyword, limit)


def save_draft(db: Session, doc_id: UUID, content: str, device: str) -> Document | None:
    """覆写草稿槽。不追加、不留历史，永远只有最新一份。"""
    doc = get_by_id(db, doc_id)
    if doc is None:
        db.rollback()  # ⚠️ 必须显式收尾：SELECT 会占着事务/连接，不 rollback 连接就泄漏（WS 长连接场景池子会被榨干）
        return None
    doc.draft_content = content
    doc.draft_updated_at = datetime.now()
    doc.draft_device = device
    db.commit()
    return doc


def is_draft_fresh(doc: Document) -> bool:
    """10 分钟内有过草稿同步才算「有一份未保存草稿」"""
    if doc.draft_updated_at is None:
        return False
    return (datetime.now() - doc.draft_updated_at).total_seconds() < DRAFT_TTL_SECONDS


def get_fresh_draft(db: Session, doc_id: UUID) -> Document | None:
    """取草稿：过期的当不存在（惰性隐藏，不删数据）"""
    doc = get_by_id(db, doc_id)
    if doc is None or not is_draft_fresh(doc):
        return None
    return doc
