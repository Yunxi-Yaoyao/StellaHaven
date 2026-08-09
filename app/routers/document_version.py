from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.document_version import DocumentVersionCreate, DocumentVersionRead
from app.services.document_version import get_version, list_versions, create_version

router = APIRouter(prefix="/document-versions", tags=["document_versions"])


@router.get("/{version_id}", response_model=DocumentVersionRead)
def read_one(version_id: UUID, db: Session = Depends(get_db)):
    return get_version(db, version_id)


@router.get("/", response_model=list[DocumentVersionRead])
def read_for_doc(doc_id: UUID, db: Session = Depends(get_db)):
    return list_versions(db, doc_id)


@router.post("/", response_model=DocumentVersionRead, status_code=201)
def create_one(data: DocumentVersionCreate, db: Session = Depends(get_db)):
    return create_version(db, data)
