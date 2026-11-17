"""Regression oracles for the guarded PostgreSQL fixture, not product mocks."""
import json
import pytest
from sqlalchemy import text


def test_lifespan_uses_disposable_schema_and_commits_for_fresh_sessions(db_session, client):
    from app import database
    from app.models.config import AppConfig
    from app.services.entry_monitor_groups import KEY
    from app.services.node import get_host_node
    from main import app
    assert database.engine is db_session.get_bind()
    with database.sessionLocal() as fresh:
        assert fresh.scalar(text('SELECT current_schema()')) == db_session.scalar(text('SELECT current_schema()'))
        state = json.loads(fresh.get(AppConfig, KEY).value)
        assert {'entry:public', 'entry:private'} <= state.keys()
        assert get_host_node(fresh) is not None
    assert app.state.backup_center.engine is database.engine
    assert app.state.node_deadlines.engine.url == database.engine.url
    with app.state.node_deadlines.engine.connect() as connection:
        assert connection.scalar(text('SELECT current_schema()')) == db_session.scalar(text('SELECT current_schema()'))
    assert client.get('/auth/security').json()['elevated'] is True


def test_startup_bootstrap_writes_are_visible_without_registration(db_session):
    from fastapi.testclient import TestClient
    from app import database
    from app.models.config import AppConfig
    from app.services.entry_monitor_groups import KEY
    from main import app
    row = db_session.get(AppConfig, KEY)
    assert row is not None
    db_session.delete(row)
    db_session.commit()
    # No registration or other HTTP endpoint is invoked here: only lifespan can
    # recreate this record. Read through a genuinely fresh committed session.
    with TestClient(app):
        with database.sessionLocal() as fresh:
            row = fresh.get(AppConfig, KEY)
            assert row is not None
            assert {'entry:public', 'entry:private'} <= json.loads(row.value).keys()


def test_fixture_intercepts_only_queued_installer_and_keeps_real_owner(monkeypatch, request, initial_host_install_tasks):
    from app.services import host, node
    from app.models.user import User
    # Exercise the dangerous host-root branch too, even inside Docker. Do not
    # skip registration or host-role preparation to make this test safe.
    monkeypatch.setattr(host, 'supports_local_install', lambda: True)
    monkeypatch.setattr(node, 'installation_url', lambda db: 'http://testserver')
    session = request.getfixturevalue('db_session')
    client = request.getfixturevalue('client')
    assert session.query(User).one().username == 'test_owner'
    assert client.get('/auth/security').json()['elevated'] is True
    state = node.host_installation(session)
    assert state['status'] == 'queued'
    assert state['attempt_id']
    assert (session.get_bind(), state['node_id'], state['attempt_id']) in initial_host_install_tasks
    assert node.get_host_node(session).installed is False


@pytest.mark.parametrize('url,env', [
    ('postgresql://stalla@postgres:5432/stella', {'CI': 'false'}),
    ('postgresql://stalla@postgres:5432/stella', {'CI': 'true', 'STELLA_TEST_DATABASE_URL': 'postgresql://stalla@postgres:5432/stella'}),
    ('postgresql://other@postgres:5432/stella_test', {'CI': 'true'}),
    ('postgresql://stalla@127.0.0.1:5432/stella_test', {'CI': 'true'}),
    ('postgresql://stalla@postgres:25476/stella_test', {'CI': 'true'}),
    ('postgresql://stalla@postgres:5432/stella_test', {'CI': 'true', 'PGOPTIONS': '-csearch_path=public'}),
])
def test_fixture_guard_rejects_nonexact_targets_before_engine_creation(url, env):
    from tests_ha.testdb_guard import build_test_engine
    def forbidden_factory(*args, **kwargs):
        pytest.fail('unsafe target reached engine factory')
    with pytest.raises(ValueError, match='Refusing unsafe'):
        build_test_engine(url, env=env, factory=forbidden_factory)
