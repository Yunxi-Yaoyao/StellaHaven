from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.document_version import DocumentVersionCreate, DocumentVersionRead
from app.services.document_version import get_version, list_versions, create_version
from app.routers.auth import current_user, require_ws_owner, require_doc_owner

router = APIRouter(dependencies=[Depends(current_user)], prefix="/document-versions", tags=["document_versions"])


@router.get("/{version_id}", response_model=DocumentVersionRead)
def read_one(version_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    v = get_version(db, version_id)
    if v is not None:
        require_doc_owner(db, v.doc_id, user)  # 数据隔离
    return v


@router.get("/", response_model=list[DocumentVersionRead])
def read_for_doc(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, doc_id, user)  # 数据隔离
    return list_versions(db, doc_id)


@router.post("/", response_model=DocumentVersionRead, status_code=201)
def create_one(data: DocumentVersionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, data.doc_id, user)  # 数据隔离
    return create_version(db, data)
