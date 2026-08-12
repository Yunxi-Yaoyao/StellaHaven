from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.document_link import DocumentLinkCreate, DocumentLinkRead
from app.services.document_link import create_link, remove_link, get_links
from app.routers.auth import current_user, require_ws_owner, require_doc_owner

router = APIRouter(dependencies=[Depends(current_user)], prefix="/document-links", tags=["document_links"])


@router.get("/", response_model=list[DocumentLinkRead])
def read_for_doc(doc_id: UUID | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """带 doc_id 查该文档的链接（双向）；不带 → 全量（图谱用）"""
    require_doc_owner(db, doc_id, user)  # 数据隔离
    if doc_id is None:
        from app.models.document_link import DocumentLink
        return db.query(DocumentLink).all()
    return get_links(db, doc_id)


@router.post("/", response_model=DocumentLinkRead, status_code=201)
def create_one(data: DocumentLinkCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, data.source_id, user)  # 数据隔离
    return create_link(db, data)


@router.delete("/", status_code=204)
def delete_one(source_id: UUID, target_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, source_id, user)  # 数据隔离
    remove_link(db, source_id, target_id)
