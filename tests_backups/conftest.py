"""Only self-provisioned exact-target PG is allowed; no developer/live DSNs."""
import json
import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


@pytest.fixture(scope='session')
def owned():
    receipt = json.loads(Path(os.environ['STELLA_BACKUP_FIXTURE']).read_text())
    assert os.readlink('/proc/self/ns/net') == os.readlink(f"/proc/{receipt['pid']}/ns/net")
    assert os.environ['POSTGRES_DB'] == receipt['database']
    assert os.environ['POSTGRES_USER'] == receipt['user']
    assert os.environ['POSTGRES_HOST'] == '127.0.0.1' and os.environ['POSTGRES_PORT'] == '5432'
    assert not Path('.env').exists()
    return receipt


@pytest.fixture
def engine(owned):
    from app.database import Base
    import app.models
    url = URL.create('postgresql+psycopg2', username=owned['user'], password=owned['password'],
                     host='127.0.0.1', port=5432, database=owned['database'])
    engine = create_engine(url, pool_size=8, max_overflow=0)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()')).one() == (
            owned['database'], owned['user'], '127.0.0.1', 5432)
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        Base.metadata.create_all(conn)
        from app.services.ha_state import metadata
        metadata.create_all(conn)
    yield engine
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database()')).scalar_one() == owned['database']
        Base.metadata.drop_all(conn)
        metadata.drop_all(conn)
    engine.dispose()
