from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.doc_tag import add, remove, get_tags_for_doc
from app.schemas.doc_tag import DocTagCreate
from app.models.doc_tag import DocTag
from app.models.tag import Tag
from app.models.workspace import Workspace
from app.services.notes_lifecycle import lock_document, rollback_on_error
from fastapi import HTTPException


def _lock_targets(db, doc_id, tag_id, user_id):
    # Never lock tag/relationship rows before the shared reference graph.
    doc = lock_document(db, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(404, '文档不存在')
    ws = db.query(Workspace).filter(Workspace.id == doc.workspace_id).populate_existing().first()
    if ws is None or ws.user_id != user_id:
        raise HTTPException(404, '文档不存在')
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user_id).populate_existing().with_for_update().first()
    if tag is None:
        raise HTTPException(404, '标签不存在')


@rollback_on_error
def add_tag(db: Session, data: DocTagCreate, *, user_id: UUID) -> DocTag:
    _lock_targets(db, data.doc_id, data.tag_id, user_id)
    result = add(db, data)
    db.commit()
    return result


@rollback_on_error
def remove_tag(db: Session, doc_id: UUID, tag_id: UUID, *, user_id: UUID) -> None:
    _lock_targets(db, doc_id, tag_id, user_id)
    from app.services.tag import purge_orphan_tags
    # No relationship means no permission to collect an unrelated unused tag.
    if remove(db, doc_id, tag_id):
        purge_orphan_tags(db, [tag_id], owner_ids=[user_id])
    db.commit()


def get_tags(db: Session, doc_id: UUID | None, user_id: UUID) -> list[DocTag]:
    return get_tags_for_doc(db, doc_id, user_id)
