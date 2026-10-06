from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, defer
from app.database import get_db
from app.models.user import User
from app.models.document_version import DocumentVersion
from app.schemas.document import DocumentRead, DocumentUpdate
from app.schemas.document_version import DocumentVersionCreate, DocumentVersionRead, DocumentVersionSummary
from app.services.document_version import get_version, create_version, content_diff
from app.routers.auth import current_user, admin_user, require_doc_owner

router = APIRouter(dependencies=[Depends(current_user)], prefix='/document-versions', tags=['document_versions'])


def owned_version(db, version_id, user):
    v = get_version(db, version_id)
    if v is None:
        raise HTTPException(404, '版本不存在')
    doc = require_doc_owner(db, v.doc_id, user)
    if doc.deleted_at is not None:
        raise HTTPException(404, '文档不存在')
    return v, doc


@router.get('/{version_id}', response_model=DocumentVersionRead)
def read_one(version_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return owned_version(db, version_id, user)[0]


@router.get('/', response_model=list[DocumentVersionSummary])
def read_for_doc(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = require_doc_owner(db, doc_id, user)
    if doc.deleted_at is not None:
        raise HTTPException(404, '文档不存在')
    return db.query(DocumentVersion).options(defer(DocumentVersion.content, raiseload=True), defer(DocumentVersion.diff, raiseload=True)).filter(
        DocumentVersion.doc_id == doc_id).order_by(DocumentVersion.version_no.desc()).limit(100).all()


@router.get('/{version_id}/diff')
def diff_version(version_id: UUID, against: UUID | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    version, doc = owned_version(db, version_id, user)
    after = doc.content or ''
    if against is not None:
        other, _ = owned_version(db, against, user)
        if other.doc_id != version.doc_id:
            raise HTTPException(404, '版本不存在')
        after = other.content
    return {'version_id': version.id, 'against': against, 'diff': content_diff(version.content, after)}


class RestoreVersion(BaseModel):
    updated_at: datetime


@router.post('/{version_id}/restore', response_model=DocumentRead)
def restore_version(version_id: UUID, data: RestoreVersion, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    version, doc = owned_version(db, version_id, user)
    from app.services.document import update_document
    from app.routers.document import notify_list
    try:
        result = update_document(db, doc.id, DocumentUpdate(updated_at=data.updated_at, content=version.content), force_version=True)
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    notify_list(result.workspace_id, result.id)
    return result


@router.post('/', response_model=DocumentVersionRead, status_code=201)
def create_one(data: DocumentVersionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = require_doc_owner(db, data.doc_id, user)
    if doc.deleted_at is not None:
        raise HTTPException(404, '文档不存在')
    return create_version(db, data)
