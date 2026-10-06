from datetime import datetime
from uuid import uuid4
import pytest
from sqlalchemy import inspect
from app.models import Workspace
from app.repositories.document import list_by_workspace
from app.services.document import update_document, list_trash_documents, get_backlinks
from app.schemas.document import DocumentUpdate


def test_summary_never_loads_body_or_draft(db, workspace, make_doc):
    d = make_doc(draft_content='private draft')
    ws_id = workspace.id
    db.expunge_all()
    item = list_by_workspace(db, ws_id)[0]
    assert {'content', 'draft_content'} <= inspect(item).unloaded


def test_backlinks_are_scoped_metadata_without_bodies(db, workspace, make_doc):
    from app.models import DocumentLink
    target = make_doc(); source = make_doc(draft_content='secret')
    other = Workspace(id=uuid4(), name='other', user_id=workspace.user_id)
    db.add(other); db.commit()
    foreign = make_doc(); foreign.workspace_id = other.id; db.commit()
    db.add_all([DocumentLink(source_id=source.id, target_id=target.id, link_type='ref'), DocumentLink(source_id=foreign.id, target_id=target.id, link_type='ref')]); db.commit()
    target_id = target.id
    db.expunge_all()
    rows = get_backlinks(db, target_id)
    assert len(rows) == 1
    assert {'content', 'draft_content'} <= inspect(rows[0]).unloaded


def test_move_rejects_cross_workspace_parent(db, workspace, make_doc):
    d = make_doc(); p = make_doc()
    other = Workspace(id=uuid4(), name='other', user_id=workspace.user_id)
    db.add(other); db.commit(); p.workspace_id = other.id; db.commit()
    with pytest.raises(ValueError, match='Invalid parent'):
        update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, parent_id=p.id))
    assert d.parent_id is None


def test_trash_get_never_physically_purges_data(db, workspace, make_doc):
    from datetime import timedelta
    d = make_doc(deleted_at=datetime.now() - timedelta(days=60))
    doc_id = d.id
    assert len(list_trash_documents(db, workspace.id)) == 1
    assert db.get(type(d), doc_id) is not None


def test_move_rejects_deleted_parent(db, make_doc):
    d = make_doc(); p = make_doc(deleted_at=datetime.now())
    with pytest.raises(ValueError, match='Invalid parent'):
        update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, parent_id=p.id))


def test_move_detects_existing_cycle_without_hanging(db, make_doc):
    d = make_doc(); p = make_doc(); p.parent_id = p.id; db.commit()
    with pytest.raises(ValueError, match='Circular parent'):
        update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, parent_id=p.id))


def test_move_serializes_same_workspace_tree_mutations(db, workspace, make_doc, monkeypatch):
    from app.services import notes_tools
    keys = []
    monkeypatch.setattr(notes_tools, 'lock_key', lambda db, key: keys.append(key))
    d = make_doc(); p = make_doc()
    update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, parent_id=p.id))
    assert keys == ['document-tree:' + str(workspace.id)]
    assert d.parent_id == p.id
