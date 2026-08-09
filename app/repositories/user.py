from uuid import UUID
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate


def get_by_id(db: Session, user_id: UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def list_all(db: Session, skip: int = 0, limit: int = 10) -> list[User]:
    return db.query(User).offset(skip).limit(limit).all()


def create(db: Session, data: UserCreate) -> User:
    user = User(**data.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
