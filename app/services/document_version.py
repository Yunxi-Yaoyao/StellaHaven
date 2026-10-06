from datetime import datetime
from difflib import unified_diff
from uuid import UUID
from sqlalchemy.orm import Session
from app.repositories.document_version import get_by_id, list_by_document
from app.schemas.document_version import DocumentVersionCreate
from app.models.document_version import DocumentVersion
from app.models.document import Document

SNAPSHOT_SECONDS = 300
SNAPSHOT_CHARACTERS = 500


def content_diff(before: str, after: str) -> str:
    return '\n'.join(unified_diff(before.splitlines(), after.splitlines(), fromfile='version', tofile='current', lineterm=''))


def get_version(db: Session, version_id: UUID):
    return get_by_id(db, version_id)


def list_versions(db: Session, doc_id: UUID):
    return list_by_document(db, doc_id)


def latest_version(db, doc_id):
    return db.query(DocumentVersion).filter(DocumentVersion.doc_id == doc_id).order_by(DocumentVersion.version_no.desc()).first()


def add_checkpoint(db, doc_id, content, previous):
    version = DocumentVersion(doc_id=doc_id, content=content,
        diff=content_diff(previous.content if previous else '', content),
        version_no=previous.version_no + 1 if previous else 1, created_at=datetime.now())
    db.add(version)
    db.flush()
    return version


def checkpoint_save(db, doc, content, *, force=False):
    """Caller holds document row lock. No commit: snapshots and CAS save are atomic."""
    latest = latest_version(db, doc.id)
    initial = latest is None
    if initial or (force and latest.content != (doc.content or '')):
        latest = add_checkpoint(db, doc.id, doc.content or '', latest)
    if latest.content == content:
        return
    # Bound the comparison: no full diff on every key/save. A large replacement
    # qualifies even when it has the same length as the previous checkpoint.
    changed = abs(len(content) - len(latest.content))
    if changed < SNAPSHOT_CHARACTERS:
        for before, after in zip(latest.content, content):
            changed += before != after
            if changed >= SNAPSHOT_CHARACTERS:
                break
    age = (datetime.now() - latest.created_at).total_seconds()
    if initial or force or age >= SNAPSHOT_SECONDS or changed >= SNAPSHOT_CHARACTERS:
        add_checkpoint(db, doc.id, content, latest)


def create_version(db: Session, data: DocumentVersionCreate):
    doc = db.query(Document).filter(Document.id == data.doc_id).with_for_update().first()
    if doc is None or doc.deleted_at is not None:
        raise ValueError('Document not found')
    latest = latest_version(db, doc.id)
    version = add_checkpoint(db, doc.id, data.content, latest)
    db.commit(); db.refresh(version)
    return version
