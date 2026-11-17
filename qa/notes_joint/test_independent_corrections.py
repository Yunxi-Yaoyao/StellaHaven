"""Independent correction: preserve failure boundary, rollback and conflict strength."""
from test_api_draft_contract import env
from test_notes_lifecycle_http import notes
from test_review_lifecycle import add_tag
from sqlalchemy import event
from sqlalchemy.orm import Session
from fastapi import HTTPException
from fastapi.testclient import TestClient


def test_f8_failure_rollback_precedes_success_retry(notes):
    from app.models import DocTag,Tag
    tid=add_tag(notes);seen=[]
    def failure(conn,cursor,sql,params,context,many):
        if sql.startswith('DELETE FROM tags'):
            seen.append(sql);raise RuntimeError('independent orphan failure')
    event.listen(notes.engine,'before_cursor_execute',failure)
    try:
        with TestClient(notes.client.app,raise_server_exceptions=False) as c:
            c.cookies.set('stella_at',notes.token)
            r=c.delete('/doc-tags/',params={'doc_id':str(notes.did),'tag_id':str(tid)})
        assert r.status_code==500 and len(seen)==1
    finally:event.remove(notes.engine,'before_cursor_execute',failure)
    # Fresh session before any retry: both link and tag MUST be rolled back.
    with Session(notes.engine) as db:
        assert db.get(Tag,tid) is not None
        assert db.get(DocTag,(notes.did,tid)) is not None
    assert notes.client.delete('/doc-tags/',params={'doc_id':str(notes.did),'tag_id':str(tid)}).status_code==204
    with Session(notes.engine) as db:
        assert db.get(Tag,tid) is None
        assert db.get(DocTag,(notes.did,tid)) is None
    assert notes.client.delete('/doc-tags/',params={'doc_id':str(notes.did),'tag_id':str(tid)}).status_code==404


def test_f9_stale_precheck_only_controlled_not_fk_and_no_orphans(notes,monkeypatch):
    from app.routers import doc_tag
    from app.services.document import permanently_delete_document
    from app.models import DocTag,Tag,Document
    tid=add_tag(notes);original=doc_tag.add_tag;observed=[]
    def interleave(db,data,**kwargs):
        assert kwargs['user_id']==notes.uid
        db.rollback()
        with Session(notes.engine) as deletion:permanently_delete_document(deletion,notes.did,user_id=notes.uid)
        try:return original(db,data,**kwargs)
        except HTTPException as exc:
            assert exc.status_code in (404,409)
            assert not db.in_transaction()
            observed.append(exc.status_code);raise
        # Any IntegrityError/runtime exception reaches HTTP 500 and fails below.
    monkeypatch.setattr(doc_tag,'add_tag',interleave)
    with TestClient(notes.client.app,raise_server_exceptions=False) as c:
        c.cookies.set('stella_at',notes.token)
        r=c.post('/doc-tags/',json={'doc_id':str(notes.did),'tag_id':str(tid)})
    assert r.status_code in (404,409)
    assert observed==[r.status_code]
    with Session(notes.engine) as db:
        assert db.get(Document,notes.did) is None
        assert db.get(Tag,tid) is None
        assert db.get(DocTag,(notes.did,tid)) is None
