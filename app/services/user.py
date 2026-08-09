from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.user import get_by_id, get_by_username, list_all, create
from app.schemas.user import UserCreate
from app.models.user import User


def get_user(db: Session, user_id: UUID) -> User | None:
    return get_by_id(db, user_id)


def find_user(db: Session, username: str) -> User | None:
    return get_by_username(db, username)


def list_users(db: Session, skip: int = 0, limit: int = 10) -> list[User]:
    return list_all(db, skip, limit)


def create_user(db: Session, data: UserCreate) -> User:
    return create(db, data)
