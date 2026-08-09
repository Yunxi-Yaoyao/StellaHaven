from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.user import UserCreate, UserRead
from app.services.user import get_user, list_users, create_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserRead)
def read_one(user_id: UUID, db: Session = Depends(get_db)):
    return get_user(db, user_id)


@router.get("/", response_model=list[UserRead])
def read_all(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return list_users(db, skip, limit)


@router.post("/", response_model=UserRead, status_code=201)
def create_one(data: UserCreate, db: Session = Depends(get_db)):
    return create_user(db, data)
