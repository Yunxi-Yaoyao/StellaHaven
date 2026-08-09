from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update, or_

from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentUpdate


def get_by_id(db: Session, doc_id: UUID) -> Document | None:
    return db.query(Document).filter(Document.id == doc_id).first()


def list_by_workspace(db: Session, workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20) -> list[Document]:
    """正常列表：不含回收站里的"""
    q = db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.deleted_at.is_(None),
    )
    if parent_id is not None:
        q = q.filter(Document.parent_id == parent_id)
    return q.offset(skip).limit(limit).all()


def list_trash(db: Session, workspace_id: UUID) -> list[Document]:
    """回收站列表：只有被软删的，最近删的排前面"""
    return db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.deleted_at.isnot(None),
    ).order_by(Document.deleted_at.desc()).all()


def purge_expired_trash(db: Session, retention_days: int) -> int:
    """物理清除过期回收站内容，返回清了几篇（惰性清理：被调用时才干活）"""
    cutoff = datetime.now() - timedelta(days=retention_days)
    count = db.query(Document).filter(Document.deleted_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return count


def search(db: Session, workspace_id: UUID, keyword: str, limit: int = 50) -> list[Document]:
    """全文搜索：标题 + 正文，ILIKE 子串匹配（pg_trgm GIN 索引加速），不含回收站"""
    like = f"%{keyword}%"
    return db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.deleted_at.is_(None),
        or_(Document.title.ilike(like), Document.content.ilike(like)),
    ).order_by(Document.updated_at.desc()).limit(limit).all()


def create(db: Session, data: DocumentCreate) -> Document:
    doc = Document(**data.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def update(db: Session, doc_id: UUID, data: DocumentUpdate) -> Document | None:
    """乐观锁更新：WHERE updated_at = 前端传的旧值，中间有人改过就拒"""
    result = db.execute(
        sql_update(Document)
        .where(Document.id == doc_id, Document.updated_at == data.updated_at)
        .values(**data.model_dump(exclude={"updated_at"}, exclude_unset=True))
    )
    db.commit()
    if result.rowcount == 0:
        return None  # 冲突
    return get_by_id(db, doc_id)


def delete(db: Session, doc: Document) -> None:
    db.delete(doc)
    db.commit()
