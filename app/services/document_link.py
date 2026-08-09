from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.document_link import create, remove, get_links_for_doc
from app.schemas.document_link import DocumentLinkCreate
from app.models.document_link import DocumentLink


def create_link(db: Session, data: DocumentLinkCreate) -> DocumentLink:
    return create(db, data)


def remove_link(db: Session, source_id: UUID, target_id: UUID) -> None:
    remove(db, source_id, target_id)


def get_links(db: Session, doc_id: UUID) -> list[DocumentLink]:
    return get_links_for_doc(db, doc_id)
