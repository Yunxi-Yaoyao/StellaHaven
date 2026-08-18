from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.doc_tag import add, remove, get_tags_for_doc
from app.schemas.doc_tag import DocTagCreate
from app.models.doc_tag import DocTag


def add_tag(db: Session, data: DocTagCreate) -> DocTag:
    return add(db, data)


def remove_tag(db: Session, doc_id: UUID, tag_id: UUID) -> None:
    remove(db, doc_id, tag_id)
    # 摘掉后这标签可能成了孤儿 → 顺手清掉本体
    from app.services.tag import purge_orphan_tags
    purge_orphan_tags(db, [tag_id])


def get_tags(db: Session, doc_id: UUID) -> list[DocTag]:
    return get_tags_for_doc(db, doc_id)
