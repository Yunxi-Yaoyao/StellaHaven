from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.tag import get_by_id, get_by_name, list_all, create
from app.schemas.tag import TagCreate
from app.models.tag import Tag
from app.models.doc_tag import DocTag


def get_tag(db: Session, tag_id: UUID) -> Tag | None:
    return get_by_id(db, tag_id)


def list_tags(db: Session, user_id: UUID, skip: int = 0, limit: int = 200) -> list[Tag]:
    return list_all(db, user_id, skip, limit)


def create_tag(db: Session, data: TagCreate) -> Tag:
    return create(db, data)


def purge_orphan_tags(db: Session, tag_ids: list[UUID]) -> int:
    """删掉「不再被任何文档引用」的标签本体。返回清了几条。

    触发时机：摘标签、删文档、清空工作区——凡是 doc_tags 关联被移除的地方都要调。
    判断标准：doc_tags 表里还有没有这个 tag_id 的引用，没有 = 孤儿。
    """
    removed = 0
    for tid in tag_ids:
        still_used = db.query(DocTag).filter(DocTag.tag_id == tid).count() > 0
        if not still_used:
            db.query(Tag).filter(Tag.id == tid).delete(synchronize_session=False)
            removed += 1
    if removed:
        db.commit()
    return removed
