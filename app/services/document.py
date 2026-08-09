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


def create_document(db: Session, data: DocumentCreate) -> Document:
    # 服务端权威算 hash：有正文算正文的，没正文用调用方给的，都没有算空串的
    if data.content is not None:
        data.content_hash = _hash_content(data.content)
    elif not data.content_hash:
        data.content_hash = _hash_content("")
    return create(db, data)


def update_document(db: Session, doc_id: UUID, data: DocumentUpdate) -> Document:
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
    # 循环引用防护：新父级不能是自己或自己的后代（A挂B下、B挂A下 → 树成环）
    if data.parent_id is not None:
        cur = get_by_id(db, data.parent_id)
        while cur is not None:
            if cur.id == doc_id:
                raise ValueError("Circular parent")
            cur = get_by_id(db, cur.parent_id) if cur.parent_id else None
    # 正文变了 → 服务端重算 hash，不信前端算的
    if data.content is not None:
        data.content_hash = _hash_content(data.content)
    result = update(db, doc_id, data)
    if result is None:
        raise ValueError("Conflict")
    # 手动保存成功 → 草稿槽清空（草稿已被 promote 成正文）
    result.draft_content = None
    result.draft_updated_at = None
    result.draft_device = None
    db.commit()
    db.refresh(result)
    # 正文保存 → 同步双链（[[标题]] → document_links）
    if data.content is not None:
        sync_wikilinks(db, result, result.content or "")
    return result


def delete_document(db: Session, doc_id: UUID, cascade: bool = True) -> str:
    """两级删除 + 级联策略（老婆定的规则）：
    - 正常文档 → 软删。cascade=True：下挂一起进回收站；cascade=False：子页上移一级再删
    - 已在回收站的 → 物理删除（只删自己）
    """
    doc = get_by_id(db, doc_id)
    if doc is None:
        raise ValueError("Document not found")
    if doc.deleted_at is None:
        now = datetime.now()
        if cascade:
            for d in descendants_of(db, doc_id):
                d.deleted_at = now
        else:
            # 子页上移一级（挂到被删页面的父级下）
            for kid in children_of(db, doc_id):
                kid.parent_id = doc.parent_id
        doc.deleted_at = now
        db.commit()
        return "trashed"
    _physical_delete(db, doc)
    return "purged"


def restore_document(db: Session, doc_id: UUID, cascade: bool = False) -> dict:
    """还原（老婆定的规则）：
    - 父页面不在了/也在回收站 → 挂回根级，标记 reattached
    - cascade=True：下挂的一起还原
    """
    doc = get_by_id(db, doc_id)
    if doc is None or doc.deleted_at is None:
        raise ValueError("Document not found in trash")

    reattached = False
    if doc.parent_id is not None:
        parent = get_by_id(db, doc.parent_id)
        if parent is None or parent.deleted_at is not None:
            doc.parent_id = None
            reattached = True

    doc.deleted_at = None
    restored = 1
    if cascade:
        for d in descendants_of(db, doc_id, only_deleted=True):
            d.deleted_at = None
            restored += 1
    db.commit()
    db.refresh(doc)
    return {"doc": doc, "reattached": reattached, "restored": restored}


def sync_wikilinks(db: Session, doc: Document, content: str) -> None:
    """保存时同步双链：扫 [[标题]] → 全量替换该文档的出链（个人规模朴素重建即可）"""
    titles = [t.strip() for t in WIKILINK_RE.findall(content)]
    # 清掉旧出链
    for old in link_repo.get_links_for_doc(db, doc.id):
        if old.source_id == doc.id:
            link_repo.remove(db, old.source_id, old.target_id)
    # 按标题解析目标（同工作区、未删除、不是自己、同名取最新保存的）
    for title in dict.fromkeys(titles):  # 去重保序
        target = db.query(Document).filter(
            Document.workspace_id == doc.workspace_id,
            Document.title == title,
            Document.deleted_at.is_(None),
            Document.id != doc.id,
        ).order_by(Document.updated_at.desc()).first()
        if target:
            link_repo.create(db, DocumentLinkCreate(
                source_id=doc.id, target_id=target.id, link_type="wiki",
            ))


def get_backlinks(db: Session, doc_id: UUID) -> list[Document]:
    """反链：哪些页面链接到了我"""
    links = link_repo.get_links_for_doc(db, doc_id)
    result = []
    for l in links:
        if l.target_id == doc_id:
            src = get_by_id(db, l.source_id)
            if src and src.deleted_at is None:
                result.append(src)
    return result


def touch_view(db: Session, doc_id: UUID) -> None:
    """打开页面 → 戳最近查看"""
    doc = get_by_id(db, doc_id)
    if doc is not None:
        doc.last_viewed_at = datetime.now()
        db.commit()


def list_recent_documents(db: Session, workspace_id: UUID, limit: int = 8) -> list[Document]:
    return list_recent(db, workspace_id, limit)


def _physical_delete(db: Session, doc: Document) -> None:
    """物理删除一篇文档 + 清理关联（标签/双链/版本），不留孤儿"""
    from app.models.doc_tag import DocTag
    from app.models.document_link import DocumentLink
    from app.models.document_version import DocumentVersion
    db.query(DocTag).filter(DocTag.doc_id == doc.id).delete(synchronize_session=False)
    db.query(DocumentLink).filter(
        (DocumentLink.source_id == doc.id) | (DocumentLink.target_id == doc.id)
    ).delete(synchronize_session=False)
    db.query(DocumentVersion).filter(DocumentVersion.doc_id == doc.id).delete(synchronize_session=False)
    delete(db, doc)


def empty_trash(db: Session, workspace_id: UUID) -> int:
    """一键清空回收站：物理删除该工作区所有已软删文档，返回清了几篇"""
    doomed = db.query(Document).filter(
        Document.workspace_id == workspace_id,
        Document.deleted_at.isnot(None),
    ).all()
    n = len(doomed)
    for d in doomed:
        _physical_delete(db, d)
    return n


def list_trash_documents(db: Session, workspace_id: UUID) -> list[Document]:
    """看回收站 = 惰性清理时机：先顺手清掉过期的，再返回剩下的"""
    purge_expired_trash(db, TRASH_RETENTION_DAYS)
    return list_trash(db, workspace_id)


def search_documents(db: Session, workspace_id: UUID, keyword: str, limit: int = 50) -> list[Document]:
    return search(db, workspace_id, keyword, limit)


def save_draft(db: Session, doc_id: UUID, content: str, device: str) -> Document | None:
    """覆写草稿槽。不追加、不留历史，永远只有最新一份。"""
    doc = get_by_id(db, doc_id)
    if doc is None:
        db.rollback()  # ⚠️ 必须显式收尾：SELECT 会占着事务/连接，不 rollback 连接就泄漏（WS 长连接场景池子会被榨干）
        return None
    doc.draft_content = content
    doc.draft_updated_at = datetime.now()
    doc.draft_device = device
    db.commit()
    return doc


def is_draft_fresh(doc: Document) -> bool:
    """10 分钟内有过草稿同步才算「有一份未保存草稿」"""
    if doc.draft_updated_at is None:
        return False
    return (datetime.now() - doc.draft_updated_at).total_seconds() < DRAFT_TTL_SECONDS


def get_fresh_draft(db: Session, doc_id: UUID) -> Document | None:
    """取草稿：过期的当不存在（惰性隐藏，不删数据）"""
    doc = get_by_id(db, doc_id)
    if doc is None or not is_draft_fresh(doc):
        return None
    return doc
