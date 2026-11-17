"""Explicit owned network-none PG receipt; never accepts a developer DSN."""
import json
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


@pytest.fixture
def engine(monkeypatch):
    receipt = json.loads(Path(os.environ['STELLA_RESULT_FIXTURE']).read_text())
    assert os.readlink('/proc/self/ns/net') == os.readlink(f"/proc/{receipt['pid']}/ns/net")
    assert not Path('.env').exists()
    assert receipt['label'] == 'stella-results-owned'
    url = URL.create('postgresql+psycopg2', username=receipt['user'], password=receipt['password'],
                     host='127.0.0.1', port=5432, database=receipt['database'])
    engine = create_engine(url, pool_size=8, max_overflow=0)
    schema = 'results_' + uuid.uuid4().hex
    from app.models import Base
    from app.services import alerts
    monkeypatch.setattr(alerts, '_push_ws', lambda p: None)
    monkeypatch.setattr(alerts, '_send_alert_email', lambda p: pytest.fail('mail forbidden'))
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(),current_user,host(inet_server_addr())')).one() == (receipt['database'], receipt['user'], '127.0.0.1')
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    from sqlalchemy import event
    @event.listens_for(engine, 'connect')
    def settings(dbapi, _):
        with dbapi.cursor() as cursor:
            cursor.execute(f'SET search_path TO {schema}, public')
        dbapi.commit()
    engine.dispose()
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(), current_schema()')).one() == (receipt['database'], schema)
        Base.metadata.create_all(conn)
        from app.services.ha_state import metadata
        metadata.create_all(conn)
    # Legacy backup subprocess probes must inherit this owned schema, not public.
    monkeypatch.setenv('PGOPTIONS', f'-csearch_path={schema},public')
    yield engine
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(),current_schema()')).one() == (receipt['database'], schema)
        conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        assert conn.execute(text('SELECT count(*) FROM pg_namespace WHERE nspname=:s'), {'s':schema}).scalar_one() == 0
    engine.dispose()
