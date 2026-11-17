"""Real isolated PostgreSQL template migration and lifecycle proofs."""
import io
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session
from fastapi import HTTPException
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes
from test_notes_overhaul import test_preferences_upgrade_conflict_and_owner_isolation as preferences_case


def test_preferences_real_pg(notes):
    preferences_case(notes)


def test_templates_migrate_once_copy_attachment_and_revalidate(notes):
    from app.services import notes_templates as service, blob_store
    from app.models import Tag, DocTag, Attachment
    with Session(notes.engine) as db:
        source = db.get(notes.models.Document, notes.did)
        aid, tid = uuid4(), uuid4()
        db.add(Tag(id=tid, name='模板', user_id=notes.uid))
        db.add(Attachment(id=aid, doc_id=source.id, filename='synthetic.png', mime='image/png', size=5))
        db.flush()
        db.add(DocTag(doc_id=source.id, tag_id=tid))
        source.content = f'![image](/attachments/{aid})'
        blob_store.put(db, 'attachments/'+str(aid), io.BytesIO(b'image'), 'image/png', 5)
        db.commit()
        root = service.initialize(db, notes.wid)
        assert service.initialize(db, notes.wid) == root
        catalog = service.catalog(db, notes.wid)
        assert len(catalog['items']) == 3
        assert catalog['recent_ids'] == []
        copied = db.query(notes.models.Document).filter_by(parent_id=root, title='fixture').one()
        original = db.get(notes.models.Document, notes.did)
        assert original.parent_id is None and str(aid) in original.content
        assert str(aid) not in copied.content
        doc = service.create_from_template(db, notes.wid, copied.id, None, 'independent')
        did, copied_id = doc.id, copied.id
        assert doc.parent_id is None and doc.content != copied.content
        assert service.catalog(db, notes.wid)['recent_ids'] == [str(copied_id)]
        notes.svc.permanently_delete_document(db, copied_id)
        independent = db.get(notes.models.Document, did)
        attachment = db.query(Attachment).filter_by(doc_id=did).one()
        assert str(attachment.id) in independent.content
        assert b''.join(blob_store.read_range(db, 'attachments/'+str(attachment.id), 0, 5)) == b'image'
        with pytest.raises(HTTPException):
            service.create_from_template(db, notes.wid, copied_id, None, 'invalid')
        assert service.catalog(db, notes.wid)['recent_ids'] == []
        for action in (notes.svc.delete_document, notes.svc.permanently_delete_document):
            with pytest.raises(HTTPException) as error:
                action(db, root)
            assert error.value.detail['code'] == 'protected_notes_folder'
        # Corrupt legacy ancestor must not allow cascade through root.
        parent = service.new_doc(db, notes.wid, None, 'ordinary ancestor', folder=True)
        parent_id = parent.id
        db.get(notes.models.Document, root).parent_id = parent_id
        db.commit()
        for action in (notes.svc.delete_document, notes.svc.permanently_delete_document):
            with pytest.raises(HTTPException):
                action(db, parent_id)
        assert db.get(notes.models.Document, root).deleted_at is None
        assert db.get(notes.models.Document, parent_id).deleted_at is None


def test_failed_migration_rolls_back_and_can_retry(notes):
    from app.services import notes_templates as service
    from app.models import Tag, DocTag
    with Session(notes.engine) as db:
        tid = uuid4()
        db.add(Tag(id=tid, name='模板', user_id=notes.uid)); db.flush()
        db.add(DocTag(doc_id=notes.did, tag_id=tid))
        db.get(notes.models.Document, notes.did).content = f'![missing](/attachments/{uuid4()})'
        db.commit()
        with pytest.raises(HTTPException):
            service.initialize(db, notes.wid)
        assert not service.protected_ids(db, notes.wid)
        assert db.query(notes.models.Document).count() == 1
        db.get(notes.models.Document, notes.did).content = 'fixed'
        db.commit()
        root = service.initialize(db, notes.wid)
        assert root and len(service.catalog(db, notes.wid)['items']) == 3
