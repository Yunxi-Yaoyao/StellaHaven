from uuid import UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.doc_tag import DocTag
from app.models.document import Document
from app.models.workspace import Workspace
from app.models.tag import Tag
from app.schemas.doc_tag import DocTagCreate


def add(db: Session, data: DocTagCreate) -> DocTag:
    # The composite primary key arbitrates concurrent retries in the database.
    # Limit conflict suppression to that key; other integrity errors must surface.
    values = data.model_dump()
    db.execute(insert(DocTag).values(**values).on_conflict_do_nothing(
        index_elements=[DocTag.doc_id, DocTag.tag_id],
    ))
    # Caller owns graph/tree locks and the single commit/rollback boundary.
    return DocTag(**values)


def remove(db: Session, doc_id: UUID, tag_id: UUID) -> bool:
    removed = db.query(DocTag).filter(DocTag.doc_id == doc_id, DocTag.tag_id == tag_id).delete()
    return bool(removed)


def get_tags_for_doc(db: Session, doc_id: UUID | None, user_id: UUID) -> list[DocTag]:
    query = (db.query(DocTag)
             .join(Document, DocTag.doc_id == Document.id)
             .join(Workspace, Document.workspace_id == Workspace.id)
             .join(Tag, DocTag.tag_id == Tag.id)
             .filter(Workspace.user_id == user_id, Tag.user_id == user_id))
    if doc_id is not None:
        query = query.filter(DocTag.doc_id == doc_id)
    return query.all()
