from datetime import datetime
from hashlib import sha256
from uuid import UUID
from sqlalchemy.orm import Session

import re

from app.repositories.document import (
    get_by_id, list_by_workspace, list_trash, purge_expired_trash, search,
    create, update, delete,
    children_of, descendants_of, list_recent,
)
from app.repositories import document_link as link_repo
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.schemas.document_link import DocumentLinkCreate
from app.models.document import Document
from app.services.notes_lifecycle import rollback_on_error, lock_document, lock_workspace, locked_tree, subtree

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")

# 草稿新鲜度：超过 10 分钟没再编辑的草稿视为不存在（惰性判断，不做物理删除）
DRAFT_TTL_SECONDS = 600

# 回收站保留期：软删超过 30 天的，下次有人看回收站时物理清除（惰性清理）
TRASH_RETENTION_DAYS = 30


def _hash_content(content: str) -> str:
    return sha256(content.encode()).hexdigest()


def get_document(db: Session, doc_id: UUID) -> Document | None:
    return get_by_id(db, doc_id)


def list_documents(db: Session, workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20) -> list[Document]:
    return list_by_workspace(db, workspace_id, parent_id, skip, limit)


@rollback_on_error
def create_document(db: Session, data: DocumentCreate) -> Document:
    lock_workspace(db, data.workspace_id)
    if data.parent_id is not None:
        parent = db.query(Document).filter(Document.id == data.parent_id).populate_existing().with_for_update().first()
        if parent is None or parent.workspace_id != data.workspace_id or parent.deleted_at is not None:
            from fastapi import HTTPException
            raise HTTPException(404, "父文档不存在")
    # 服务端权威算 hash：有正文算正文的，没正文用调用方给的，都没有算空串的
    if data.content is not None:
        data.content_hash = _hash_content(data.content)
    elif not data.content_hash:
        data.content_hash = _hash_content("")
    doc = create(db, data, commit=False)
    sync_wikilinks(db, doc, doc.content or "")
    db.commit()
    db.refresh(doc)
    return doc


@rollback_on_error
def update_document(db: Session, doc_id: UUID, data: DocumentUpdate, *, force_version: bool = False, source_edit: bool = False) -> Document:
    doc = lock_document(db, doc_id)
    if doc is None or doc.deleted_at is not None:
        raise ValueError("Document not found")
    from app.services.notes_templates import protected_ids
    if doc.id in protected_ids(db, doc.workspace_id) and data.model_fields_set & {'parent_id', 'is_folder', 'title'}:
        from fastapi import HTTPException
        raise HTTPException(409, {'code': 'protected_notes_folder', 'folder_id': str(doc.id)})
    if doc.updated_at != data.updated_at:
        raise ValueError("Conflict")
    # 循环引用防护：新父级不能是自己或自己的后代（A挂B下、B挂A下 → 树成环）
    if data.parent_id is not None:
        cur = get_by_id(db, data.parent_id)
        if cur is None or cur.workspace_id != doc.workspace_id or cur.deleted_at is not None:
            raise ValueError("Invalid parent")
        seen = {doc_id}
        while cur is not None:
            if cur.id in seen:
                raise ValueError("Circular parent")
            seen.add(cur.id)
            if cur.workspace_id != doc.workspace_id or cur.deleted_at is not None:
                raise ValueError("Invalid parent")
            cur = get_by_id(db, cur.parent_id) if cur.parent_id else None
    if 'parent_id' in data.model_fields_set:
        from app.services.web_projects import guard_project_move
        guard_project_move(db, doc, data.parent_id)
    from app.services.web_projects import guard_detached_update
    guard_detached_update(db, doc, data, source_edit=source_edit)
    # 正文变了 → 服务端重算 hash，不信前端算的
    if data.content is not None:
        data.content_hash = _hash_content(data.content)
    elif 'content_hash' in data.model_fields_set:
        data.content_hash = _hash_content(doc.content or '')
    previous_content = doc.content or ""
    previous_draft = doc.draft_content
    if data.content is not None and data.content != previous_content:
        from app.services.document_version import checkpoint_save
        checkpoint_save(db, doc, data.content, force=force_version)
    result = update(db, doc_id, data, commit=False)
    if result is None:
        db.rollback()
        raise ValueError("Conflict")
    if data.model_fields_set & {'title', 'parent_id'}:
        from app.services.web_projects import validate_ancestor_projects
        db.flush()
        validate_ancestor_projects(db, result)
    # Unknown draft provenance is never permission to clear another device's slot.
    if (data.content is not None and data.consumed_draft is not None
            and result.draft_updated_at == data.consumed_draft.draft_updated_at
            and result.draft_content is not None
            and _hash_content(result.draft_content) == data.consumed_draft.content_hash):
        result.draft_content = None
        result.draft_updated_at = None
        result.draft_device = None
    # 正文保存 → 同步双链（[[标题]] → document_links）
    if data.content is not None and not source_edit:
        sync_wikilinks(db, result, result.content or "")
        # 老婆的规则：正文不再引用的附件，连文件带记录删除
        if not force_version:
            from app.services.attachment_lifecycle import cleanup_unreferenced
            db.flush()  # Exact draft consumption must be visible to the reference scan.
            cleanup_unreferenced(db, result, result.content or "", previous_content=previous_content)
    from app.services.attachment_lifecycle import cleanup_detached_removed
    cleanup_detached_removed(db, result, previous_draft, result.draft_content)
    db.commit()
    from app.services.attachment_lifecycle import drain_file_gc
    drain_file_gc(db)
    db.refresh(result)
    return result


@rollback_on_error
def delete_document(db: Session, doc_id: UUID, cascade: bool = True, *, scope_token: str | None = None, user_id: UUID | None = None) -> str:
    """Idempotent trash intent; preserve existing trash timestamps."""
    from app.services.notes_lifecycle import lock_graph
    from app.services.notes_delete_scope import owned_tree, verify_scope
    lock_graph(db)
    workspace_id = db.query(Document.workspace_id).filter(Document.id == doc_id).scalar()
    tree = (owned_tree(db, workspace_id, user_id) if user_id is not None else locked_tree(db, workspace_id)) if workspace_id is not None else {}
    doc = tree.get(doc_id)
    if doc is None:
        raise ValueError("Document not found")
    from app.services.notes_templates import guard_protected
    guard_protected(db, [doc] + (subtree(tree, doc_id) if cascade else []))
    verify_scope(tree, workspace_id=workspace_id, doc_id=doc_id, mode='trash', cascade=cascade,
                 user_id=user_id, scope_token=scope_token)
    if doc.deleted_at is None:
        now = datetime.now()
        if cascade:
            for child in subtree(tree, doc_id):
                if child.deleted_at is None:
                    child.deleted_at = now
        else:
            for child in tree.values():
                if child.parent_id == doc_id:
                    from app.services.web_projects import guard_project_move
                    guard_project_move(db, child, doc.parent_id)
                    child.parent_id = doc.parent_id
        doc.deleted_at = now
    db.commit()
    return "trashed"


@rollback_on_error
def restore_document(db: Session, doc_id: UUID, cascade: bool = False) -> dict:
    """还原（老婆定的规则）：
    - 父页面不在了/也在回收站 → 挂回根级，标记 reattached
    - cascade=True：下挂的一起还原
    """
    doc = lock_document(db, doc_id)
    if doc is None or doc.deleted_at is None:
        raise ValueError("Document not found in trash")

    tree = locked_tree(db, doc.workspace_id)

    reattached = False
    if doc.parent_id is not None:
        parent = get_by_id(db, doc.parent_id)
        if parent is None or parent.deleted_at is not None:
            from app.services.web_projects import guard_project_move
            guard_project_move(db, doc, None)
            doc.parent_id = None
            reattached = True

    doc.deleted_at = None
    restored = 1
    if cascade:
        for d in subtree(tree, doc_id, only_deleted=True):
            d.deleted_at = None
            restored += 1
    db.commit()
    db.refresh(doc)
    return {"doc": doc, "reattached": reattached, "restored": restored}


@rollback_on_error
def finalize_documents(db, workspace_id, document_ids):
    from fastapi import HTTPException
    lock_workspace(db, workspace_id)
    ids = set(document_ids)
    if not 1 <= len(ids) <= 200:
        raise HTTPException(422, 'Invalid finalize batch size')
    docs = db.query(Document).filter(Document.id.in_(ids)).order_by(Document.id).populate_existing().with_for_update().all()
    if len(docs) != len(ids) or any(doc.workspace_id != workspace_id or doc.deleted_at is not None for doc in docs):
        raise HTTPException(404, '文档不存在')
    for doc in docs:
        sync_wikilinks(db, doc, doc.content or '')
    db.commit()
    return len(docs)


def sync_wikilinks(db: Session, doc: Document, content: str) -> None:
    """保存时同步双链：扫 [[标题]] → 全量替换该文档的出链（个人规模朴素重建即可）"""
    from urllib.parse import urlsplit, parse_qs
    from app.services.notes_zip import rewrite_markdown
    explicit = set()
    def collect(raw):
        try:
            url = urlsplit(raw)
            values = parse_qs(url.query).get('doc', [])
            if not url.scheme and not url.netloc and url.path == '/notes' and len(values) == 1:
                value = values[0]
                if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
                    explicit.add(UUID(value))
        except ValueError:
            pass
        return raw
    rewrite_markdown(content, collect)
    titles = [t.strip() for t in WIKILINK_RE.findall(content)]
    # 清掉旧出链
    for old in link_repo.get_links_for_doc(db, doc.id):
        if old.source_id == doc.id:
            link_repo.remove(db, old.source_id, old.target_id, commit=False)
    registered = set()
    for target in db.query(Document).filter(
        Document.workspace_id == doc.workspace_id, Document.deleted_at.is_(None),
        Document.id.in_(explicit), Document.id != doc.id,
    ).all():
        link_repo.create(db, DocumentLinkCreate(source_id=doc.id, target_id=target.id, link_type='ref'), commit=False)
        registered.add(target.id)
    # 按标题解析目标（同工作区、未删除、不是自己、同名取最新保存的）
    for title in dict.fromkeys(titles):  # 去重保序
        target = db.query(Document).filter(
            Document.workspace_id == doc.workspace_id,
            Document.title == title,
            Document.deleted_at.is_(None),
            Document.id != doc.id,
        ).order_by(Document.updated_at.desc()).first()
        if target and target.id not in registered:
            registered.add(target.id)
            link_repo.create(db, DocumentLinkCreate(
                source_id=doc.id, target_id=target.id, link_type="wiki",
            ), commit=False)


def get_backlinks(db: Session, doc_id: UUID) -> list[Document]:
    """Scoped backlink summaries, including both legacy-corrupt edge endpoints."""
    from app.models.document_link import DocumentLink
    from app.repositories.document import _SUMMARY_ONLY
    from sqlalchemy.orm import aliased
    target = aliased(Document)
    return db.query(Document).options(*_SUMMARY_ONLY).join(DocumentLink, DocumentLink.source_id == Document.id).join(target, target.id == DocumentLink.target_id).filter(
        target.id == doc_id, target.deleted_at.is_(None), Document.deleted_at.is_(None),
        Document.workspace_id == target.workspace_id).order_by(Document.updated_at.desc(), Document.id).all()


def touch_view(db: Session, doc_id: UUID) -> None:
    """打开页面 → 戳最近查看"""
    doc = get_by_id(db, doc_id)
    if doc is not None:
        doc.last_viewed_at = datetime.now()
        db.commit()


def list_recent_documents(db: Session, workspace_id: UUID, limit: int = 8) -> list[Document]:
    return list_recent(db, workspace_id, limit)


def _delete_set(db, docs, *, promote_children=False):
    """Preflight the entire set, then remove relationships and leaves in one UoW.

    Caller holds graph/tree/document locks and owns the only commit.
    """
    from fastapi import HTTPException
    from app.models.doc_tag import DocTag
    from app.models.document_link import DocumentLink
    from app.models.document_version import DocumentVersion
    from app.models.attachment import Attachment
    from app.models.config import AppConfig
    from app.models.workspace import Workspace
    from app.services.attachment_lifecycle import plan_document_release, delete_attachment, collect_detached
    from app.services.notes_lifecycle import postorder
    if not docs:
        return
    ids = {doc.id for doc in docs}
    from app.services.notes_templates import guard_protected
    guard_protected(db, docs)
    ordered = postorder(docs)
    children = db.query(Document).filter(Document.parent_id.in_(ids), Document.id.notin_(ids)).order_by(Document.id).populate_existing().with_for_update().all()
    if children and not promote_children:
        raise HTTPException(409, {'code': 'document_has_children', 'message': '删除集合外仍有子页，请明确选择级联或上移'})
    by_id = {doc.id: doc for doc in docs}
    for child in children:
        if child.workspace_id != by_id[child.parent_id].workspace_id:
            raise HTTPException(409, {'code': 'document_tree_invalid', 'message': '存在跨工作区子页'})
    attachments = db.query(Attachment).filter(Attachment.doc_id.in_(ids)).order_by(Attachment.id).with_for_update().all()
    retained = plan_document_release(db, attachments, excluding_docs=ids)
    # No writes above this line: conflict cannot leave half of a batch removed.
    for child in children:
        parent_id = child.parent_id
        while parent_id in by_id:
            parent_id = by_id[parent_id].parent_id
        from app.services.web_projects import guard_project_move
        guard_project_move(db, child, parent_id)
        child.parent_id = parent_id
    db.flush()
    owner_ids = [row[0] for row in db.query(Workspace.user_id).filter(Workspace.id.in_({doc.workspace_id for doc in docs})).all()]
    tag_ids = [row[0] for row in db.query(DocTag.tag_id).filter(DocTag.doc_id.in_(ids)).all()]
    db.query(DocTag).filter(DocTag.doc_id.in_(ids)).delete(synchronize_session=False)
    db.query(DocumentLink).filter((DocumentLink.source_id.in_(ids)) | (DocumentLink.target_id.in_(ids))).delete(synchronize_session=False)
    db.query(DocumentVersion).filter(DocumentVersion.doc_id.in_(ids)).delete(synchronize_session=False)
    for att in attachments:
        if att.id in retained:
            att.doc_id = None
        else:
            delete_attachment(db, att)
    db.query(AppConfig).filter(AppConfig.key.in_(['note-node:' + str(item) for item in ids])).delete(synchronize_session=False)
    project_keys = [prefix + str(item) for item in ids for prefix in ('web-project:', 'web-project-state:', 'web-project-source:')]
    db.query(AppConfig).filter(AppConfig.key.in_(project_keys)).delete(synchronize_session='fetch')
    # Do not clear receipts: stale upload retries must not resurrect deleted data.
    db.flush()
    for doc in ordered:
        db.delete(doc)
        db.flush()  # Immediate self-FK, so children must be gone before parents.
    for owner_id in set(owner_ids):
        collect_detached(db, owner_id)
    if tag_ids:
        from app.services.tag import purge_orphan_tags
        purge_orphan_tags(db, tag_ids, owner_ids=owner_ids)


@rollback_on_error
def _physical_delete(db: Session, doc: Document) -> None:
    """Compatibility wrapper for a single explicit purge; no partial commits."""
    permanently_delete_document(db, doc.id, cascade=False)


@rollback_on_error
def permanently_delete_document(db: Session, doc_id: UUID, cascade: bool = True, *, scope_token: str | None = None, user_id: UUID | None = None) -> None:
    from app.services.notes_lifecycle import lock_graph, locked_tree, subtree
    from app.services.notes_delete_scope import owned_tree, verify_scope
    lock_graph(db)
    workspace_id = db.query(Document.workspace_id).filter(Document.id == doc_id).scalar()
    if workspace_id is None:
        db.commit()
        return
    tree = owned_tree(db, workspace_id, user_id) if user_id is not None else locked_tree(db, workspace_id)
    doc = tree.get(doc_id)
    if doc is None:
        db.commit()
        return
    verify_scope(tree, workspace_id=workspace_id, doc_id=doc_id, mode='permanent', cascade=cascade,
                 user_id=user_id, scope_token=scope_token)
    docs = [doc] + (subtree(tree, doc.id) if cascade else [])
    _delete_set(db, docs, promote_children=not cascade)
    db.commit()
    from app.services.attachment_lifecycle import drain_file_gc
    drain_file_gc(db)


@rollback_on_error
def empty_trash(db: Session, workspace_id: UUID, *, scope_token: str | None = None, user_id: UUID | None = None) -> int:
    from app.services.notes_lifecycle import locked_tree
    from app.services.notes_delete_scope import owned_tree, verify_scope
    tree = owned_tree(db, workspace_id, user_id) if user_id is not None else locked_tree(db, workspace_id)
    verify_scope(tree, workspace_id=workspace_id, doc_id=None, mode='empty-trash', cascade=True,
                 user_id=user_id, scope_token=scope_token)
    doomed = [doc for doc in tree.values() if doc.deleted_at is not None]
    _delete_set(db, doomed)
    db.commit()
    from app.services.attachment_lifecycle import drain_file_gc
    drain_file_gc(db)
    return len(doomed)



@rollback_on_error
def clear_workspace_docs(db: Session, workspace_id: UUID) -> int:
    """清空笔记：工作区所有正常文档移入回收站（软删可还原，层级结构保留），返回篇数"""
    docs = [doc for doc in locked_tree(db, workspace_id).values() if doc.deleted_at is None]
    from app.services.notes_templates import guard_protected
    guard_protected(db, docs)
    now = datetime.now()
    for d in docs:
        d.deleted_at = now
    db.commit()
    return len(docs)


def list_trash_documents(db: Session, workspace_id: UUID) -> list[Document]:
    """Read-only: physical cleanup is an explicit owner-authorized intent."""
    return list_trash(db, workspace_id)


def search_documents(db: Session, workspace_id: UUID, keyword: str, limit: int = 50) -> list[Document]:
    return search(db, workspace_id, keyword, limit)


def save_draft(db: Session, doc_id: UUID, content: str, device: str) -> dict | None:
    """覆写活跃文档的单一草稿槽，成功提交后返回本次写入的标量回执。"""
    try:
        doc = lock_document(db, doc_id)
        if doc is None or doc.deleted_at is not None:
            db.rollback()  # Release the read transaction even on a missing/deleted document.
            return None
        previous_draft = doc.draft_content
        doc.draft_content = content
        doc.draft_updated_at = datetime.now()
        doc.draft_device = device
        # Snapshot while locked: a post-commit ORM refresh can see a later writer,
        # and would retain a new connection/transaction while the socket is idle.
        receipt = {
            "draft_updated_at": doc.draft_updated_at.isoformat(),
            "content_hash": _hash_content(content),
            "base_updated_at": doc.updated_at.isoformat(),
        }
        from app.services.attachment_lifecycle import cleanup_detached_removed
        cleanup_detached_removed(db, doc, previous_draft, content)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise


def is_draft_fresh(doc: Document) -> bool:
    """10 分钟内有过草稿同步才算「有一份未保存草稿」"""
    if doc.draft_updated_at is None:
        return False
    return (datetime.now() - doc.draft_updated_at).total_seconds() < DRAFT_TTL_SECONDS


def get_fresh_draft(db: Session, doc_id: UUID) -> Document | None:
    """取草稿：已删/过期的当不存在（惰性隐藏，不删数据）。"""
    doc = db.query(Document).filter(Document.id == doc_id).populate_existing().first()
    if doc is None or doc.deleted_at is not None or not is_draft_fresh(doc):
        return None
    return doc
