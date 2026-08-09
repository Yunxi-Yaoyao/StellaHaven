from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.doc_tag import DocTagCreate, DocTagRead
from app.services.doc_tag import add_tag, remove_tag, get_tags

router = APIRouter(prefix="/doc-tags", tags=["doc_tags"])


@router.get("/", response_model=list[DocTagRead])
def read_for_doc(doc_id: UUID | None = None, db: Session = Depends(get_db)):
    """带 doc_id 查该文档的标签；不带 → 全量（图谱/筛选要一次拉全）"""
    if doc_id is None:
        from app.models.doc_tag import DocTag
        return db.query(DocTag).all()
    return get_tags(db, doc_id)


@router.post("/", response_model=DocTagRead, status_code=201)
def create_one(data: DocTagCreate, db: Session = Depends(get_db)):
    return add_tag(db, data)


@router.delete("/", status_code=204)
def delete_one(doc_id: UUID, tag_id: UUID, db: Session = Depends(get_db)):
    remove_tag(db, doc_id, tag_id)
