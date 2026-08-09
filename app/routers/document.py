from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentRead, DraftRead
from app.services.document import (
    get_document, list_documents, create_document, update_document, delete_document,
    restore_document, list_trash_documents, search_documents,
    touch_view, list_recent_documents, get_backlinks,
    is_draft_fresh, get_fresh_draft,
)

from app.routers.ws import notify_sync

router = APIRouter(prefix="/documents", tags=["documents"])


# ⚠️ /search /trash /recent 固定路径必须声明在 /{doc_id} 之前——否则被当 UUID 解析直接 422


@router.get("/search", response_model=list[DocumentRead])
def search_docs(q: str, workspace_id: UUID, limit: int = 50, db: Session = Depends(get_db)):
    """全文搜索：标题 + 正文子串匹配（pg_trgm 索引加速），不含回收站"""
    return search_documents(db, workspace_id, q, limit)


@router.get("/recent", response_model=list[DocumentRead])
def recent_docs(workspace_id: UUID, limit: int = 8, db: Session = Depends(get_db)):
    """最近查看"""
    return list_recent_documents(db, workspace_id, limit)


@router.get("/trash", response_model=list[DocumentRead])
def read_trash(workspace_id: UUID, db: Session = Depends(get_db)):
    """回收站列表。访问时顺手惰性清理超过保留期的（默认 30 天）"""
    return list_trash_documents(db, workspace_id)


@router.get("/{doc_id}", response_model=DocumentRead)
def read_one(doc_id: UUID, db: Session = Depends(get_db)):
    doc = get_document(db, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在")
    touch_view(db, doc_id)  # 戳最近查看（不动 updated_at）
    # 草稿新鲜度在读取这一刻惰性判断（10 分钟规则）
    doc.has_draft = is_draft_fresh(doc)
    return doc


@router.get("/{doc_id}/draft", response_model=DraftRead)
def read_draft(doc_id: UUID, db: Session = Depends(get_db)):
    """查看草稿内容。过期草稿返回 404——和「没有草稿」同一个语义。"""
    doc = get_fresh_draft(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="没有未保存草稿")
    return DraftRead(content=doc.draft_content, updated_at=doc.draft_updated_at, device=doc.draft_device)


@router.get("/{doc_id}/backlinks", response_model=list[DocumentRead])
def read_backlinks(doc_id: UUID, db: Session = Depends(get_db)):
    """反链：哪些页面链接到了这篇"""
    return get_backlinks(db, doc_id)


@router.get("/", response_model=list[DocumentRead])
def read_all(workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    return list_documents(db, workspace_id, parent_id, skip, limit)


def notify_list(workspace_id: UUID, doc_id: UUID):
    """往列表频道广播：这篇文档有变动，前端刷新左侧列表"""
    try:
        notify_sync(f"list:{workspace_id}", {"type": "list_changed", "doc_id": str(doc_id)})
    except Exception:
        pass


@router.post("/", response_model=DocumentRead, status_code=201)
def create_one(data: DocumentCreate, db: Session = Depends(get_db)):
    doc = create_document(db, data)
    notify_list(doc.workspace_id, doc.id)
    return doc


@router.put("/{doc_id}")
def update_one(doc_id: UUID, data: DocumentUpdate, request: Request, db: Session = Depends(get_db)):
    try:
        result = update_document(db, doc_id, data)
    except ValueError as e:
        if str(e) == "Circular parent":
            raise HTTPException(status_code=409, detail={"message": "不能移动到它自己或它的子页面下面"})
        raise HTTPException(status_code=409, detail={
            "message": str(e) if str(e) == "Conflict" else "文档已被修改或不存在，请刷新",
            "editor": {
                "ip": request.client.host,
                "ua": request.headers.get("User-Agent", "")
            }
        })

    # 保存成功 → 通知其他设备（文档频道）+ 列表频道
    try:
        notify_sync(doc_id, {
            "type": "doc_saved",
            "by": {
                "ip": request.client.host,
                "ua": request.headers.get("User-Agent", ""),
                "saved_at": result.updated_at.isoformat()
            }
        })
    except Exception:
        pass
    notify_list(result.workspace_id, doc_id)

    return result



@router.post("/{doc_id}/favorite", response_model=DocumentRead)
def toggle_favorite(doc_id: UUID, db: Session = Depends(get_db)):
    """星标切换。轻量端点：只翻 is_favorite，不碰 updated_at（点赞不是保存正文，
    不该让笔记跳列表顶），不走乐观锁（单用户场景无冲突语义）"""
    doc = get_document(db, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.is_favorite = not doc.is_favorite
    db.commit()
    db.refresh(doc)
    notify_list(doc.workspace_id, doc.id)
    return doc


@router.post("/{doc_id}/restore")
def restore_one(doc_id: UUID, cascade: bool = False, db: Session = Depends(get_db)):
    """从回收站还原。cascade=True 时下挂一起还原。
    返回 {doc, reattached, restored}：reattached=父页面不在已挂回根级（前端提醒）"""
    try:
        result = restore_document(db, doc_id, cascade)
    except ValueError:
        raise HTTPException(status_code=404, detail="回收站里没有这篇文档")
    doc = result["doc"]
    notify_list(doc.workspace_id, doc.id)
    return {
        "doc": DocumentRead.model_validate(doc),
        "reattached": result["reattached"],
        "restored": result["restored"],
    }


@router.delete("/{doc_id}", status_code=204)
def delete_one(doc_id: UUID, cascade: bool = True, db: Session = Depends(get_db)):
    """两级删除 + 级联策略：cascade=True 下挂一起进回收站；False 子页上移一级。
    回收站里的再删 → 物理删除"""
    doc = get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    workspace_id = doc.workspace_id
    delete_document(db, doc_id, cascade)
    notify_list(workspace_id, doc_id)
