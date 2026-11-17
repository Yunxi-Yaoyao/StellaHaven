from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.user import User
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentRead, DocumentListItem, DraftRead, DeletePreviewRequest, DeletePreviewRead
from app.routers.auth import current_user, admin_user, require_ws_owner, require_doc_owner
from app.services.document import (
    get_document, list_documents, create_document, update_document, delete_document, permanently_delete_document,
    restore_document, list_trash_documents, search_documents,
    touch_view, list_recent_documents, get_backlinks, empty_trash, clear_workspace_docs,
    is_draft_fresh, get_fresh_draft, sync_wikilinks,
)

from app.routers.ws import notify_sync

router = APIRouter(dependencies=[Depends(current_user)], prefix="/documents", tags=["documents"])


def zip_target(db, workspace_id, parent_id, user):
    require_ws_owner(db, workspace_id, user)
    if parent_id:
        parent = require_doc_owner(db, parent_id, user)
        if parent.workspace_id != workspace_id or parent.deleted_at is not None:
            raise HTTPException(404, '父文档不存在')


@router.post('/import/zip/preview')
def preview_zip(file: UploadFile = File(...), workspace_id: UUID = Form(...),
                      parent_id: UUID | None = Form(None), encoding: str = Form('auto'),
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.services.notes_zip import MAX_COMPRESSED, preview_archive
    zip_target(db, workspace_id, parent_id, user)
    return preview_archive(file.file.read(MAX_COMPRESSED + 1), encoding)


@router.post('/import/zip')
def import_zip(file: UploadFile = File(...), workspace_id: UUID = Form(...),
                     import_id: UUID = Form(...), parent_id: UUID | None = Form(None),
                     encoding: str = Form('auto'), db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    from app.services.notes_zip import MAX_COMPRESSED, commit_archive
    zip_target(db, workspace_id, parent_id, user)
    result = commit_archive(db, user, workspace_id, parent_id, import_id,
                            file.file.read(MAX_COMPRESSED + 1), encoding)
    notify_list(workspace_id, workspace_id)
    return result


@router.post('/import/html/preview')
def preview_html(file: UploadFile = File(...), workspace_id: UUID = Form(...),
                 parent_id: UUID | None = Form(None), encoding: str = Form('auto'),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    zip_target(db, workspace_id, parent_id, user)
    from app.services.notes_zip import MAX_FILE
    from app.services.html_note_conversion import conversion_archive
    _, report = conversion_archive(file.file.read(MAX_FILE + 1), file.filename or '', encoding)
    return report


@router.post('/import/html')
def import_html(file: UploadFile = File(...), workspace_id: UUID = Form(...),
                import_id: UUID = Form(...), parent_id: UUID | None = Form(None), encoding: str = Form('auto'),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    zip_target(db, workspace_id, parent_id, user)
    from app.services.notes_zip import MAX_FILE, commit_archive
    from app.services.html_note_conversion import conversion_archive
    converted, report = conversion_archive(file.file.read(MAX_FILE + 1), file.filename or '', encoding)
    result = commit_archive(db, user, workspace_id, parent_id, import_id, converted, 'utf-8')
    notify_list(workspace_id, workspace_id)
    return {**result, 'conversion': report}


class ImportFinalize(BaseModel):
    workspace_id: UUID
    document_ids: list[UUID] = Field(min_length=1, max_length=200)


@router.post("/import/finalize")
def finalize_import(data: ImportFinalize, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Resolve forward wikilinks after all imports exist; never save document bodies."""
    require_ws_owner(db, data.workspace_id, user)
    from app.services.document import finalize_documents
    count = finalize_documents(db, data.workspace_id, data.document_ids)
    notify_list(data.workspace_id, data.workspace_id)
    return {"synced": count}


# ⚠️ /search /trash /recent 固定路径必须声明在 /{doc_id} 之前——否则被当 UUID 解析直接 422


@router.get("/search", response_model=list[DocumentListItem])
def search_docs(q: str, workspace_id: UUID, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """全文搜索：标题 + 正文子串匹配（pg_trgm 索引加速），不含回收站"""
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    return search_documents(db, workspace_id, q, limit)


@router.get("/recent", response_model=list[DocumentListItem])
def recent_docs(workspace_id: UUID, limit: int = 8, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """最近查看"""
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    return list_recent_documents(db, workspace_id, limit)


@router.get("/trash", response_model=list[DocumentListItem])
def read_trash(workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """只读回收站列表；清理必须显式请求。"""
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    return list_trash_documents(db, workspace_id)


@router.post('/delete-preview', response_model=DeletePreviewRead)
def delete_preview(data: DeletePreviewRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Read-only complete active+trash scope; no receipt or list-change broadcast.

    Confirm with scope_token query on the matching delete endpoint within ten
    minutes. Tree budget/validation errors return controlled 409, never a partial
    inventory. Token is not authorization; current owner is rechecked on use.
    """
    from app.services.notes_delete_scope import preview_delete
    return preview_delete(db, data, user.id)


@router.post("/trash/empty")
def empty_trash_endpoint(workspace_id: UUID, scope_token: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """清空回收站。scope_token 冻结确认范围；漂移409/零写。

    无 token 的兼容请求处理锁内当前全部回收站，并非界面曾展示的集合。
    模糊提交结果不得自动重放；只读核对后重新预检并确认。
    """
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    n = empty_trash(db, workspace_id, scope_token=scope_token, user_id=user.id)
    notify_list(workspace_id, workspace_id)  # 通知列表频道刷新
    return {"purged": n}


@router.post("/clear-all")
def clear_all_endpoint(workspace_id: UUID, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """清空笔记：工作区全部笔记移入回收站（可还原），前端二次确认"""
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    n = clear_workspace_docs(db, workspace_id)
    notify_list(workspace_id, workspace_id)
    return {"trashed": n}


@router.get("/{doc_id}", response_model=DocumentRead)
def read_one(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, doc_id, user)  # 数据隔离
    doc = get_document(db, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在")
    touch_view(db, doc_id)  # 戳最近查看（不动 updated_at）
    # 草稿新鲜度在读取这一刻惰性判断（10 分钟规则）
    doc.has_draft = is_draft_fresh(doc)
    return doc


@router.get("/{doc_id}/draft", response_model=DraftRead)
def read_draft(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """查看草稿内容。已删或过期草稿返回 404；不物理清除草稿槽。"""
    require_doc_owner(db, doc_id, user)  # 数据隔离
    doc = get_fresh_draft(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="没有未保存草稿")
    return DraftRead(content=doc.draft_content, updated_at=doc.draft_updated_at, device=doc.draft_device)


@router.get("/{doc_id}/backlinks", response_model=list[DocumentListItem])
def read_backlinks(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """反链：哪些页面链接到了这篇"""
    require_doc_owner(db, doc_id, user)  # 数据隔离
    return get_backlinks(db, doc_id)


@router.get("/", response_model=list[DocumentListItem])
def read_all(workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_ws_owner(db, workspace_id, user)  # 数据隔离
    return list_documents(db, workspace_id, parent_id, skip, limit)


def notify_list(workspace_id: UUID, doc_id: UUID):
    """往列表频道广播：这篇文档有变动，前端刷新左侧列表"""
    try:
        notify_sync(f"list:{workspace_id}", {"type": "list_changed", "doc_id": str(doc_id)})
    except Exception:
        pass


@router.post("/", response_model=DocumentRead, status_code=201)
def create_one(data: DocumentCreate, db: Session = Depends(get_db), user: User = Depends(current_user),
               x_import_key: str | None = Header(None)):
    require_ws_owner(db, data.workspace_id, user)  # 数据隔离
    from app.services.notes_lifecycle import lock_workspace
    lock_workspace(db, data.workspace_id)
    if data.parent_id is not None:
        parent = require_doc_owner(db, data.parent_id, user)
        if parent.workspace_id != data.workspace_id or parent.deleted_at is not None:
            raise HTTPException(status_code=404, detail="父文档不存在")
    if x_import_key is not None:
        if x_import_key != data.file_path or not x_import_key.startswith('/imports/') or len(x_import_key) > 1024:
            raise HTTPException(400, 'Invalid X-Import-Key')
        import hashlib
        from sqlalchemy import text
        from app.models.document import Document
        key = hashlib.sha256(f'flat-import:{user.id}:{data.workspace_id}:{x_import_key}'.encode()).digest()
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                   {'key': int.from_bytes(key[:8], 'big', signed=True)})
        existing = db.query(Document).filter(Document.workspace_id == data.workspace_id,
            Document.file_path == x_import_key).order_by(Document.created_at.asc()).first()
        if existing is not None:
            db.commit()
            return existing
    doc = create_document(db, data)
    notify_list(doc.workspace_id, doc.id)
    return doc


@router.put("/{doc_id}")
def update_one(doc_id: UUID, data: DocumentUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_doc_owner(db, doc_id, user)  # 数据隔离
    try:
        result = update_document(db, doc_id, data)
    except ValueError as e:
        db.rollback()
        if str(e) in {"Invalid parent", "Document not found"}:
            raise HTTPException(status_code=404, detail="文档或父文档不存在")
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

    # Preserve the existing unfiltered PUT/raw draft contract; add only a display
    # projection. Do not replace this with DocumentRead (it filters raw fields).
    from fastapi.encoders import jsonable_encoder
    payload = jsonable_encoder(result)
    payload.pop('saved_event_at', None)
    payload['updated_at_display'] = result.updated_at_display
    return payload



@router.post("/{doc_id}/favorite", response_model=DocumentRead)
def toggle_favorite(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """星标切换。轻量端点：只翻 is_favorite，不碰 updated_at（点赞不是保存正文，
    不该让笔记跳列表顶），不走乐观锁（单用户场景无冲突语义）"""
    require_doc_owner(db, doc_id, user)  # 数据隔离
    doc = get_document(db, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.is_favorite = not doc.is_favorite
    db.commit()
    db.refresh(doc)
    notify_list(doc.workspace_id, doc.id)
    return doc


@router.post("/{doc_id}/restore")
def restore_one(doc_id: UUID, cascade: bool = False, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """从回收站还原。cascade=True 时下挂一起还原。
    返回 {doc, reattached, restored}：reattached=父页面不在已挂回根级（前端提醒）"""
    require_doc_owner(db, doc_id, user)  # 数据隔离
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
def delete_one(doc_id: UUID, cascade: bool = True, scope_token: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """幂等移入回收站；cascade=False 子页上移，永不升级为永久删除。

    scope_token 锁内验证预检范围，变化409/零写；无token按处理时树集合。
    """
    require_doc_owner(db, doc_id, user)  # 数据隔离
    doc = get_document(db, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    workspace_id = doc.workspace_id
    try:
        delete_document(db, doc_id, cascade, scope_token=scope_token, user_id=user.id)
    except ValueError:
        raise HTTPException(404, '文档不存在')
    notify_list(workspace_id, doc_id)


@router.delete("/{doc_id}/permanent", status_code=204)
def permanently_delete_one(doc_id: UUID, cascade: bool = True, scope_token: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """显式永久删除；缺失对象安全重试204，引用/范围冲突409且整批不变。

    scope_token 锁内验证预检范围；无token按处理时树集合。
    """
    from app.services.notes_lifecycle import lock_graph
    lock_graph(db)
    doc = get_document(db, doc_id)
    if doc is None:
        db.commit()
        return
    require_doc_owner(db, doc_id, user)
    workspace_id = doc.workspace_id
    permanently_delete_document(db, doc_id, cascade, scope_token=scope_token, user_id=user.id)
    notify_list(workspace_id, doc_id)
