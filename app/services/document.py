from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.document import get_by_id, list_by_workspace, create, update, delete
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.models.document import Document


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
    return result


def delete_document(db: Session, doc_id: UUID) -> None:
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
    delete(db, doc)
