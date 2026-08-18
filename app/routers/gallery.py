"""图库（Immich）路由：容器状态探测 + 启停管理 + 免登录连接端点。"""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.models.user import User
from app.routers.auth import current_user
from app.services import gallery as gallery_svc

router = APIRouter(dependencies=[Depends(current_user)], prefix="/gallery", tags=["gallery"])



@router.get("/connect")
def connect(user: User = Depends(current_user)):
    """iframe 免登录入口：Stella 已登录才放行，302 到 Immich。
    Immich 已配 autoLaunch + OIDC(Stella)，未登录会自动走 OAuth 流程；
    链路全在 xiya.live 下（SameSite=Lax 按 eTLD+1 判同站，iframe 内导航 cookie 照发），
    Stella authorize 能读到登录态直接签 code，全程无需用户操作。"""
    return RedirectResponse("https://immich.xiya.live/")


@router.get("/status")
def get_status():
    return gallery_svc.get_status()


@router.post("/start")
def start():
    return gallery_svc.start_container()


@router.post("/stop")
def stop():
    return gallery_svc.stop_container()


@router.post("/restart")
def restart():
    return gallery_svc.restart_container()
