import re
import hashlib
import json
from sqlalchemy import text
from app.models.config import AppConfig
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request, Header
from starlette.concurrency import run_in_threadpool
from app.services import blob_store
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.attachment import Attachment
from app.models.document import Document
from app.routers.auth import current_user, require_ws_owner, require_doc_owner

router = APIRouter(dependencies=[Depends(current_user)], prefix="/attachments", tags=["attachments"])

# 文件本体落这里（DB 只记元信息——二进制不进关系库，docs/15 的决策）
STORAGE = Path(__file__).resolve().parents[2] / "data" / "attachments"
if not blob_store.enabled():
    STORAGE.mkdir(parents=True, exist_ok=True)

# 正文里引用附件的标记：![..](/attachments/{id})
ATTACH_REF_RE = re.compile(r"/attachments/([0-9a-f-]{36})")

MAX_SIZE = 25 * 1024 * 1024  # 25MB（手机原图随便贴）


@router.get("/")
def list_attachments(workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """列出工作区所有附件（含所属笔记标题；回收站里的笔记的附件也列出并标记）"""
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    rows = (
        db.query(Attachment, Document)
        .join(Document, Attachment.doc_id == Document.id)
        .filter(Document.workspace_id == workspace_id)
        .order_by(Attachment.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(a.id),
            "url": f"/attachments/{a.id}",
            "filename": a.filename,
            "mime": a.mime,
            "size": a.size,
            "created_at": a.created_at.isoformat(),
            "doc_id": str(d.id),
            "doc_title": d.title,
            "doc_in_trash": d.deleted_at is not None,
        }
        for a, d in rows
    ]


@router.post("/{doc_id}")
async def upload(doc_id: UUID, file: UploadFile, db: Session = Depends(get_db), user: User = Depends(current_user), idempotency_key: str | None = Header(default=None, max_length=128)):
    """上传附件：粘贴图片时前端调这里。返回引用路径"""
    require_doc_owner(db, doc_id, user)  # 数据隔离
    doc = db.get(Document, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在")

    data = await file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 25MB")

    def persist():
        receipt_key = None
        fingerprint = None
        if blob_store.enabled() and idempotency_key:
            receipt_key = hashlib.sha256(('ha-upload:'+str(user.id)+':'+str(doc_id)+':'+idempotency_key).encode()).hexdigest()
            fingerprint = hashlib.sha256(data).hexdigest()
            db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':receipt_key})
            old = db.get(AppConfig,receipt_key)
            if old is not None:
                receipt=json.loads(old.value)
                if receipt['sha256'] != fingerprint or receipt['size'] != len(data):
                    raise HTTPException(409,'Idempotency key reused with different content')
                previous=db.get(Attachment,UUID(receipt['id']))
                if previous is None:raise HTTPException(409,'Original upload was deleted')
                return {'id':str(previous.id),'url':'/attachments/'+str(previous.id),'filename':previous.filename}
        att = Attachment(
            doc_id=doc_id,
            filename=file.filename or "paste.png",
            mime=file.content_type or "application/octet-stream",
            size=len(data),
        )
        db.add(att)
        if blob_store.enabled():
            import io
            db.flush()
            blob_store.put(db, 'attachments/'+str(att.id), io.BytesIO(data), att.mime, MAX_SIZE)
            if receipt_key:
                db.add(AppConfig(key=receipt_key,value=json.dumps({'id':str(att.id),'size':len(data),'sha256':fingerprint})))
            db.commit()
            db.refresh(att)
        else:
            db.commit()
            db.refresh(att)
            (STORAGE / str(att.id)).write_bytes(data)
        return {"id": str(att.id), "url": f"/attachments/{att.id}", "filename": att.filename}
    return await run_in_threadpool(persist)


@router.api_route("/{att_id}", methods=["GET", "HEAD"])
def serve(att_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """读附件（仅归属者）；鉴权和物化的连接均不随下载存活。"""
    headers = {'Cache-Control': 'no-store'}
    try:
        att = db.get(Attachment, att_id)
        if att is None:
            raise HTTPException(status_code=404, detail="附件不存在")
        require_doc_owner(db, att.doc_id, user)
        filename, mime = att.filename, att.mime
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **headers}
        raise
    finally:
        # current_user + require_doc_owner are read-only (no heartbeat writes).
        # This GET/HEAD has no pending business state. Yield cleanup is otherwise
        # request-scoped and would keep the auth transaction during slow sends.
        db.close()
    if blob_store.enabled():
        return blob_store.response(db, 'attachments/'+str(att_id), request, filename=filename, private=True)
    path = STORAGE / str(att_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="附件不存在", headers=headers)
    return FileResponse(path, media_type=mime, filename=filename, headers=headers)


def cleanup_unreferenced(db: Session, doc: Document, content: str) -> int:
    """引用计数清理（老婆的规则：笔记里删了图片，存储也要删）。
    保存正文后调用：这篇文档不再引用的附件 → 连文件带记录删。"""
    referenced = set(ATTACH_REF_RE.findall(content or ""))
    removed = 0
    for att in db.query(Attachment).filter(Attachment.doc_id == doc.id).all():
        if str(att.id) not in referenced:
            if blob_store.enabled():
                blob_store.delete(db, 'attachments/'+str(att.id))
            else:
                (STORAGE / str(att.id)).unlink(missing_ok=True)
            db.delete(att)
            removed += 1
    if removed:
        db.commit()
    return removed


def delete_attachments_of(db: Session, doc_id: UUID) -> None:
    """物理删文档时连带清附件"""
    for att in db.query(Attachment).filter(Attachment.doc_id == doc_id).all():
        if blob_store.enabled():
            blob_store.delete(db, 'attachments/'+str(att.id))
        else:
            (STORAGE / str(att.id)).unlink(missing_ok=True)
        db.delete(att)
