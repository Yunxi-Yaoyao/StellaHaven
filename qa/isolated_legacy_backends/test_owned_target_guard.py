"""Independent positive and fail-closed acceptance; actual disposable PG only."""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
import guard
from owned_target import OwnedTarget, owned_target as default_fixture
from control import ROOT

def test_default_fixture_preserves_legacy_mode():
    assert default_fixture.__wrapped__() is None

def test_owned_same_connection_identity_and_schema_cleanup():
    target = OwnedTarget()
    with target.scope() as engine:
        assert target.confirmation(engine) == guard.s['db']
        with engine.connect() as conn:
            target.identity(conn)
            assert conn.exec_driver_sql('select current_database(),current_user').one() == (guard.s['db'],guard.s['user'])

@pytest.mark.parametrize('field,value', [('host','172.25.0.2'),('port',24532),('database','postgres'),('username','postgres'),('query',{'host':'172.25.0.2'})])
def test_other_target_rejected_before_connect(field,value,monkeypatch):
    target = OwnedTarget()
    engine = create_engine(guard.URL_.set(**{field:value}))
    def forbidden():
        pytest.fail('must reject before any connection attempt')
    monkeypatch.setattr(engine,'connect',forbidden)
    with pytest.raises(AssertionError):
        target.confirmation(engine)
    engine.dispose()

def test_wrong_binding_rejected_before_connection(monkeypatch):
    monkeypatch.setitem(guard.s,'nonce','not-the-owned-container')
    with pytest.raises(AssertionError):
        OwnedTarget()

def test_wrong_namespace_rejected_before_connection(monkeypatch):
    original = guard.os.readlink
    monkeypatch.setattr(guard.os,'readlink',lambda path: 'net:[wrong]' if path=='/proc/self/ns/net' else original(path))
    with pytest.raises(AssertionError):
        OwnedTarget()

def test_real_identity_mismatch_rejected(monkeypatch):
    target = OwnedTarget()
    role = 'identity_probe_' + guard.s['nonce']
    with target.scope() as engine:
        with engine.begin() as conn:
            conn.exec_driver_sql('CREATE ROLE "'+role+'"')
            try:
                conn.exec_driver_sql('SET ROLE "'+role+'"')
                with pytest.raises(AssertionError):
                    target.identity(conn)
            finally:
                conn.exec_driver_sql('RESET ROLE')
                conn.exec_driver_sql('DROP ROLE "'+role+'"')
            assert conn.exec_driver_sql('select count(*) from pg_roles where rolname=%s',(role,)).scalar_one() == 0

@pytest.mark.parametrize('override', [{'dbname':'postgres'}, {'host':'172.25.0.2'}, {'port':24532}, {'hostaddr':'127.0.0.2'}, {'options':'-csearch_path=public'}])
def test_dbapi_overrides_rejected_before_connect(override,monkeypatch):
    import psycopg2
    def forbidden(*a,**kw):
        pytest.fail('driver must not be called for another target')
    monkeypatch.setattr(psycopg2,'connect',forbidden)
    engine = create_engine(guard.URL_,connect_args=override)
    with pytest.raises(AssertionError):
        engine.connect()
    engine.dispose()


def test_unbound_invocation_is_rejected(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules,'guard')
    with pytest.raises(AssertionError,match='owned launcher'):
        OwnedTarget()

@pytest.mark.parametrize('dbname,port', [('postgres',40001),('stella_infra_audit',5432),('stella_infra_audit',24532),('stella_infra_audit',24533),('stella_infra_audit',24534)])
def test_default_audit_refuses_other_database_or_production_ports(dbname,port,monkeypatch):
    import app.services
    from tests_isolated.test_operations_audit_pg import test_postgres_audit_concurrent_first_insert_and_rollback as original
    monkeypatch.setenv('STELLA_INFRA_TEST_DSN',f'postgresql://127.0.0.1:{port}/{dbname}')
    with pytest.raises(AssertionError):
        original(None)

def test_default_audit_missing_optin_still_skips(monkeypatch):
    import app.services
    from tests_isolated.test_operations_audit_pg import legacy_audit_url
    monkeypatch.delenv('STELLA_INFRA_TEST_DSN',raising=False)
    with pytest.raises(pytest.skip.Exception,match='dedicated disposable'):
        legacy_audit_url()

def test_default_memory_missing_optin_still_skips(monkeypatch):
    from tests_isolated.test_system_memory_roundtrip import test_memory_report_repository_schema_http_roundtrip as original
    monkeypatch.delenv('MEMORY_QA_PG_SOCKET',raising=False)
    with pytest.raises(pytest.skip.Exception,match='disposable PostgreSQL socket'):
        original('postgres',None)

@pytest.mark.parametrize('path',['/var/run/postgresql','/root/.hermes/cache/scratch/not-memory','/root/.hermes/cache/scratch/elsewhere/memory-qa-123'])
def test_default_memory_rejects_foreign_socket(path,monkeypatch):
    from tests_isolated.test_system_memory_roundtrip import test_memory_report_repository_schema_http_roundtrip as original
    monkeypatch.setenv('MEMORY_QA_PG_SOCKET',path)
    with pytest.raises(AssertionError):
        original('postgres',None)

def test_default_cli_keeps_literal_confirmation_and_rejects_owned_database(tmp_path,capsys):
    from app.services import ha_state
    from tests_ha.test_shared_state import test_import_cli_private_output as original
    with guard.schema_scope() as (engine,name):
        ha_state.metadata.create_all(engine)
        try:
            with pytest.raises(AssertionError):
                original(engine,tmp_path,capsys,None)
            with engine.connect() as conn:
                assert conn.exec_driver_sql('select count(*) from ha_shared_state').scalar_one()==0
        finally:
            (tmp_path/'dsn').unlink(missing_ok=True)

def test_ambient_libpq_override_refused_before_driver(monkeypatch):
    import psycopg2
    monkeypatch.setenv('PGHOSTADDR','127.0.0.2')
    def forbidden(*a,**kw):
        pytest.fail('ambient PG must be rejected before driver')
    monkeypatch.setattr(psycopg2,'connect',forbidden)
    engine=create_engine(guard.URL_)
    with pytest.raises(AssertionError,match='ambient libpq'):
        engine.connect()
    engine.dispose()
