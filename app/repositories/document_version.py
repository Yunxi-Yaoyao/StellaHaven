from uuid import UUID
from sqlalchemy.orm import Session

from app.models.document_version import DocumentVersion
from app.schemas.document_version import DocumentVersionCreate


def get_by_id(db: Session, version_id: UUID) -> DocumentVersion | None:
    return db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()


def list_by_document(db: Session, doc_id: UUID) -> list[DocumentVersion]:
    return db.query(DocumentVersion).filter(DocumentVersion.doc_id == doc_id).order_by(DocumentVersion.version_no.desc()).all()


def create(db: Session, data: DocumentVersionCreate) -> DocumentVersion:
    ver = DocumentVersion(**data.model_dump())
    db.add(ver)
    db.commit()
    db.refresh(ver)
    return ver
