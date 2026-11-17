"""Exact-target prerequisites for test_servers_feedback (never app settings)."""
import os
import re

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from tests_ha.testdb_guard import (
    IDENTITY_SQL, MARKER, build_test_engine, verify_identity,
)


def fixture_engine(schema=None, env=None):
    env = os.environ if env is None else env
    if schema is not None and re.fullmatch(r'servers_fixture_[0-9a-f]{32}', schema) is None:
        raise ValueError('Invalid servers fixture schema')
    explicit = env.get('STELLA_SERVERS_FIXTURE_URL')
    if not explicit:
        # This is the exact service provisioned by .gitlab-ci.yml and
        # deploy/ci/create-test-db.py, NOT any ambient application URL.
        actual = tuple(env.get(k) for k in (
            'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_USER', 'POSTGRES_DB'))
        if env.get('CI') != 'true' or actual != ('postgres', '5432', 'stalla', 'stella'):
            raise ValueError('Dedicated servers fixture or exact disposable CI service required')
        if 'STELLA_TEST_DATABASE_URL' in env:
            raise ValueError('Unrelated test database override forbidden')
        source = URL.create('postgresql+psycopg2', username='stalla',
                            password=env.get('POSTGRES_PASSWORD'),
                            host='postgres', port=5432, database='stella')

        def scoped_factory(url, connect_args):
            if schema:
                connect_args['options'] += f' -csearch_path={schema}'
            return create_engine(url, connect_args=connect_args)

        return build_test_engine(source, env=env, factory=scoped_factory)

    url = make_url(explicit)
    if (url.drivername not in ('postgresql', 'postgresql+psycopg2') or url.query
            or (url.host, url.username, url.database) !=
               ('127.0.0.1', 'servers_fixture', 'stella_servers_fixture')
            or url.port is None or not 1 <= url.port <= 65535 or url.port == 5432
            or any(k.startswith('PG') for k in env)):
        raise ValueError('Refusing unsafe dedicated servers fixture target')
    options = '-c stella.test_isolation=' + MARKER
    if schema:
        options += f' -csearch_path={schema}'
    engine = create_engine(url, connect_args={'hostaddr': '127.0.0.1', 'options': options})

    def revalidate():
        if env.get('STELLA_SERVERS_FIXTURE_URL') != explicit or any(k.startswith('PG') for k in env):
            raise ValueError('Changed servers fixture configuration')

    @event.listens_for(engine, 'do_connect')
    def before_connect(dialect, record, args, params):
        revalidate()
        if args or set(params) - {'host', 'hostaddr', 'port', 'user', 'dbname', 'password', 'options'}:
            raise ValueError('Unexpected servers fixture connect overrides')
        if (params.get('host'), params.get('hostaddr'), params.get('port'),
                params.get('user'), params.get('dbname'), params.get('options')) != (
                '127.0.0.1', '127.0.0.1', url.port, 'servers_fixture',
                'stella_servers_fixture', options):
            raise ValueError('Changed servers fixture connection target')

    @event.listens_for(engine, 'checkout')
    def check_connection(conn, record, proxy):
        revalidate()
        try:
            with conn.cursor() as cursor:
                cursor.execute(IDENTITY_SQL)
                verify_identity(cursor.fetchone(), url, '127.0.0.1')
        finally:
            conn.rollback()

    engine._stella_test_identity = (url, '127.0.0.1', revalidate)
    return engine
