from uuid import UUID
from sqlalchemy.orm import Session

from app.models.document_link import DocumentLink
from app.schemas.document_link import DocumentLinkCreate
from app.services.notes_lifecycle import rollback_on_error


def _lock_pair(db, source_id, target_id):
    from fastapi import HTTPException
    from app.models.document import Document
    from app.services.notes_lifecycle import lock_graph, lock_workspace
    lock_graph(db)
    ids = {source_id, target_id}
    workspaces = {row[0] for row in db.query(Document.workspace_id).filter(Document.id.in_(ids)).all()}
    for workspace_id in sorted(workspaces, key=str):
        lock_workspace(db, workspace_id, graph_locked=True)
    docs = db.query(Document).filter(Document.id.in_(ids)).order_by(Document.id).populate_existing().with_for_update().all()
    if len(docs) != len(ids) or len(workspaces) != 1 or any(doc.deleted_at is not None for doc in docs):
        raise HTTPException(404, '关联文档不存在')


@rollback_on_error
def create(db: Session, data: DocumentLinkCreate, *, commit: bool = True) -> DocumentLink:
    if commit:
        _lock_pair(db, data.source_id, data.target_id)
    existing = db.get(DocumentLink, (data.source_id, data.target_id))
    if existing is not None:
        if existing.link_type != data.link_type:
            from fastapi import HTTPException
            raise HTTPException(409, {'code': 'document_link_type_conflict'})
        if commit:
            db.commit()
        return existing
    link = DocumentLink(**data.model_dump())
    db.add(link)
    if commit:
        db.commit()
        db.refresh(link)
    else:
        db.flush()
    return link


@rollback_on_error
def remove(db: Session, source_id: UUID, target_id: UUID, *, commit: bool = True) -> None:
    if commit:
        _lock_pair(db, source_id, target_id)
    db.query(DocumentLink).filter(
        DocumentLink.source_id == source_id,
        DocumentLink.target_id == target_id
    ).delete()
    if commit:
        db.commit()


def get_links_for_doc(db: Session, doc_id: UUID) -> list[DocumentLink]:
    return db.query(DocumentLink).filter(
        (DocumentLink.source_id == doc_id) | (DocumentLink.target_id == doc_id)
    ).all()
