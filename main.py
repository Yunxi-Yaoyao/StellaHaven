from fastapi import FastAPI
from app.routers import (
    workspace_router, user_router, tag_router, document_router,
    doc_tag_router, document_link_router, document_version_router,
    ws_router,
)
from app.routers.attachment import router as attachment_router

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

