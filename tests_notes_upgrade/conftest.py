"""Isolated notes contracts: no main, settings, PostgreSQL or side effects."""
import sys
import types
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

class Base(DeclarativeBase):
    pass
module = types.ModuleType('app.database')
module.Base = Base
module.get_db = lambda: None
sys.modules['app.database'] = module

@compiles(JSONB, 'sqlite')
def sqlite_json(type_, compiler, **kwargs):
    return 'JSON'

from pathlib import Path
routers = types.ModuleType('app.routers')
routers.__path__ = [str(Path(__file__).resolve().parents[1] / 'app' / 'routers')]
sys.modules['app.routers'] = routers

from app.models import Document, Workspace, User
from app.models.config import AppConfig
from app.models.document_version import DocumentVersion

user = types.SimpleNamespace(id=uuid4(), is_admin=True)
auth = types.ModuleType('app.routers.auth')
def current_user():
    return user

def admin_user():
    raise HTTPException(403, {'code': 'admin_elevation_required'})

def require_ws_owner(db, ws_id, who):
    ws = db.get(Workspace, ws_id)
    if not ws or ws.user_id != who.id:
        raise HTTPException(404, 'workspace')
    return ws

def require_doc_owner(db, doc_id, who):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, 'document')
    require_ws_owner(db, doc.workspace_id, who)
    return doc

auth.current_user = current_user
auth.admin_user = admin_user
auth.require_doc_owner = require_doc_owner
auth.require_ws_owner = require_ws_owner
sys.modules['app.routers.auth'] = auth
ws = types.ModuleType('app.routers.ws'); ws.notify_sync = lambda *a: None
sys.modules['app.routers.ws'] = ws
attachment = types.ModuleType('app.routers.attachment')
attachment.cleanup_unreferenced = lambda *a: None
sys.modules['app.routers.attachment'] = attachment

@pytest.fixture
def db():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()

@pytest.fixture
def workspace(db):
    w = Workspace(id=uuid4(), name='isolated', user_id=user.id)
    db.add(w); db.commit()
    return w

@pytest.fixture
def make_doc(db, workspace):
    def create(**kw):
        from datetime import datetime
        kw.setdefault('updated_at', datetime.now())
        d = Document(id=uuid4(), title='note', content='before', content_hash='hash', file_path='/test.md', workspace_id=workspace.id, **kw)
        db.add(d); db.commit(); db.refresh(d)
        return d
    return create
