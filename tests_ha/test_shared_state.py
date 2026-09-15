"""Isolated shared-state tests; no production settings, keys or schema touched.
Run STELLA_HA_STATE_PG_TEST=1 to opt into the exact dedicated PoC DB.
"""
import importlib
import json
import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture
def safe_modules(monkeypatch, tmp_path):
    # Stub before import: settings and auth otherwise load real config/key files.
    config = types.ModuleType('app.config')
    config.settings = types.SimpleNamespace(database_url='sqlite://')
    monkeypatch.setitem(sys.modules, 'app.config', config)
    auth = types.ModuleType('app.routers.auth')
    auth.admin_user = lambda: None
    monkeypatch.setitem(sys.modules, 'app.routers.auth', auth)
    routers = types.ModuleType('app.routers')
    routers.__path__ = [str(Path(__file__).resolve().parents[1] / 'app' / 'routers')]
    monkeypatch.setitem(sys.modules, 'app.routers', routers)
    from app.services import oidc
    admin_email = importlib.import_module('app.routers.admin_email')
    monkeypatch.setattr(oidc, 'OIDC_DIR', tmp_path / 'oidc')
    monkeypatch.setattr(oidc, 'PRIVATE_KEY_PATH', tmp_path / 'oidc' / 'private.json')
    monkeypatch.setattr(oidc, 'CLIENT_FILE', tmp_path / 'oidc' / 'clients.json')
    monkeypatch.setattr(oidc, 'DEFAULT_CLIENT', {**oidc.DEFAULT_CLIENT, 'client_secret': None})
    monkeypatch.setattr(admin_email, 'CONFIG_FILE', tmp_path / 'email.json')
    monkeypatch.delenv('STELLA_SHARED_STATE', raising=False)
    return oidc, admin_email


def test_opt_in_does_not_write_legacy_clients(safe_modules, monkeypatch):
    oidc, _ = safe_modules
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    # Missing table must fail closed, never silently write a file.
    with pytest.raises(Exception):
        oidc.get_client_secret('new-client')
    assert not oidc.CLIENT_FILE.exists()


@pytest.fixture
def pg(safe_modules, monkeypatch):
    if os.getenv('STELLA_HA_STATE_PG_TEST') != '1':
        pytest.skip('explicit real-PG opt-in required')
    data = json.loads(Path('/opt/hermes-workstation/stella-ha-poc/private/blob-db.json').read_text())
    url = make_url(data['dsn'])
    assert url.host == '172.25.0.2' and url.port == 5432 and url.database == 'stella_ha_poc'
    engine = create_engine(url, hide_parameters=True)
    schema = 'ha_state_test_' + uuid4().hex
    with engine.begin() as conn:
        assert conn.scalar(text('select current_database()')) == 'stella_ha_poc'
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = create_engine(url, connect_args={'options': f'-csearch_path={schema}'}, hide_parameters=True)
    from app.services import ha_state
    ha_state.metadata.create_all(scoped)
    monkeypatch.setattr(ha_state, '_engine', lambda: scoped)
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    try:
        yield scoped
    finally:
        scoped.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()


def test_real_pg_exchange_once_across_workers(pg, safe_modules):
    oidc, _ = safe_modules
    secret = oidc.get_client_secret('rp')
    code = oidc.create_authorization_code('rp', 'https://rp/cb', '123', 'user', 'a@b', 'nonce')
    assert oidc.exchange_code(code, 'rp', 'bad', 'https://rp/cb') is None
    assert oidc.exchange_code(code, 'rp', secret, 'https://wrong') is None
    from authlib.jose import JsonWebKey
    oidc.PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    oidc.PRIVATE_KEY_PATH.write_text(json.dumps(JsonWebKey.generate_key('RSA', 2048, is_private=True).as_dict(is_private=True)))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: oidc.exchange_code(code, 'rp', secret, 'https://rp/cb'), range(8)))
    tokens = [r for r in results if r]
    assert len(tokens) == 1
    # A fresh module instance has no Python state/cache from the issuer.
    spec = importlib.util.spec_from_file_location('oidc_fresh_worker', oidc.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.get_client_secret('rp') == secret
    assert fresh.userinfo(tokens[0]['access_token'])['sub'] == '123'
    assert fresh.exchange_code(code, 'rp', secret, 'https://rp/cb') is None
    assert not (oidc.OIDC_DIR / 'runtime').exists()
    assert not oidc.CLIENT_FILE.exists()


def test_smtp_postgres_transaction_and_mask(pg, safe_modules):
    _, mail = safe_modules
    from app.services import ha_state
    mail.put_config(mail.EmailConfigIn(host='smtp.test', username='test', password='secret'), None)
    assert not mail.CONFIG_FILE.exists()
    mail.put_config(mail.EmailConfigIn(host='smtp.changed', username='test', password='••••••'), None)
    assert mail.get_config(None)['password'] == '••••••'
    assert mail._load()['password'] == 'secret'
    assert mail._load()['host'] == 'smtp.changed'
    with pytest.raises(RuntimeError):
        with ha_state.locked_state('smtp.config', {}) as state:
            state['password'] = 'must-rollback'
            raise RuntimeError('rollback')
    assert mail._load()['password'] == 'secret'


def test_import_explicit_atomic_no_overwrite(pg, safe_modules, tmp_path):
    from scripts import import_shared_state as importer
    from app.services import ha_state
    clients = tmp_path / 'clients.json'
    smtp = tmp_path / 'smtp.json'
    clients.write_text(json.dumps({'openlist': {'client_secret': 'imported', 'redirect_uris': ['https://custom/cb']}}))
    smtp.write_text(json.dumps({'host': 'imported', 'password': 'kept'}))
    assert importer.import_files(pg, clients=clients, smtp=smtp) == ['oidc.clients', 'smtp.config']
    oidc, mail = safe_modules
    assert oidc.verify_redirect_uri('openlist', 'https://custom/cb')
    assert oidc.get_client_secret('openlist') == 'imported'
    assert mail._load()['password'] == 'kept'
    smtp.write_text(json.dumps({'password': 'overwrite'}))
    with pytest.raises(ValueError):
        importer.import_files(pg, smtp=smtp)
    assert mail._load()['password'] == 'kept'
    runtime = tmp_path / 'runtime.json'
    runtime.write_text(json.dumps({'codes': {}, 'tokens': {}}))
    # A later conflict must roll back earlier inserts in the same import.
    with pg.begin() as conn:
        conn.execute(text("delete from ha_shared_state where key='oidc.clients'"))
    with pytest.raises(ValueError):
        importer.import_files(pg, clients=clients, smtp=smtp, runtime=runtime)
    with pg.connect() as conn:
        assert conn.scalar(text("select count(*) from ha_shared_state where key='oidc.clients'")) == 0


def test_import_cli_private_output(pg, tmp_path, capsys):
    from scripts import import_shared_state as importer
    dsn = tmp_path / 'dsn'
    dsn.write_text(pg.url.update_query_dict({'options': pg.dialect.create_connect_args(pg.url)[1].get('options', '')}).render_as_string(hide_password=False))
    # Bind CLI to the fixture engine so its exact isolated search_path is retained.
    from unittest.mock import patch
    dsn.chmod(0o600)
    source = tmp_path / 'smtp.json'
    source.write_text(json.dumps({'password': 'NEVER_PRINT_THIS'}))
    args = ['import_shared_state', '--database-url-file', str(dsn), '--confirm-database', 'stella_ha_poc', '--smtp', str(source)]
    with patch.object(importer, 'create_engine', return_value=pg), patch.object(sys, 'argv', args):
        assert importer.main() == 0
        assert importer.main() == 1
    output = capsys.readouterr().out
    assert 'Imported and verified: smtp.config' in output
    assert 'NEVER_PRINT_THIS' not in output


def test_pg_requires_provisioned_signing_key(pg, safe_modules):
    oidc, _ = safe_modules
    with pytest.raises(RuntimeError, match='provision'):
        oidc._get_key()
    assert not oidc.PRIVATE_KEY_PATH.exists()


def test_migration_roundtrip(pg):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.services import ha_state
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/a6b7c8d9e0f1_ha_shared_state.py'
    spec = importlib.util.spec_from_file_location('state_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pg.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        module.downgrade()
        module.upgrade()
        assert conn.scalar(text('select count(*) from ha_shared_state')) == 0


def test_pg_expiry_and_no_implicit_json_import(pg, safe_modules):
    oidc, mail = safe_modules
    from app.services import ha_state
    oidc.CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    oidc.CLIENT_FILE.write_text(json.dumps({'legacy': {'client_secret': 'old'}}))
    mail.CONFIG_FILE.write_text(json.dumps({'password': 'old'}))
    assert oidc._load_clients() == {}
    assert mail._load()['password'] == ''
    with ha_state.locked_state('oidc.runtime', {'codes': {}, 'tokens': {}}) as state:
        state['codes']['expired'] = {'expires': 0}
        state['tokens']['expired'] = {'expires': 0}
    assert oidc.userinfo('expired') is None
    assert oidc.exchange_code('expired', 'rp', 'x', 'cb') is None


def test_pg_concurrent_client_creation_and_masked_smtp(pg, safe_modules):
    oidc, mail = safe_modules
    with ThreadPoolExecutor(max_workers=8) as pool:
        secrets = list(pool.map(lambda _: oidc.get_client_secret('race'), range(16)))
    assert len(set(secrets)) == 1
    mail.put_config(mail.EmailConfigIn(host='h', username='u', password='keep'), None)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: mail.put_config(mail.EmailConfigIn(host=str(i), username='u', password='••••••'), None), range(16)))
    assert mail._load()['password'] == 'keep'


def test_pg_failure_never_falls_back(safe_modules, monkeypatch):
    oidc, mail = safe_modules
    from app.services import ha_state
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    def unavailable():
        raise RuntimeError('unavailable')
    monkeypatch.setattr(ha_state, '_engine', unavailable)
    for operation in (mail._load, lambda: mail._save({}), lambda: oidc.create_authorization_code('c', 'cb', 'u', 'n', '', None)):
        with pytest.raises(RuntimeError, match='unavailable'):
            operation()
    assert not mail.CONFIG_FILE.exists()
    assert not oidc.CLIENT_FILE.exists()


def test_default_legacy_unchanged(safe_modules):
    oidc, mail = safe_modules
    secret = oidc.get_client_secret('rp')
    assert oidc.CLIENT_FILE.exists()
    code = oidc.create_authorization_code('rp', 'cb', 'u', 'user', '', None)
    token = oidc.exchange_code(code, 'rp', secret, 'cb')
    assert token and oidc.exchange_code(code, 'rp', secret, 'cb') is None
    mail._save({**mail.DEFAULTS, 'password': 'old'})
    mail.put_config(mail.EmailConfigIn(host='h', username='u', password='••••••'), None)
    assert mail.CONFIG_FILE.exists() and mail._load()['password'] == 'old'
