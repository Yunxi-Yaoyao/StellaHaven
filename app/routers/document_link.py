from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, aliased
from app.database import get_db
from app.models.user import User
from app.models.document import Document
from app.models.document_link import DocumentLink
from app.schemas.document_link import DocumentLinkCreate, DocumentLinkRead
from app.services.document_link import create_link, remove_link
from app.routers.auth import current_user, require_ws_owner, require_doc_owner

router = APIRouter(dependencies=[Depends(current_user)], prefix='/document-links', tags=['document_links'])


def scoped_links(db, workspace_id):
    source, target = aliased(Document), aliased(Document)
    return db.query(DocumentLink).join(source, source.id == DocumentLink.source_id).join(target, target.id == DocumentLink.target_id).filter(
        source.workspace_id == workspace_id, target.workspace_id == workspace_id,
        source.deleted_at.is_(None), target.deleted_at.is_(None))


@router.get('/', response_model=list[DocumentLinkRead])
def read_for_doc(doc_id: UUID | None = None, workspace_id: UUID | None = None,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    if doc_id is not None:
        doc = require_doc_owner(db, doc_id, user)
        if doc.deleted_at is not None or (workspace_id is not None and workspace_id != doc.workspace_id):
            raise HTTPException(404, '文档不存在')
        workspace_id = doc.workspace_id
    if workspace_id is None:
        raise HTTPException(422, '需要 workspace_id 或 doc_id')
    require_ws_owner(db, workspace_id, user)
    query = scoped_links(db, workspace_id)
    if doc_id is not None:
        query = query.filter((DocumentLink.source_id == doc_id) | (DocumentLink.target_id == doc_id))
    return query.all()


def validate_pair(db, source_id, target_id, user):
    source = require_doc_owner(db, source_id, user)
    target = require_doc_owner(db, target_id, user)
    if source.deleted_at is not None or target.deleted_at is not None or source.workspace_id != target.workspace_id:
        raise HTTPException(404, '关联文档不存在')


@router.post('/', response_model=DocumentLinkRead, status_code=201)
def create_one(data: DocumentLinkCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    validate_pair(db, data.source_id, data.target_id, user)
    return create_link(db, data)


@router.delete('/', status_code=204)
def delete_one(source_id: UUID, target_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    validate_pair(db, source_id, target_id, user)
    remove_link(db, source_id, target_id)
