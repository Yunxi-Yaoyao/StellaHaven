from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.doc_tag import DocTagCreate, DocTagRead
from app.services.doc_tag import add_tag, remove_tag, get_tags
from app.routers.auth import current_user, require_ws_owner, require_doc_owner

router = APIRouter(dependencies=[Depends(current_user)], prefix="/doc-tags", tags=["doc_tags"])


@router.get("/", response_model=list[DocTagRead])
def read_for_doc(doc_id: UUID | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """带 doc_id 查该文档的标签；不带 → 全量（图谱/筛选一次拉全）。
    数据隔离：全量只出当前用户的（经 document→workspace 归属）"""
    if doc_id is not None:
        require_doc_owner(db, doc_id, user)
        return get_tags(db, doc_id)
    from app.models.doc_tag import DocTag
    from app.models.document import Document
    from app.models.workspace import Workspace
    return (db.query(DocTag)
            .join(Document, DocTag.doc_id == Document.id)
            .join(Workspace, Document.workspace_id == Workspace.id)
            .filter(Workspace.user_id == user.id)
            .all())


@router.post("/", response_model=DocTagRead, status_code=201)
def create_one(data: DocTagCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, data.doc_id, user)  # 数据隔离
    return add_tag(db, data)


@router.delete("/", status_code=204)
def delete_one(doc_id: UUID, tag_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, doc_id, user)  # 数据隔离
    remove_tag(db, doc_id, tag_id)
