"""图库（Immich）路由：容器状态探测 + 启停管理 + 免登录连接端点。"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.models.user import User
from app.routers.auth import current_user
from app.services import gallery as gallery_svc

router = APIRouter(dependencies=[Depends(current_user)], prefix="/gallery", tags=["gallery"])



@router.get("/connect")
def connect(request: Request, user: User = Depends(current_user)):
    """iframe 免登录入口：Stella 已登录才放行，按当前域名选择 Immich 入口做 302。
    冗余：yunxi.life 子域走 LA 上的 immich.yunxi.life，其他回退到 immich.xiya.live。
    Immich 已配 autoLaunch + OIDC(Stella)，未登录会自动走 OAuth 流程。"""
    host = request.headers.get("host", "").lower().split(":")[0]
    if host.endswith((".yunxi.life", "yunxi.life")):
        return RedirectResponse("https://immich.yunxi.life/")
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
