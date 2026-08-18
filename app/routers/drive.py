"""网盘（alist）路由：docker 检测/安装、拉镜像进度、存储配置、创建容器。"""
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user
from app.services import drive as drive_svc

router = APIRouter(dependencies=[Depends(current_user)], prefix="/drive", tags=["drive"])


class StorageIn(BaseModel):
    name: str
    host_path: str
    mount_path: str


class SettingsIn(BaseModel):
    port: int = 5244
    mem_limit: str | None = None
    cpus: str | None = None
    tz: str = "Asia/Shanghai"
    restart_policy: str = "unless-stopped"


class InstallIn(BaseModel):
    storages: list[StorageIn]
    settings: SettingsIn | None = None


@router.get("/status")
def get_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.get_status(db)


@router.post("/docker/install")
def install_docker(user: User = Depends(current_user)):
    return drive_svc.install_docker()


@router.post("/pull")
def pull_image(user: User = Depends(current_user), db: Session = Depends(get_db)):
    drive_svc.start_pull(db)
    return {"ok": True}


class ProxyIn(BaseModel):
    proxy: str  # 空字符串 = 清除代理（走宿主机默认网络）


@router.post("/proxy")
def set_proxy(data: ProxyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.apply_proxy(db, data.proxy)


@router.get("/pull/progress")
def pull_progress(user: User = Depends(current_user)):
    return drive_svc.get_pull_progress()


@router.post("/install")
def install_container(data: InstallIn, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    storages = [s.model_dump() for s in data.storages]
    settings = data.settings.model_dump() if data.settings else None
    return drive_svc.install_container(db, storages, settings=settings)


@router.get("/login-url")
def login_url(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.get_login_url(db)


@router.post("/start")
def start(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.start_container(db)


@router.post("/stop")
def stop(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.stop_container(db)


@router.post("/restart")
def restart(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.restart_container(db)


class UninstallIn(BaseModel):
    remove_image: bool = False


@router.post("/uninstall")
def uninstall(data: UninstallIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    return drive_svc.uninstall_container(db, remove_image=data.remove_image)


@router.post("/remove-image")
def remove_image(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.remove_image(db)


@router.post("/check-update")
def check_update(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.check_update(db)


@router.post("/update")
def update(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.update_container(db)


@router.post("/pull-latest")
def pull_latest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return drive_svc.pull_latest(db)


# ── OpenList 反代：藏在 Stella 子路径 /drive/openlist/ 下 ──
# OpenList 监听 127.0.0.1 不暴露公网，所有访问走 Stella 反代（复用 stella.xiya.live 隧道）
OPENLIST_UPSTREAM = "http://127.0.0.1:5244"
_HOP_HEADERS = {
    "content-length", "transfer-encoding", "connection", "keep-alive",
    "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailer",
}


@router.api_route("/openlist/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def openlist_proxy(path: str, request: Request,
                         user: User = Depends(current_user)):
    """反代 /drive/openlist/* → 127.0.0.1:5244（保留前缀，OpenList base_path=/drive/openlist）。"""
    url = f"{OPENLIST_UPSTREAM}/drive/openlist/{path}"
    # 去掉 host + hop-by-hop + Accept-Encoding（让 OpenList 返回未压缩内容，
    # 否则 httpx 自动解压 + aiter_raw 流式转发会截断，导致 JS 不完整前端白屏）
    req_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in _HOP_HEADERS
                   and k.lower() not in ("host", "accept-encoding")}
    # 不用 async with（退出时会提前 aclose，导致流式响应被截断）——
    # client 由 body_iterator 在读完（或中断）后关闭
    client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    req = client.build_request(
        request.method, url,
        headers=req_headers,
        params=dict(request.query_params),
        content=await request.body(),
    )
    resp = await client.send(req, stream=True)
    resp_headers = {k: v for k, v in resp.headers.items()
                    if k.lower() not in _HOP_HEADERS}

    # HTML 响应：读全 + 注入深色主题 CSS（首屏第一次渲染就是深色，消除默认浅色主题的闪烁）
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        body = await resp.aread()
        html = body.decode("utf-8", errors="replace")
        html = drive_svc.inject_theme_html(html)
        await client.aclose()
        # 禁止缓存 HTML，确保浏览器每次都拿到最新的 customize_head/body 注入
        resp_headers["cache-control"] = "no-store, no-cache, must-revalidate"
        resp_headers["pragma"] = "no-cache"
        return Response(content=html, status_code=resp.status_code,
                        headers=resp_headers, media_type="text/html")

    async def body_iterator():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await client.aclose()

    return StreamingResponse(
        body_iterator(),
        status_code=resp.status_code,
        headers=resp_headers,
    )
