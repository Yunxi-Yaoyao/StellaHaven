from uuid import UUID
from sqlalchemy.orm import Session

from app.models.document_link import DocumentLink
from app.schemas.document_link import DocumentLinkCreate


def create(db: Session, data: DocumentLinkCreate) -> DocumentLink:
    link = DocumentLink(**data.model_dump())
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def remove(db: Session, source_id: UUID, target_id: UUID) -> None:
    db.query(DocumentLink).filter(
        DocumentLink.source_id == source_id,
        DocumentLink.target_id == target_id
    ).delete()
    db.commit()


def get_links_for_doc(db: Session, doc_id: UUID) -> list[DocumentLink]:
    return db.query(DocumentLink).filter(
        (DocumentLink.source_id == doc_id) | (DocumentLink.target_id == doc_id)
    ).all()
