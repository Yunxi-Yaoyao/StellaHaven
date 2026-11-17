"""Attachment reference checks and transaction-local deletion.

Only references removed from this save are GC candidates. Pending uploads have
no implicit expiry policy. All legacy users/workspaces are scanned; diagnostics
never expose their IDs or titles. Limits are safety budgets, not retention TTLs.
"""
import html
import json
import logging
import re
from urllib.parse import unquote
from uuid import UUID
from sqlalchemy import func, and_, or_
from fastapi import HTTPException
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.attachment import Attachment
from app.models.config import AppConfig
from app.services import blob_store

log = logging.getLogger(__name__)
MAX_REFERENCE_ROWS = 20000
MAX_REFERENCE_CHARS = 32 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024
ATTACH_REF_RE = re.compile(r'/attachments/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})', re.I)


def references(content):
    text = content or ''
    if len(text) > MAX_TEXT_CHARS:
        return set(), True
    # Conservative superset: plain text, code, HTML, absolute/encoded URLs.
    for _ in range(3):
        decoded = html.unescape(unquote(text))
        if decoded == text:
            break
        text = decoded
    ids = {UUID(match) for match in ATTACH_REF_RE.findall(text)}
    remaining = ATTACH_REF_RE.sub('', text).lower()
    unknown = '/attachments/' in remaining or '%2fattachments' in remaining
    return ids, unknown


def referenced_candidates(db, candidates, *, excluding_docs=()):
    """Return protected IDs and whether the bounded full scan was inconclusive."""
    candidates = set(candidates)
    if not candidates:
        return set(), False
    excluded = set(excluding_docs)
    found, rows, chars = set(), 0, 0
    # Bound each DB result value before materializing large text into Python.
    queries = [
        db.query(Document.id, func.substr(Document.content, 1, MAX_TEXT_CHARS + 1),
                 func.substr(Document.draft_content, 1, MAX_TEXT_CHARS + 1))
          .filter(Document.id.notin_(excluded)).order_by(Document.id),
        db.query(DocumentVersion.doc_id, func.substr(DocumentVersion.content, 1, MAX_TEXT_CHARS + 1))
          .filter(DocumentVersion.doc_id.notin_(excluded)).order_by(DocumentVersion.id),
    ]
    for query in queries:
        for row in query.limit(MAX_REFERENCE_ROWS + 1).yield_per(64):
            rows += 1
            if rows > MAX_REFERENCE_ROWS:
                return found, True
            for value in row[1:]:
                chars += len(value or '')
                if chars > MAX_REFERENCE_CHARS:
                    return found, True
                refs, unknown = references(value)
                found.update(candidates & refs)
                if unknown:
                    return found, True
    return found, False


def preflight_delete(db, attachments, *, excluding_docs=()):
    found, unknown = referenced_candidates(db, [a.id for a in attachments], excluding_docs=excluding_docs)
    if found or unknown:
        # No third-party title/ID/ownership disclosure.
        raise HTTPException(409, {'code': 'attachment_in_use' if found else 'attachment_reference_check_incomplete',
                                  'message': '附件仍被删除集合外内容引用，或引用检查未能完成'})


def delete_attachment(db, att):
    """No commit or filesystem unlink here. File intent survives process failure."""
    if blob_store.enabled():
        blob_store.delete(db, 'attachments/' + str(att.id))
    else:
        key = 'notes-file-gc:' + str(att.id)
        if db.get(AppConfig, key) is None:
            db.add(AppConfig(key=key, value=json.dumps({'attachment_id': str(att.id), 'attempts': 0, 'state': 'pending'})))
    db.delete(att)


def plan_document_release(db, attachments, *, excluding_docs):
    """Read-only plan under graph lock: ordinary attachments still fail closed.

    Only server-marked project objects may detach. Their pinned owner must still
    match the source workspace; an ownership mismatch is not a transfer grant.
    Inconclusive scans retain all project objects rather than deleting bytes.
    Every actual hard-delete candidate still passes the unchanged preflight.
    """
    from app.models.workspace import Workspace
    projects = [att for att in attachments if att.owner_id is not None]
    for att in projects:
        owner = db.query(Workspace.user_id).join(Document, Document.workspace_id == Workspace.id).filter(Document.id == att.doc_id).scalar()
        if owner != att.owner_id:
            raise HTTPException(409, {'code': 'attachment_owner_mismatch', 'message': '附件归属检查未通过'})
    found, unknown = referenced_candidates(db, [a.id for a in projects], excluding_docs=excluding_docs)
    retained = {a.id for a in projects if unknown or a.id in found}
    preflight_delete(db, [a for a in attachments if a.id not in retained], excluding_docs=excluding_docs)
    return retained


def collect_detached(db, owner_id, *, candidates=None, after_id=None, limit=128):
    """Owner-scoped bounded GC; caller commits. No pending ordinary uploads.

    Explicit maintenance callers can page by UUID using after_id; an incomplete
    reference scan never authorizes deletion. Graph lock fences all note writers.
    """
    from app.services.notes_lifecycle import lock_graph
    lock_graph(db)
    db.flush()
    query = db.query(Attachment).filter(Attachment.doc_id.is_(None), Attachment.owner_id == owner_id)
    if candidates is not None:
        query = query.filter(Attachment.id.in_(candidates))
    if after_id is not None:
        query = query.filter(Attachment.id > after_id)
    rows = query.order_by(Attachment.id).limit(min(max(limit, 1), 128)).populate_existing().with_for_update().all()
    found, unknown = referenced_candidates(db, [a.id for a in rows])
    removable = [] if unknown else [a for a in rows if a.id not in found]
    preflight_delete(db, removable)
    for att in removable:
        delete_attachment(db, att)
    return {'scanned': len(rows), 'removed': len(removable), 'after_id': rows[-1].id if rows else None, 'incomplete': unknown}


def cleanup_detached_removed(db, doc, previous_content, content):
    """Draft-slot changes must never change ordinary upload GC semantics."""
    before, unknown_before = references(previous_content)
    after, unknown_after = references(content)
    if unknown_before or unknown_after or not before - after:
        return
    from app.models.workspace import Workspace
    owner_id = db.query(Workspace.user_id).filter(Workspace.id == doc.workspace_id).scalar()
    collect_detached(db, owner_id, candidates=before - after)


def cleanup_unreferenced(db, doc, content, *, previous_content=None):
    # Legacy callers without the old body cannot distinguish pending from removed.
    before, unknown_before = references(previous_content)
    after, unknown_after = references(content)
    if unknown_before or unknown_after:
        log.warning('notes_attachment_gc_deferred: ambiguous content')
        return 0
    candidates = before - after
    if not candidates:
        return 0
    from app.models.workspace import Workspace
    owner_id = db.query(Workspace.user_id).filter(Workspace.id == doc.workspace_id).scalar()
    attachments = db.query(Attachment).filter(
        or_(and_(Attachment.doc_id == doc.id, Attachment.owner_id.is_(None)),
            and_(Attachment.doc_id.is_(None), Attachment.owner_id == owner_id)),
        Attachment.id.in_(candidates)).order_by(Attachment.id).with_for_update().all()
    found, unknown = referenced_candidates(db, [a.id for a in attachments])
    if unknown:
        log.warning('notes_attachment_gc_deferred: reference scan incomplete')
        return 0
    removed = 0
    for att in attachments:
        if att.id not in found:
            delete_attachment(db, att)
            removed += 1
    return removed


def drain_file_gc(db, *, storage=None, limit=32, object_ids=None):
    """Bounded post-commit retry. Never turn committed deletion into HTTP failure.

    UUID object keys are never reused. Incomplete/corrupt intents remain evidence;
    a live metadata row always prevents unlink. No directory-wide orphan sweep.
    """
    if blob_store.enabled():
        return
    from pathlib import Path
    from app.services.notes_lifecycle import lock_graph
    if storage is None:
        storage = Path(__file__).resolve().parents[2] / 'data' / 'attachments'
    try:
        lock_graph(db)
        query = db.query(AppConfig).filter(AppConfig.key.startswith('notes-file-gc:'))
        if object_ids is not None:
            # ZIP failure compensation must not drain another operation's work.
            query = query.filter(AppConfig.key.in_(['notes-file-gc:' + str(i) for i in object_ids]))
        rows = query.order_by(AppConfig.key).limit(min(max(limit, 1), 32)).populate_existing().with_for_update().all()
        for row in rows:
            try:
                intent = json.loads(row.value)
                att_id = UUID(intent['attachment_id'])
                if row.key != 'notes-file-gc:' + str(att_id):
                    raise ValueError('Mismatched object key')
                if db.get(Attachment, att_id) is not None:
                    intent['state'] = 'blocked_live_metadata'
                    row.value = json.dumps(intent)
                    continue
                if intent.get('source') == 'notes-zip':
                    found, unknown = referenced_candidates(db, [att_id])
                    if found or unknown:
                        intent['state'] = 'blocked_references'
                        row.value = json.dumps(intent)
                        continue
                (storage / str(att_id)).unlink(missing_ok=True)
                db.delete(row)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                # Keep only non-sensitive failure class, never absolute paths.
                try:
                    previous = json.loads(row.value)
                except (ValueError, TypeError):
                    previous = {}
                if not isinstance(previous, dict):
                    previous = {}
                previous.update(state='retry', attempts=int(previous.get('attempts', 0)) + 1, error=type(exc).__name__)
                row.value = json.dumps(previous)
                log.warning('notes_file_gc_retry key=%s failure=%s', row.key, type(exc).__name__)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.error('notes_file_gc_deferred failure=%s', type(exc).__name__)


def delete_attachments_of(db, doc_id):
    attachments = db.query(Attachment).filter(Attachment.doc_id == doc_id).order_by(Attachment.id).with_for_update().all()
    retained = plan_document_release(db, attachments, excluding_docs={doc_id})
    for att in attachments:
        if att.id in retained:
            att.doc_id = None
        else:
            delete_attachment(db, att)
