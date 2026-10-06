"""Private receipt reads; no live database, SMTP, SSH or production writes."""
import importlib.util
import json
from datetime import datetime, timezone

def test_receipt_contract(tmp_path):
    assert importlib.util.find_spec('app.services.backup_health') is not None, 'backup receipt reader missing'
    from app.services.backup_health import read_backup_health
    receipt = {'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'verified',
               'checksumverified': True, 'restoreverified': False, 'source': 'postgres-dump',
               'private_path': '/root/.credentials/do-not-return', 'dump_list_verified': True}
    (tmp_path / 'backup.json').write_text(json.dumps(receipt))
    result = read_backup_health(tmp_path)
    assert set(result) == {'timestamp', 'status', 'checksumverified', 'restoreverified', 'source'}
    assert result['checksumverified'] is True
    assert result['restoreverified'] is False
    assert '/root' not in json.dumps(result)


def test_untrusted_receipts_fail_closed(tmp_path):
    from app.services.backup_health import read_backup_health
    receipt = {'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'verified',
               'checksumverified': 'false', 'restoreverified': 'yes', 'source': 'postgres-dump'}
    (tmp_path / 'bad.json').write_text(json.dumps(receipt))
    assert read_backup_health(tmp_path)['status'] == 'invalid'


def test_symlink_not_read(tmp_path):
    from app.services.backup_health import read_backup_health
    outside = tmp_path.parent / 'private.json'
    outside.write_text(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'verified',
                                   'checksumverified': True, 'restoreverified': True, 'source': 'postgres-dump'}))
    (tmp_path / 'backup.json').symlink_to(outside)
    assert read_backup_health(tmp_path)['status'] == 'invalid'


def test_stale_and_future_receipts(tmp_path):
    from app.services.backup_health import read_backup_health
    receipt = {'timestamp': '2026-01-01T00:00:00Z', 'status': 'verified',
               'checksumverified': True, 'restoreverified': False, 'source': 'postgres-dump'}
    (tmp_path / 'backup.json').write_text(json.dumps(receipt))
    assert read_backup_health(tmp_path, now=datetime(2026, 1, 4, tzinfo=timezone.utc))['status'] == 'stale'
    assert read_backup_health(tmp_path, now=datetime(2025, 1, 4, tzinfo=timezone.utc))['status'] == 'invalid'


def test_audit_persists_without_secret_payload():
    from app.services import backup_health as svc
    assert hasattr(svc, 'record_change'), 'audit writer missing'
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.config import AppConfig
    engine = create_engine('sqlite:///:memory:')
    AppConfig.__table__.create(engine)
    actor = '7f925ced-5453-4f7f-b6ef-46545169d9c9'
    with Session(engine) as db:
        for _ in range(205):
            svc.record_change(db, action='integration.update', actor_id=actor,
                              changed_fields=['title', 'token', 'password', 'script', 'enabled'],
                              payload={'password': 'never-store', 'url': 'https://private/?token=never-store'})
        db.commit()
    with Session(engine) as db:
        events = svc.read_change_audit(db)
        assert len(events) == 200
        assert events[0]['changed_fields'] == ['enabled', 'title']
        assert 'never-store' not in db.get(AppConfig, svc.AUDIT_KEY).value
        svc.record_change(db, action='security.lock', actor_id=actor)
        db.rollback()
        assert svc.read_change_audit(db) == events


def test_real_readonly_api_requires_auth_and_hides_paths(tmp_path, monkeypatch):
    assert importlib.util.find_spec('app.routers.operations_status') is not None, 'operations router missing'
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.operations_status import router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.setenv('STELLA_BACKUP_RECEIPT_DIR', str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get('/operations/backup-health').status_code == 401
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id='owner')
    response = client.get('/operations/backup-health')
    assert response.status_code == 200
    assert response.json()['status'] == 'missing'
    assert set(response.json()) == {'timestamp','status','checksumverified','restoreverified','source'}
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/operations/backup-health').status_code == 405
    app.dependency_overrides[admin_user] = lambda: SimpleNamespace(id='owner')
    db = Mock()
    db.get.return_value = None
    app.dependency_overrides[get_db] = lambda: db
    assert client.get('/operations/change-audit').json() == {'events': [], 'limit': 200}
    db.commit.assert_not_called()


def test_backup_receipt_producer_does_not_claim_restore(tmp_path, monkeypatch):
    path = __import__('pathlib').Path(__file__).parents[1] / 'scripts' / 'backup_health_receipt.py'
    assert path.exists(), 'backup receipt producer missing'
    import importlib.util
    spec = importlib.util.spec_from_file_location('backup_receipt', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dump = tmp_path / 'backup.dump'
    dump.write_bytes(b'PGDMP-test')
    expected = __import__('hashlib').sha256(dump.read_bytes()).hexdigest()
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: __import__('subprocess').CompletedProcess(args, 0))
    receipt = module.make_receipt(dump, expected, 'isolated-pg')
    assert receipt['checksumverified'] is True
    assert receipt['restoreverified'] is False
    assert receipt['dump_list_verified'] is True
    assert receipt['status'] == 'verified'
    failed = module.make_receipt(dump, '0' * 64, 'isolated-pg')
    assert failed['status'] == 'failed'


def test_ingress_bundle_preserves_host_and_reuses_existing_ha(tmp_path):
    path = __import__('pathlib').Path(__file__).parents[1] / 'deploy' / 'integrations' / 'prepare.py'
    assert path.exists(), 'deployment bundle generator missing'
    import importlib.util
    spec = importlib.util.spec_from_file_location('ingress_prepare', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    conf = module.render_nginx('/etc/ssl/xiya.live/fullchain.pem', '/etc/ssl/xiya.live/privkey.pem')
    assert 'proxy_set_header Host $http_host;' in conf
    assert 'proxy_pass http://127.0.0.1:12031;' in conf
    assert 'proxy_buffering off;' in conf
    assert 'proxy_request_buffering off;' in conf
    assert 'proxy_set_header Range $http_range;' in conf
    assert 'proxy_redirect off;' in conf
    assert 'proxy_hide_header Content-Security-Policy' not in conf
    assert '$request_uri' not in conf.split('log_format')[1].split(';', 1)[0]
    assert 'reload' not in module.validation_commands(tmp_path)
