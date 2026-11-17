"""Opt-in disposable PostgreSQL database; never point at preview business DB.
Run --noconftest with STELLA_ACCESS_TEST_DATABASE_URL created by the scoped runner.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

OWNER = '00000000-0000-4000-8000-000000000001'
P = 'https://stella.test'
L = 'https://stella.p.test'

@pytest.fixture
def pg(monkeypatch):
    url = os.getenv('STELLA_ACCESS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('explicit disposable PostgreSQL URL required')
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.port == 25436
    assert parsed.database.startswith('stella_test_accessflow_')
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([{'service_id':'stella','public':P,'private':L}]))
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', P+','+L)
    monkeypatch.delenv('STELLA_OWNER_ID', raising=False)
    from app.models.config import AppConfig
    from app.services.admin_security import STATE_KEY
    engine = create_engine(url, pool_size=4, max_overflow=0)
    with engine.connect() as c:
        assert str(c.execute(text('select system_identifier from pg_control_system()')).scalar()) == '7698041980212371498'
    AppConfig.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.query(AppConfig).delete()
        db.add(AppConfig(key=STATE_KEY, value=json.dumps({'owner_id':OWNER})))
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()

@pytest.mark.parametrize('existing', [False,True])
def test_postgres_concurrent_same_revision_has_exactly_one_winner(pg, existing):
    from app.services import access_entries as service
    from app.models.config import AppConfig
    with pg() as db:
        draft = service.Settings(**service.read(db,OWNER))
        if existing:
            digest = service.check(db,draft,OWNER)['digest']
            service.apply(db,service.ApplyInput(**draft.model_dump(),checked_digest=digest),OWNER)
        draft = service.Settings(**(service.read(db,OWNER)|{'enabled':False}))
        digest = service.check(db,draft,OWNER)['digest']
        incoming = service.ApplyInput(**draft.model_dump(),checked_digest=digest)
    ready = threading.Barrier(2)
    def worker():
        with pg() as db:
            ready.wait(timeout=5)
            try:
                return (200,service.apply(db,incoming,OWNER)['settings']['revision'])
            except HTTPException as exc:
                return (exc.status_code,None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _:worker(),range(2)))
    assert sorted(s for s,_ in outcomes) == [200,409]
    with pg() as db:
        stored = service.read(db,OWNER)
        assert stored == draft.model_dump()|{'revision':draft.revision+1}
        assert db.query(AppConfig).filter(AppConfig.key==service.KEY).count() == 1

def test_postgres_request_snapshot_pins_selection_until_next_request(pg):
    from app.services import access_entries as service
    with service.request_snapshot(pg):
        assert service.lane(L) == 'private'
        with pg() as db:
            incoming = service.Settings(**(service.read(db,OWNER)|{'enabled':False}))
            digest = service.check(db,incoming,OWNER)['digest']
            service.apply(db,service.ApplyInput(**incoming.model_dump(),checked_digest=digest),OWNER)
        assert service.lane(L) == 'private'
    assert service.current() is None
    with service.request_snapshot(pg):
        assert service.lane(L) == 'private'
        assert service.lane(L,policy='public') == 'public'
        assert service.current()['revision'] == 1

def test_postgres_persisted_owner_mismatch_fails_closed(pg):
    from app.services import access_entries as service
    from app.models.config import AppConfig
    with pg() as db:
        before = service.read(db,OWNER)
        db.add(AppConfig(key=service.KEY,value=json.dumps({'owner_id':'00000000-0000-4000-8000-000000000002','settings':before})))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            service.read(db,OWNER)
        assert exc.value.status_code == 503


def test_postgres_legacy_disabled_revision_reads_same_side_without_mutation(pg):
    from app.services import access_entries as service
    from app.models.config import AppConfig
    raw=json.dumps({'owner_id':OWNER,'settings':{'revision':10,'enabled':False,'public_origin':P,'private_origin':L}})
    with pg() as db:
        db.add(AppConfig(key=service.KEY,value=raw));db.commit()
    with service.request_snapshot(pg):
        assert service.lane(L)=='private'
        assert service.lane(P)=='public'
        assert service.lane(L,policy='public')=='public'
    with pg() as db:
        assert db.get(AppConfig,service.KEY).value==raw
