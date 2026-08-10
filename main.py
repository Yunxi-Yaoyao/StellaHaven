from fastapi import FastAPI
from app.routers import (
    workspace_router, user_router, tag_router, document_router,
    doc_tag_router, document_link_router, document_version_router,
    ws_router,
)
from app.routers.attachment import router as attachment_router
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# 全局资源（主页背景/挂件素材等）：和笔记附件系统（引用计数清理）完全隔离
ASSETS_DIR = Path(__file__).resolve().parent / "data" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

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
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

