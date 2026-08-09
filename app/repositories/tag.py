from uuid import UUID
from sqlalchemy.orm import Session

from app.models.tag import Tag
from app.schemas.tag import TagCreate


def get_by_id(db: Session, tag_id: UUID) -> Tag | None:
    return db.query(Tag).filter(Tag.id == tag_id).first()


def get_by_name(db: Session, name: str) -> Tag | None:
    return db.query(Tag).filter(Tag.name == name).first()


def list_all(db: Session, skip: int = 0, limit: int = 20) -> list[Tag]:
    return db.query(Tag).offset(skip).limit(limit).all()


def create(db: Session, data: TagCreate) -> Tag:
    tag = Tag(**data.model_dump())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag
