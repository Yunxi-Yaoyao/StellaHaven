from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.document import get_by_id, list_by_workspace, create, update, delete
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.models.document import Document

# 草稿新鲜度：超过 10 分钟没再编辑的草稿视为不存在（惰性判断，不做物理删除）
DRAFT_TTL_SECONDS = 600


def get_document(db: Session, doc_id: UUID) -> Document | None:
    return get_by_id(db, doc_id)


def list_documents(db: Session, workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20) -> list[Document]:
    return list_by_workspace(db, workspace_id, parent_id, skip, limit)


def create_document(db: Session, data: DocumentCreate) -> Document:
    return create(db, data)


def update_document(db: Session, doc_id: UUID, data: DocumentUpdate) -> Document:
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
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


def save_draft(db: Session, doc_id: UUID, content: str, device: str) -> Document | None:
    """覆写草稿槽。不追加、不留历史，永远只有最新一份。"""
    doc = get_by_id(db, doc_id)
    if doc is None:
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


def delete_document(db: Session, doc_id: UUID) -> None:
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
    delete(db, doc)
