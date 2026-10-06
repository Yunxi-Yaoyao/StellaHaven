"""Workspace inbox and note/node associations. Writes only on explicit requests."""
import json
from hashlib import sha256
from uuid import UUID, uuid4
from sqlalchemy import text
from app.models.config import AppConfig
from app.models.document import Document
from app.services.document import create_document
from app.schemas.document import DocumentCreate


def lock_key(db, key):
    if db.get_bind().dialect.name == 'postgresql':
        number = int.from_bytes(sha256(key.encode()).digest()[:8], 'big', signed=True)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': number})


def config_write(db, key, value):
    row = db.get(AppConfig, key)
    if row is None:
        row = AppConfig(key=key, value=value); db.add(row)
    else:
        row.value = value
    return row


def inbox_for_write(db, workspace_id):
    key = 'notes-inbox:' + str(workspace_id)
    lock_key(db, key)
    row = db.get(AppConfig, key)
    folder = None
    if row:
        try:
            folder = db.get(Document, UUID(row.value))
        except ValueError:
            pass
    if not folder or folder.workspace_id != workspace_id or folder.deleted_at is not None or not folder.is_folder:
        folder = Document(id=uuid4(), title='快捷记录收件箱', file_path='/system/quick-record-inbox',
            workspace_id=workspace_id, content='', content_hash=sha256(b'').hexdigest(), is_folder=True)
        db.add(folder); db.flush()
        config_write(db, key, str(folder.id))
    db.commit(); db.refresh(folder)
    return folder


def quick_record(db, workspace_id, title, content):
    folder = inbox_for_write(db, workspace_id)
    return create_document(db, DocumentCreate(workspace_id=workspace_id, parent_id=folder.id,
        title=title, content=content, file_path='/quick-record/' + str(uuid4()) + '.md'))


def note_node(db, doc_id):
    row = db.get(AppConfig, 'note-node:' + str(doc_id))
    if row is None:
        return None
    try:
        value = json.loads(row.value)
        return value['node_id'] if isinstance(value.get('node_id'), int) else None
    except (ValueError, TypeError, KeyError):
        return None


def set_note_node(db, doc_id, node_id):
    key = 'note-node:' + str(doc_id)
    lock_key(db, key)
    row = db.get(AppConfig, key)
    if node_id is None:
        if row is not None:
            db.delete(row)
    else:
        config_write(db, key, json.dumps({'node_id': node_id}))
    db.commit()
