"""全局配置路由：公网地址、站点背景等（设置页）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user
from app.repositories import config as config_repo

# 需登录的配置路由（公网地址等）
router = APIRouter(dependencies=[Depends(current_user)], prefix="/config", tags=["config"])
# 公开配置读路由（主页未登录也要读站点背景）
public_router = APIRouter(prefix="/config", tags=["config"])


class PublicHostIn(BaseModel):
    value: str


@router.get("/public-host")
def get_public_host(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"value": config_repo.get(db, "public_host", "") or ""}


@router.put("/public-host")
def set_public_host(data: PublicHostIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    v = data.value.strip()
    config_repo.put(db, "public_host", v)
    return {"ok": True, "value": v}


@public_router.get("/site-background")
def get_site_background(db: Session = Depends(get_db)):
    """站点背景 = 管理员的壁纸。管理员登录后自选背景，未登录访客看到的就是它。"""
    admin = db.query(User).filter(User.is_admin == True).order_by(User.created_at).first()  # noqa: E712
    return {"value": admin.home_bg if admin else ""}
