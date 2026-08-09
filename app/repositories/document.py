from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update

from app.models.document import Document
from app.schemas.document import DocumentCreate, DocumentUpdate


def get_by_id(db: Session, doc_id: UUID) -> Document | None:
    return db.query(Document).filter(Document.id == doc_id).first()


def list_by_workspace(db: Session, workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20) -> list[Document]:
    q = db.query(Document).filter(Document.workspace_id == workspace_id)
    if parent_id is not None:
        q = q.filter(Document.parent_id == parent_id)
    return q.offset(skip).limit(limit).all()


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
