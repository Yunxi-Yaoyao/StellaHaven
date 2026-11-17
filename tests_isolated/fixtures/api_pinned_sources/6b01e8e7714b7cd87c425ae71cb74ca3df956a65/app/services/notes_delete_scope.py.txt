"""Read-only deletion plans and bounded, non-authorizing scope fingerprints.

All decisions use the caller's graph/tree transaction. Tokens are comparison
values, not capabilities: owner authorization must always be checked anew.
"""
import hashlib
import hmac
import json
import time
from typing import NoReturn
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.services.notes_lifecycle import lock_workspace, locked_tree, subtree

SCOPE_TTL_SECONDS = 600
PREVIEW_LOCK_TIMEOUT_MS = 1500
PREVIEW_STATEMENT_TIMEOUT_MS = 5000


def scope_changed() -> NoReturn:
    raise HTTPException(409, {'code': 'delete_scope_changed', 'message': '删除范围已变化或确认已过期，请重新预检并确认'})


def owned_tree(db, workspace_id, user_id):
    ws = lock_workspace(db, workspace_id)
    if ws.user_id != user_id:
        raise HTTPException(404, '工作区不存在')
    return locked_tree(db, workspace_id)


def scope_data(tree, *, workspace_id, doc_id, mode, cascade):
    if mode == 'empty-trash':
        targets = [doc.id for doc in tree.values() if doc.deleted_at is not None]
        descendant_count = 0
    else:
        if doc_id not in tree:
            raise HTTPException(404, '文档不存在')
        descendants = subtree(tree, doc_id)
        descendant_count = len(descendants)
        targets = [doc_id] + ([doc.id for doc in descendants] if cascade else [])
    return dict(workspace_id=workspace_id, doc_id=doc_id, mode=mode, cascade=cascade,
                target_ids=sorted(targets, key=str), descendant_count=descendant_count)


def _fingerprint(tree, data, user_id, issued_at):
    # No titles, bodies, draft contents, or secrets enter the token. Whole-tree
    # topology intentionally errs on the conservative side for non-cascade moves.
    topology = [(str(doc.id), str(doc.parent_id), str(doc.created_at), str(doc.deleted_at))
                for doc in sorted(tree.values(), key=lambda item: str(item.id))]
    encoded = json.dumps([user_id, issued_at, data, topology], default=str,
                         sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def token_for(tree, data, user_id):
    issued_at = int(time.time())
    return f'v1.{issued_at}.{_fingerprint(tree, data, user_id, issued_at)}'


def verify_scope(tree, *, workspace_id, doc_id, mode, cascade, user_id, scope_token):
    if scope_token is None:
        return
    if user_id is None or len(scope_token) > 128 or not scope_token.isascii():
        scope_changed()
    try:
        version, stamp, digest = scope_token.split('.')
        issued_at = int(stamp)
        if version != 'v1' or not 0 <= time.time() - issued_at <= SCOPE_TTL_SECONDS:
            scope_changed()
    except (ValueError, TypeError):
        scope_changed()
    data = scope_data(tree, workspace_id=workspace_id, doc_id=doc_id, mode=mode, cascade=cascade)
    if not hmac.compare_digest(scope_token, f'v1.{issued_at}.{_fingerprint(tree, data, user_id, issued_at)}'):
        scope_changed()


def preview_delete(db, data, user_id):
    try:
        if db.get_bind().dialect.name == 'postgresql':
            # Transaction-local budgets: rollback also restores pool settings.
            db.execute(text("SELECT set_config('lock_timeout', :budget, true)"),
                       {'budget': f'{PREVIEW_LOCK_TIMEOUT_MS}ms'})
            db.execute(text("SELECT set_config('statement_timeout', :budget, true)"),
                       {'budget': f'{PREVIEW_STATEMENT_TIMEOUT_MS}ms'})
        tree = owned_tree(db, data.workspace_id, user_id)
        result = scope_data(tree, workspace_id=data.workspace_id, doc_id=data.doc_id,
                            mode=data.mode, cascade=data.cascade)
        return dict(result, scope_token=token_for(tree, result, user_id))
    except DBAPIError as exc:
        code = getattr(exc.orig, 'pgcode', None) or getattr(exc.orig, 'sqlstate', None) or ''
        if code in ('55P03', '57014') or code.startswith('08') or exc.connection_invalidated:
            raise HTTPException(409, {'code': 'document_tree_check_incomplete',
                'message': '未能完整读取删除范围，请稍后重新预检'}) from None
        raise
    finally:
        # No receipt, no database write, no commit and no retained locks.
        db.rollback()
