"""Server-owned template directory and transactional independent copies.

AppConfig identities are not writable through document/frontmatter APIs.
All writers share the document graph/workspace fence. No read seeds data.
"""
import io
import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import HTTPException
from app.models.config import AppConfig
from app.models.document import Document
from app.models.attachment import Attachment
from app.services.notes_lifecycle import lock_workspace, locked_tree, rollback_on_error

PREFIX = 'notes-template-root:'
BUILTINS = [
    ('文章模板', '> 摘要：填写本文主题和适用场景。\n\n## 核心结论\n\n\n## 原理与概念\n\n\n## 操作或示例\n\n\n## 验证结果\n\n\n## 关联阅读\n\n\n## 参考资料\n\n\n## 待办\n\n- [ ] 补充并验证内容\n'),
    ('事件记录模板', '> 时间：\n> 环境：\n> 状态：待确认\n\n## 现象与影响\n\n\n## 时间线\n\n| 时间 | 事件与证据 |\n| --- | --- |\n| | |\n\n## 定位与根因\n\n\n## 处理过程\n\n\n## 验证结果\n\n- [ ] 功能恢复\n- [ ] 日志与监控确认\n\n## 回滚方案\n\n\n## 后续行动\n\n- [ ] \n\n## 参考与关联\n\n'),
]


def protected_ids(db, workspace_id):
    row = db.get(AppConfig, PREFIX + str(workspace_id))
    return {UUID(row.value)} if row else set()


def guard_protected(db, docs):
    for doc in docs:
        if doc.id in protected_ids(db, doc.workspace_id):
            raise HTTPException(409, {'code': 'protected_notes_folder', 'folder_id': str(doc.id),
                                      'message': '内置目录不可删除，请在笔记设置中隐藏'})


def descendants(tree, root):
    result = set()
    for doc in tree.values():
        current, seen = doc, set()
        while current and current.id not in seen and current.deleted_at is None:
            if current.parent_id == root:
                result.add(doc.id)
                break
            seen.add(current.id)
            current = tree.get(current.parent_id)
    return result


def new_doc(db, workspace, parent, title, content='', folder=False):
    doc = Document(id=uuid4(), workspace_id=workspace, parent_id=parent, title=title,
                   file_path='/notes/' + str(uuid4()), content=content,
                   content_hash=sha256(content.encode()).hexdigest(), is_folder=folder)
    db.add(doc)
    db.flush()
    return doc


def independent_copy(db, source, parent, title):
    from app.services import blob_store
    from app.services.attachment_lifecycle import references
    from app.services.attachment_files import publish
    content = source.content or ''
    refs, unknown = references(content)
    if unknown:
        raise HTTPException(409, '附件引用无法安全复制，请修正后重试')
    doc = new_doc(db, source.workspace_id, parent, title)
    # Rewriting encoded/HTML forms without changing other text is ambiguous.
    # Fail visibly rather than silently retaining unsafe references.
    literal = {UUID(v) for v in re.findall(r'/attachments/([0-9a-fA-F-]{36})', content)}
    if refs != literal:
        raise HTTPException(409, '编码附件引用需先改为标准附件地址')
    storage = Path(__file__).resolve().parents[2] / 'data' / 'attachments'
    total = 0
    for aid in sorted(refs):
        att = db.get(Attachment, aid)
        owner = db.get(Document, att.doc_id) if att and att.doc_id is not None else None
        if att and att.owner_id is not None:
            from app.models.workspace import Workspace
            workspace = db.get(Workspace, source.workspace_id)
            accessible = (workspace is not None and workspace.user_id == att.owner_id
                          and (att.doc_id is None or (owner is not None and owner.workspace_id == source.workspace_id)))
        else:
            # Ordinary attachments retain the original same-workspace rule.
            accessible = owner is not None and owner.workspace_id == source.workspace_id
        if not accessible:
            raise HTTPException(409, '附件不可访问，未复制模板')
        total += att.size
        if total > 64 * 1024 * 1024:
            raise HTTPException(413, '模板附件总量超过 64 MiB')
        key = 'attachments/' + str(aid)
        if blob_store.enabled():
            meta = blob_store.metadata(db, key)
            if not meta or meta['size'] != att.size:
                raise HTTPException(409, '附件文件缺失，未复制模板')
            data = b''.join(blob_store.read_range(db, key, 0, att.size))
        else:
            try:
                data = (storage / str(aid)).read_bytes()
            except OSError as exc:
                raise HTTPException(409, '附件文件缺失，未复制模板') from exc
        if len(data) != att.size:
            raise HTTPException(409, '附件文件不完整，未复制模板')
        copied = Attachment(id=uuid4(), doc_id=doc.id, filename=att.filename, mime=att.mime, size=att.size)
        db.add(copied)
        if blob_store.enabled():
            blob_store.put(db, 'attachments/' + str(copied.id), io.BytesIO(data), att.mime, max_bytes=64 * 1024 * 1024)
        else:
            # Unique publish before commit: uncertain commit never unlinks live data.
            publish(storage, copied.id, data)
        content = re.sub(r'(/attachments/)' + re.escape(str(aid)), lambda m: m[1] + str(copied.id), content, flags=re.I)
    doc.content = content
    doc.content_hash = sha256(content.encode()).hexdigest()
    from app.services.document import sync_wikilinks
    sync_wikilinks(db, doc, content)
    return doc


@rollback_on_error
def initialize(db, workspace_id):
    lock_workspace(db, workspace_id)
    key = PREFIX + str(workspace_id)
    row = db.get(AppConfig, key)
    if row:
        db.commit()
        return UUID(row.value)
    from app.models.tag import Tag
    from app.models.doc_tag import DocTag
    root = new_doc(db, workspace_id, None, '模板', folder=True)
    db.add(AppConfig(key=key, value=str(root.id)))
    for title, content in BUILTINS:
        new_doc(db, workspace_id, root.id, title, content)
    originals = db.query(Document).join(DocTag, DocTag.doc_id == Document.id).join(Tag, Tag.id == DocTag.tag_id).filter(
        Document.workspace_id == workspace_id, Document.deleted_at.is_(None), Document.is_folder.is_(False), Tag.name == '模板').order_by(Document.id).all()
    for source in originals:
        independent_copy(db, source, root.id, source.title)
    db.commit()
    return root.id


@rollback_on_error
def copy_into_templates(db, workspace_id, source_id):
    root_id = initialize(db, workspace_id)
    lock_workspace(db, workspace_id)
    tree = locked_tree(db, workspace_id)
    source = tree.get(source_id)
    if source is None or source.deleted_at is not None or source.is_folder:
        raise HTTPException(404, '笔记不存在')
    doc = independent_copy(db, source, root_id, source.title)
    db.commit()
    db.refresh(doc)
    return doc


def catalog(db, workspace_id):
    tree = {d.id: d for d in db.query(Document).filter(Document.workspace_id == workspace_id).all()}
    roots = protected_ids(db, workspace_id)
    root = next(iter(roots), None)
    valid = descendants(tree, root) if root else set()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    usage = db.get(AppConfig, 'notes-template-usage:' + str(workspace_id))
    events = json.loads(usage.value) if usage else []
    scores = {}
    for tid, stamp in events:
        if stamp >= cutoff:
            count, last = scores.get(tid, (0, ''))
            scores[tid] = (count + 1, max(last, stamp))
    notes = [d for d in tree.values() if d.id in valid and not d.is_folder]
    recent = sorted([d for d in notes if str(d.id) in scores], key=lambda d: (scores[str(d.id)], str(d.id)), reverse=True)[:2]
    return {'root_id': str(root) if root else None,
            'items': [{'id': str(d.id), 'parent_id': str(d.parent_id), 'title': d.title, 'is_folder': d.is_folder} for d in tree.values() if d.id in valid],
            'recent_ids': [str(d.id) for d in recent]}


@rollback_on_error
def create_from_template(db, workspace_id, template_id, parent_id, title):
    lock_workspace(db, workspace_id)
    tree = locked_tree(db, workspace_id)
    roots = protected_ids(db, workspace_id)
    root = next(iter(roots), None)
    valid = descendants(tree, root) if root else set()
    source = tree.get(template_id)
    if not source or template_id not in valid or source.is_folder:
        raise HTTPException(409, '模板已移出目录或删除，请重新选择')
    if parent_id is not None and (parent_id not in tree or tree[parent_id].deleted_at is not None):
        raise HTTPException(404, '目标目录不存在')
    if parent_id in valid or parent_id in roots:
        raise HTTPException(409, '新文章必须创建在模板目录之外')
    doc = independent_copy(db, source, parent_id, title)
    key = 'notes-template-usage:' + str(workspace_id)
    row = db.get(AppConfig, key)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    events = [e for e in json.loads(row.value) if e[1] >= cutoff] if row else []
    events.append([str(template_id), datetime.now(timezone.utc).isoformat()])
    if row:
        row.value = json.dumps(events)
    else:
        db.add(AppConfig(key=key, value=json.dumps(events)))
    db.commit()
    db.refresh(doc)
    return doc
