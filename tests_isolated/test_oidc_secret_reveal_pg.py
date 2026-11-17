"""Opt-in owned loopback PostgreSQL proofs; never connects to preview/config DSNs."""
import copy
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import URL

from tests_isolated.test_oidc_pool_security import offline_modules  # noqa: F401
from tests_isolated.test_oidc_provider import oidc  # noqa: F401

REAL_CONNECT = socket.socket.connect


@pytest.fixture
def pg(oidc, monkeypatch):
    raw_port = os.getenv('STELLA_REVEAL_TEST_PG_PORT')
    marker = os.getenv('STELLA_REVEAL_TEST_PG_MARKER')
    if not raw_port or not marker:
        pytest.skip('requires owned ephemeral reveal-test PostgreSQL')
    port = int(raw_port)
    assert 1024 < port < 65536 and port not in (25436, 5432)
    assert marker.startswith('reveal-owned-') and len(marker) == 45
    assert not any(k.startswith('PG') for k in os.environ)
    def owned_connect(sock, address):
        assert address == ('127.0.0.1', port), 'non-owned TCP forbidden'
        return REAL_CONNECT(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', owned_connect)
    url = URL.create('postgresql+psycopg2', username='reveal_test', host='127.0.0.1',
                     port=port, database='stella_reveal_test')
    root = create_engine(url)
    schema = 'reveal_' + uuid4().hex
    with root.begin() as conn:
        assert conn.execute(text('select current_database(), current_user, inet_server_port()')).one() == ('stella_reveal_test', 'reveal_test', 5432)
        assert conn.scalar(text("select shobj_description(oid, 'pg_database') from pg_database where datname=current_database()")) == marker
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'}, pool_size=3, max_overflow=0)
    from app.services import ha_state
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    monkeypatch.setattr(ha_state, '_engine', lambda: engine)
    try:
        ha_state.metadata.create_all(engine)
        yield oidc, ha_state, engine
    finally:
        engine.dispose()
        with root.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert conn.scalar(text('select count(*) from information_schema.schemata where schema_name=:s'), {'s':schema}) == 0
        root.dispose()


def snapshot(ha, engine):
    with engine.connect() as conn:
        return conn.execute(text('select key,payload,xmin::text from ha_shared_state order by key')).all()


def test_pg_existing_reveal_is_select_only_and_keeps_runtime_and_credential_version(pg):
    oidc, ha, engine = pg
    created = oidc.create_client('fixture-rp', name='Fixture', redirect_uris=['https://rp.test/cb'])
    with ha.locked_state('oidc.runtime', {'codes':{},'tokens':{}}) as state:
        state['codes']['synthetic-code'] = {'keep':True}
    before = snapshot(ha, engine)
    statements = []
    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        assert oidc.reveal_client_secret('fixture-rp') == {'client_id':'fixture-rp','client_secret':created['client_secret']}
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert len(statements) == 1 and statements[0].lstrip().startswith('SELECT') and 'FOR SHARE' in statements[0]
    assert snapshot(ha, engine) == before
    assert 'client_secret' not in oidc.list_clients()[0]


def test_pg_absent_row_or_value_never_initializes_or_updates_any_state(pg):
    oidc, ha, engine = pg
    before = snapshot(ha, engine)
    with pytest.raises(KeyError):
        oidc.reveal_client_secret('openlist')
    assert snapshot(ha, engine) == before == []
    payload = {'fixture-rp':{'client_secret':'','credential_version':'keep-version','redirect_uris':['https://rp.test/cb']}}
    with engine.begin() as conn:
        conn.execute(ha.state_table.insert().values(key='oidc.clients',payload=copy.deepcopy(payload)))
    before = snapshot(ha, engine)
    with pytest.raises(ValueError, match='no existing secret'):
        oidc.reveal_client_secret('fixture-rp')
    assert snapshot(ha, engine) == before


def test_pg_reveal_waits_for_rotation_and_checks_admission_only_after_lock(pg):
    oidc, ha, engine = pg
    oidc.create_client('fixture-rp',name='Fixture',redirect_uris=['https://rp.test/cb'])
    started, authorized = Event(), Event()
    def read():
        started.set()
        return oidc.reveal_client_secret('fixture-rp', authorize=authorized.set)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with engine.begin() as conn:
            clients = conn.execute(select(ha.state_table.c.payload).where(ha.state_table.c.key=='oidc.clients').with_for_update()).scalar_one()
            clients['fixture-rp']['client_secret']='synthetic-replacement'
            clients['fixture-rp']['credential_version']='replacement-version'
            conn.execute(ha.state_table.update().where(ha.state_table.c.key=='oidc.clients').values(payload=clients))
            future = pool.submit(read)
            assert started.wait(2)
            deadline=time.monotonic()+5
            waiting=False
            while time.monotonic()<deadline:
                with engine.connect() as observer:
                    waiting=bool(observer.scalar(text("select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and wait_event_type='Lock' and query like '%FOR SHARE%'")))
                if waiting:
                    break
                time.sleep(.02)
            assert waiting and not future.done() and not authorized.is_set()
        assert future.result(timeout=5)=={'client_id':'fixture-rp','client_secret':'synthetic-replacement'}
    assert authorized.is_set()
    with engine.connect() as conn:
        clients=conn.execute(select(ha.state_table.c.payload).where(ha.state_table.c.key=='oidc.clients')).scalar_one()
    assert clients['fixture-rp']['credential_version']=='replacement-version'
