"""Shared Notes transaction helpers. Never obtain an independent connection."""
from functools import wraps
from fastapi import HTTPException
from app.models.document import Document
from app.models.workspace import Workspace

MAX_TREE_DOCUMENTS = 5000


def lock_graph(db):
    # Global rather than owner-local: retained legacy users can reference these
    # objects too. Every reference-producing entry point must take this first.
    from app.services.notes_tools import lock_key
    lock_key(db, 'notes-reference-graph:v1')


def lock_workspace(db, workspace_id, *, graph_locked=False):
    if not graph_locked:
        lock_graph(db)
    from app.services.notes_tools import lock_key
    lock_key(db, 'document-tree:' + str(workspace_id))
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).populate_existing().first()
    if ws is None:
        raise HTTPException(404, '工作区不存在')
    return ws


def lock_document(db, doc_id):
    lock_graph(db)
    workspace_id = db.query(Document.workspace_id).filter(Document.id == doc_id).scalar()
    if workspace_id is None:
        return None
    lock_workspace(db, workspace_id, graph_locked=True)
    return db.query(Document).filter(Document.id == doc_id).populate_existing().with_for_update().first()


def locked_tree(db, workspace_id):
    from sqlalchemy.orm import defer
    lock_workspace(db, workspace_id)
    docs = db.query(Document).options(defer(Document.content), defer(Document.draft_content)).filter(
        Document.workspace_id == workspace_id).order_by(Document.id).limit(MAX_TREE_DOCUMENTS + 1).populate_existing().with_for_update().all()
    if len(docs) > MAX_TREE_DOCUMENTS:
        raise HTTPException(409, {'code': 'document_tree_check_incomplete', 'message': '工作区树超出同步操作预算'})
    by_id = {doc.id: doc for doc in docs}
    # Validate the complete graph before changing a parent or deleting any row.
    done = set()
    for doc in docs:
        path, cur = set(), doc
        while cur is not None and cur.id not in done:
            if cur.id in path or (cur.parent_id is not None and cur.parent_id not in by_id):
                raise HTTPException(409, {'code': 'document_tree_invalid', 'message': '文档树存在循环或跨工作区父级'})
            path.add(cur.id)
            cur = by_id.get(cur.parent_id)
        done.update(path)
    return by_id


def subtree(tree, root_id, *, only_deleted=False):
    children = {}
    for doc in tree.values():
        children.setdefault(doc.parent_id, []).append(doc)
    result, queue = [], [root_id]
    while queue:
        current = queue.pop()
        for child in children.get(current, ()):
            if not only_deleted or child.deleted_at is not None:
                result.append(child)
                queue.append(child.id)
    return result


def postorder(docs):
    by_id = {doc.id: doc for doc in docs}
    counts = {key: 0 for key in by_id}
    for doc in docs:
        if doc.parent_id in counts:
            counts[doc.parent_id] += 1
    leaves = sorted((key for key, count in counts.items() if count == 0), key=str)
    ordered = []
    while leaves:
        key = leaves.pop()
        doc = by_id[key]
        ordered.append(doc)
        if doc.parent_id in counts:
            counts[doc.parent_id] -= 1
            if counts[doc.parent_id] == 0:
                leaves.append(doc.parent_id)
    if len(ordered) != len(docs):
        raise HTTPException(409, {'code': 'document_tree_invalid', 'message': '文档树存在循环'})
    return ordered


def rollback_on_error(func):
    @wraps(func)
    def wrapped(db, *args, **kwargs):
        try:
            return func(db, *args, **kwargs)
        except Exception:
            db.rollback()
            raise
    return wrapped
