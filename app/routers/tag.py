from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.tag import TagCreate, TagRead
from app.services.tag import get_tag, list_tags, create_tag
from app.models.user import User
from app.routers.auth import current_user

router = APIRouter(dependencies=[Depends(current_user)], prefix="/tags", tags=["tags"])


@router.get("/{tag_id}", response_model=TagRead)
def read_one(tag_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    tag = get_tag(db, tag_id)
    if tag is None or tag.user_id != user.id:
        from fastapi import HTTPException
        raise HTTPException(404, "标签不存在")
    return tag


@router.get("/", response_model=list[TagRead])
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db),
             skip: int = 0, limit: int = 200):
    """列出当前用户的标签（隔离：只出自己的）"""
    return list_tags(db, user.id, skip, limit)


@router.post("/", response_model=TagRead, status_code=201)
def create_one(data: TagCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """创建标签（归属当前用户，无视前端传的 user_id）"""
    data.user_id = user.id
    return create_tag(db, data)
