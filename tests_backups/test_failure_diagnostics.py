"""Only synthetic owned PG data; failures retain all prior archive bytes."""
import hashlib
import io
import json
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


def persisted_job(engine):
    with engine.connect() as conn:
        return json.loads(conn.execute(text("SELECT value FROM app_config WHERE key='backup_center_v1'")).scalar_one())['job']


def test_resource_guard_has_safe_reason_stage_job_correlation_and_preserves_old(engine, tmp_path, caplog):
    from app.services.backup_center import BackupCenter
    from app.services import blob_store
    from app.models.blob import BlobObject
    center = BackupCenter(engine, tmp_path / 'data', key=b'fixture')
    for _ in range(2):
        center.submit('backup', 'settings')
        center.wait()
        assert center.status()['job']['state'] == 'succeeded'
    records = center.status()['records']
    before = {r['filename']: hashlib.sha256((center.store().path / r['filename']).read_bytes()).hexdigest() for r in records}
    with Session(engine) as db:
        blob_store.put(db, 'homebg/synthetic.png', io.BytesIO(b'SYNTHETIC-PRIVATE-RESOURCE'), 'image/png', 1024)
        db.get(BlobObject, 'homebg/synthetic.png').sha256 = '0' * 64
        db.commit()
    caplog.set_level(logging.WARNING, logger='app.services.backup_center')
    accepted = center.submit('backup', 'settings')
    center.wait()
    job = persisted_job(engine)
    assert job['id'] == accepted['id'] and job['state'] == 'failed'
    assert job.get('reason_code') == 'configuration_resource_checksum_mismatch'
    assert job.get('failed_stage') == 'exporting'
    assert center.status()['records'] == records
    assert {r['filename']: hashlib.sha256((center.store().path / r['filename']).read_bytes()).hexdigest() for r in records} == before
    message = caplog.text
    assert accepted['id'] in message and 'configuration_resource_checksum_mismatch' in message and 'exporting' in message
    assert 'SYNTHETIC-PRIVATE-RESOURCE' not in message and 'synthetic.png' not in message


def test_unknown_error_cannot_export_exception_string_or_dynamic_class(engine, tmp_path, monkeypatch, caplog):
    import app.services.backup_center as module
    from contextlib import contextmanager
    class PRIVATE_CLASS_NAME(RuntimeError):
        pass
    @contextmanager
    def bad(*args):
        raise PRIVATE_CLASS_NAME('postgres://user:password@private SELECT resource secret')
        yield
    monkeypatch.setattr(module, 'export_settings', bad)
    caplog.set_level(logging.WARNING, logger=module.__name__)
    center = module.BackupCenter(engine, tmp_path / 'data', key=b'fixture')
    center.submit('backup', 'settings')
    center.wait()
    job = persisted_job(engine)
    assert job.get('reason_code') == 'operation_failed'
    assert job.get('failed_stage') == 'exporting'
    public = json.dumps(job) + caplog.text
    for secret in ('PRIVATE_CLASS_NAME', 'password', 'private', 'SELECT', 'resource secret'):
        assert secret not in public


def test_legacy_failure_read_and_recover_do_not_invent_reason(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    from app.schemas.backups import Config, Job
    old = dict(id='151e79b465154e0e950593d1101a441b', kind='backup', scope='settings', state='failed', stage='failed', error='legacy InvalidArchive', record_id=None)
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO app_config (key,value) VALUES (:key,:value)'), {'key':'backup_center_v1', 'value':json.dumps(dict(config=Config().model_dump(), job=old, last_slot=None))})
    center = BackupCenter(engine, tmp_path / 'data', key=b'fixture')
    assert center.status()['job'] == old
    center.recover()
    assert persisted_job(engine) == old
    assert Job.model_validate(old).model_dump().get('reason_code') is None
    assert Job.model_validate(old).model_dump().get('failed_stage') is None
