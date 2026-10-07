"""Exclusively owned disposable PG; never uses application settings DSN."""
import json
import os
import subprocess
import time
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.models.config import AppConfig

@pytest.fixture(scope='module')
def pg_engine():
    if os.environ.get('STELLA_SERVICE_TEST_PG_RECEIPT'):
        from tests_service_settings.pg_fixture import guarded_engine
        with guarded_engine() as engine:
            AppConfig.__table__.create(engine)
            yield engine
        return
    assert not any(k in os.environ for k in ('PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','PGSERVICE','PGSERVICEFILE','PGOPTIONS'))
    name = 'stella-builtin-test-' + uuid4().hex[:12]
    subprocess.run(['docker','run','-d','--name',name,'-p','127.0.0.1::5432','-e','POSTGRES_USER=builtin','-e','POSTGRES_PASSWORD=builtin-fixture-only','-e','POSTGRES_DB=stella_builtin_test','postgres:16-alpine','-c','stella.test_isolation=builtin-test-only'], check=True, capture_output=True)
    engine = None
    try:
        mapping = json.loads(subprocess.check_output(['docker','inspect',name]))[0]['NetworkSettings']['Ports']['5432/tcp'][0]
        assert mapping['HostIp'] == '127.0.0.1'
        port = int(mapping['HostPort']); assert port not in {5432,24532,24533,24534}
        engine = create_engine(f'postgresql+psycopg2://builtin:builtin-fixture-only@127.0.0.1:{port}/stella_builtin_test', connect_args={'connect_timeout':2})
        for _ in range(60):
            try:
                with engine.connect() as c:
                    assert c.execute(text("select current_database(), current_user, current_setting('stella.test_isolation')")).one() == ('stella_builtin_test','builtin','builtin-test-only')
                break
            except __import__('sqlalchemy').exc.OperationalError:
                time.sleep(.2)
        else: raise AssertionError('disposable PG did not start')
        AppConfig.__table__.create(engine)
        yield engine
    finally:
        if engine: engine.dispose()
        subprocess.run(['docker','rm','-f',name], check=True, capture_output=True)

@pytest.fixture
def pg_db(pg_engine):
    with Session(pg_engine) as db:
        db.query(AppConfig).delete(); db.commit()
        yield db
