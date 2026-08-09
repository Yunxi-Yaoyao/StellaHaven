from uuid import UUID
from sqlalchemy.orm import Session

from app.models.doc_tag import DocTag
from app.schemas.doc_tag import DocTagCreate


def add(db: Session, data: DocTagCreate) -> DocTag:
    dt = DocTag(**data.model_dump())
    db.add(dt)
    db.commit()
    db.refresh(dt)
    return dt


def remove(db: Session, doc_id: UUID, tag_id: UUID) -> None:
    db.query(DocTag).filter(DocTag.doc_id == doc_id, DocTag.tag_id == tag_id).delete()
    db.commit()


def get_tags_for_doc(db: Session, doc_id: UUID) -> list[DocTag]:
    return db.query(DocTag).filter(DocTag.doc_id == doc_id).all()
