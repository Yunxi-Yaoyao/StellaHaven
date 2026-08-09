from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.document_version import get_by_id, list_by_document, create
from app.schemas.document_version import DocumentVersionCreate
from app.models.document_version import DocumentVersion


def get_version(db: Session, version_id: UUID) -> DocumentVersion | None:
    return get_by_id(db, version_id)


def list_versions(db: Session, doc_id: UUID) -> list[DocumentVersion]:
    return list_by_document(db, doc_id)


def create_version(db: Session, data: DocumentVersionCreate) -> DocumentVersion:
    return create(db, data)
