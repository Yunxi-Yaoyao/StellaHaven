"""Run only against an explicitly provided disposable loopback test database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.models.config import AppConfig
from app.services.backup_health import record_change, read_change_audit

@pytest.mark.skipif(not os.environ.get('STELLA_INFRA_TEST_DSN'), reason='dedicated disposable PostgreSQL DSN not provided')
def test_postgres_audit_concurrent_first_insert_and_rollback():
    url = make_url(os.environ['STELLA_INFRA_TEST_DSN'])
    assert url.host == '127.0.0.1' and url.database == 'stella_infra_audit'
    assert url.port not in {5432, 24532, 24533, 24534}, 'refuse production ports'
    engine = create_engine(url)
    AppConfig.__table__.create(engine)
    actor = str(uuid4())
    barrier = Barrier(2)
    def append_batch():
        barrier.wait()
        for _ in range(20):
            with Session(engine) as db:
                record_change(db, action='integration.update', actor_id=actor, resource_id=uuid4(), changed_fields=['enabled'])
                db.commit()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(append_batch) for _ in range(2)]
            for job in jobs:
                job.result(timeout=30)
        with Session(engine) as db:
            events = read_change_audit(db)
            assert len(events) == 40
            assert len({event['resource_id'] for event in events}) == 40
            record_change(db, action='integration.delete', actor_id=actor)
            db.rollback()
            assert read_change_audit(db) == events
    finally:
        AppConfig.__table__.drop(engine)
        engine.dispose()
