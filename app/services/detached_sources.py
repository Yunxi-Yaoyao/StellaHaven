"""Durable source identity for real Documents moved out of webpage projects.

No new filesystem directory or placeholder note. Metadata lives in AppConfig;
source, version history and trash lifecycle remain on the original document ID.
"""
import json
from fastapi import HTTPException
from app.models.config import AppConfig
from app.models.document import Document
from app.models.workspace import Workspace
from app.services.notes_lifecycle import lock_workspace, rollback_on_error
from app.services.web_projects import DETACHED_PREFIX, uid


def owned(db, owner, ident):
    doc = db.get(Document, uid(ident))
    ws = db.get(Workspace, doc.workspace_id) if doc else None
    row = db.get(AppConfig, DETACHED_PREFIX + str(ident))
    if not doc or doc.deleted_at is not None or not ws or ws.user_id != owner or not row:
        raise HTTPException(404, '独立源码不存在')
    meta = json.loads(row.value)
    if meta.get('owner_id') != str(owner) or meta.get('kind') != 'text' or doc.visibility != 'private' or doc.is_folder:
        raise HTTPException(404, '独立源码不存在')
    return doc, meta


def projection(doc, meta, content=False):
    result = {'id': str(doc.id), 'workspace_id': str(doc.workspace_id), 'title': doc.title,
              'kind': 'detached-source', 'mime': meta['mime'], 'updated_at': doc.updated_at.isoformat()}
    if content: result['content'] = doc.content or ''
    return result


def catalog(db, owner, workspace):
    ws = db.get(Workspace, workspace)
    if not ws or ws.user_id != owner: raise HTTPException(404, '工作区不存在')
    result = []
    for doc in db.query(Document).filter(Document.workspace_id == workspace, Document.deleted_at.is_(None)).all():
        row = db.get(AppConfig, DETACHED_PREFIX + str(doc.id))
        if row:
            current, meta = owned(db, owner, doc.id)
            result.append(projection(current, meta))
    return result


def read(db, owner, ident):
    doc, meta = owned(db, owner, ident)
    return projection(doc, meta, True)


@rollback_on_error
def save(db, owner, ident, updated_at, content):
    try: size = len(content.encode('utf-8'))
    except UnicodeEncodeError: raise HTTPException(422, '源码包含非法 Unicode 字符') from None
    if size > 5 * 1024 * 1024: raise HTTPException(413, '单个源码文件超过5 MiB')
    if '\x00' in content: raise HTTPException(422, '源码不能包含 NUL')
    doc, _ = owned(db, owner, ident)
    lock_workspace(db, doc.workspace_id)
    # Refresh after graph/workspace lock; detached ownership is not a cached grant.
    db.expire_all()
    owned(db, owner, ident)
    from app.services.document import update_document
    from app.schemas.document import DocumentUpdate
    try:
        update_document(db, uid(ident), DocumentUpdate(updated_at=updated_at, content=content), source_edit=True)
    except ValueError as exc:
        raise HTTPException(409, '源码已变化，请重新读取后核对本地草稿') from exc
    return read(db, owner, ident)
