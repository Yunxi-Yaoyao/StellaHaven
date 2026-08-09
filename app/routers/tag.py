from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.tag import TagCreate, TagRead
from app.services.tag import get_tag, list_tags, create_tag

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/{tag_id}", response_model=TagRead)
def read_one(tag_id: UUID, db: Session = Depends(get_db)):
    return get_tag(db, tag_id)


@router.get("/", response_model=list[TagRead])
def read_all(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    return list_tags(db, skip, limit)


@router.post("/", response_model=TagRead, status_code=201)
def create_one(data: TagCreate, db: Session = Depends(get_db)):
    return create_tag(db, data)
