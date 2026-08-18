from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from app.routers import (
    workspace_router, user_router, tag_router, document_router,
    doc_tag_router, document_link_router, document_version_router,
    ws_router,
)
from app.routers.attachment import router as attachment_router
from app.routers.homebg import router as homebg_router
from app.routers.auth import router as auth_router
from app.routers.admin_email import router as admin_email_router
from app.routers.monitor import node_router, agent_router, monitor_router
from app.routers.task import router as task_router, agent_task_router
from app.routers.config import router as config_router, public_router as config_public_router
from app.routers.drive import router as drive_router
from app.routers.oidc import router as oidc_router
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# 全局资源（主页背景/挂件素材等）：和笔记附件系统（引用计数清理）完全隔离
ASSETS_DIR = Path(__file__).resolve().parent / "data" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# 前端 SPA（生产部署）
FRONTEND_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
API_PREFIXES = (
    "/auth", "/nodes", "/monitors", "/agent", "/config", "/workspaces",
    "/documents", "/tags", "/doc-tags", "/document-links",
    "/document-versions", "/attachments", "/homebg", "/iperf-tasks",
    "/mtr-tasks", "/commands", "/ws", "/assets", "/drive",
    "/.well-known", "/oauth",
)

app = FastAPI(title="StellaHaven")

app.include_router(workspace_router)
app.include_router(user_router)
app.include_router(tag_router)
app.include_router(document_router)
app.include_router(doc_tag_router)
app.include_router(document_link_router)
app.include_router(document_version_router)
app.include_router(ws_router)
app.include_router(attachment_router)
app.include_router(homebg_router)
app.include_router(auth_router)
app.include_router(admin_email_router)
app.include_router(node_router)
app.include_router(monitor_router)
app.include_router(agent_router)
app.include_router(task_router)
app.include_router(agent_task_router)
app.include_router(config_router)
app.include_router(config_public_router)
app.include_router(drive_router)
app.include_router(oidc_router)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


# 前端 SPA：静态文件 + 路由 fallback（必须在所有 API 路由之后注册）
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str, request: Request):
    path = request.url.path
    # 只拦截「带子路径」的 API 请求（/drive/status），不拦截「精确等于前缀」的前端路由（/drive）
    if any(path.startswith(p + "/") for p in API_PREFIXES):
        raise HTTPException(404, "Not Found")
    candidate = FRONTEND_DIR / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404, "Not Found")

