import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attachment import Attachment
from app.models.document import Document

router = APIRouter(prefix="/attachments", tags=["attachments"])

# 文件本体落这里（DB 只记元信息——二进制不进关系库，docs/15 的决策）
STORAGE = Path(__file__).resolve().parents[2] / "data" / "attachments"
STORAGE.mkdir(parents=True, exist_ok=True)

# 正文里引用附件的标记：![..](/attachments/{id})
ATTACH_REF_RE = re.compile(r"/attachments/([0-9a-f-]{36})")

MAX_SIZE = 25 * 1024 * 1024  # 25MB（手机原图随便贴）


@router.get("/")
def list_attachments(workspace_id: UUID, db: Session = Depends(get_db)):
    """列出工作区所有附件（含所属笔记标题；回收站里的笔记的附件也列出并标记）"""
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
async def upload(doc_id: UUID, file: UploadFile, db: Session = Depends(get_db)):
    """上传附件：粘贴图片时前端调这里。返回引用路径"""
    doc = db.get(Document, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 25MB")

    att = Attachment(
        doc_id=doc_id,
        filename=file.filename or "paste.png",
        mime=file.content_type or "application/octet-stream",
        size=len(data),
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    (STORAGE / str(att.id)).write_bytes(data)
    return {"id": str(att.id), "url": f"/attachments/{att.id}", "filename": att.filename}


@router.get("/{att_id}")
def serve(att_id: UUID, db: Session = Depends(get_db)):
    """读附件"""
    att = db.get(Attachment, att_id)
    path = STORAGE / str(att_id)
    if att is None or not path.exists():
        raise HTTPException(status_code=404, detail="附件不存在")
    return FileResponse(path, media_type=att.mime, filename=att.filename)


def cleanup_unreferenced(db: Session, doc: Document, content: str) -> int:
    """引用计数清理（老婆的规则：笔记里删了图片，存储也要删）。
    保存正文后调用：这篇文档不再引用的附件 → 连文件带记录删。"""
    referenced = set(ATTACH_REF_RE.findall(content or ""))
    removed = 0
    for att in db.query(Attachment).filter(Attachment.doc_id == doc.id).all():
        if str(att.id) not in referenced:
            (STORAGE / str(att.id)).unlink(missing_ok=True)
            db.delete(att)
            removed += 1
    if removed:
        db.commit()
    return removed


def delete_attachments_of(db: Session, doc_id: UUID) -> None:
    """物理删文档时连带清附件"""
    for att in db.query(Attachment).filter(Attachment.doc_id == doc_id).all():
        (STORAGE / str(att.id)).unlink(missing_ok=True)
        db.delete(att)
