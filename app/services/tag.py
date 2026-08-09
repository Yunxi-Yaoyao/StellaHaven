from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.tag import get_by_id, get_by_name, list_all, create
from app.schemas.tag import TagCreate
from app.models.tag import Tag


def get_tag(db: Session, tag_id: UUID) -> Tag | None:
    return get_by_id(db, tag_id)


def list_tags(db: Session, skip: int = 0, limit: int = 20) -> list[Tag]:
    return list_all(db, skip, limit)


def create_tag(db: Session, data: TagCreate) -> Tag:
    return create(db, data)
