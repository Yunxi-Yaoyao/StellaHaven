from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update, or_

from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentUpdate


def get_by_id(db: Session, doc_id: UUID) -> Document | None:
    return db.query(Document).filter(Document.id == doc_id).first()


def children_of(db: Session, doc_id: UUID, include_deleted: bool = False) -> list[Document]:
    q = db.query(Document).filter(Document.parent_id == doc_id)
    if not include_deleted:
        q = q.filter(Document.deleted_at.is_(None))
    return q.all()


def descendants_of(db: Session, doc_id: UUID, only_deleted: bool = False) -> list[Document]:
    """BFS 收集所有后代（不含自己）。only_deleted=True 用于级联还原"""
    result = []
    queue = [doc_id]
    while queue:
        cur = queue.pop(0)
        q = db.query(Document).filter(Document.parent_id == cur)
        if only_deleted:
            q = q.filter(Document.deleted_at.isnot(None))
        kids = q.all()
        result.extend(kids)
        queue.extend(k.id for k in kids)
    return result


def list_recent(db: Session, workspace_id: UUID, limit: int = 8) -> list[Document]:
    """最近查看：按 last_viewed_at 倒序，没看过的不要"""
    return db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.deleted_at.is_(None),
        Document.last_viewed_at.isnot(None),
    ).order_by(Document.last_viewed_at.desc()).limit(limit).all()


def list_by_workspace(db: Session, workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20) -> list[Document]:
    """正常列表：不含回收站里的"""
    q = db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.deleted_at.is_(None),
    )
    if parent_id is not None:
        q = q.filter(Document.parent_id == parent_id)
    # 排序是硬要求：分页（offset/limit）下无 ORDER BY 时 PG 返回顺序不定，
    # 前端分页拉全量会漏/重文档（8.26 limit=200 截掉 v3 文件夹事故的根因之一）
    return q.order_by(Document.created_at, Document.id).offset(skip).limit(limit).all()


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
    """乐观锁更新：WHERE updated_at = 前端传的旧值，中间有人改过就拒。
    updated_at 由这里显式推进（不用 onupdate——草稿同步不该动它）"""
    result = db.execute(
        sql_update(Document)
        .where(Document.id == doc_id, Document.updated_at == data.updated_at)
        .values(
            **data.model_dump(exclude={"updated_at"}, exclude_unset=True),
            updated_at=datetime.now(),
        )
    )
    db.commit()
    if result.rowcount == 0:
        return None  # 冲突
    return get_by_id(db, doc_id)


def delete(db: Session, doc: Document) -> None:
    db.delete(doc)
    db.commit()
