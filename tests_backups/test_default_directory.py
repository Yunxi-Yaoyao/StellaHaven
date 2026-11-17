from datetime import datetime, timezone
import pytest
from sqlalchemy import text


def test_uncreated_default_directory_advertises_safe_initialization_without_side_effects(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    from app.schemas.backups import Status
    root = tmp_path / 'uncreated-data'
    center = BackupCenter(engine, root, key=b'parent-fixture')
    status = Status.model_validate(center.status()).model_dump()
    assert status['storage']['available'] is False
    assert status['storage'].get('can_initialize_default') is True
    assert status['storage']['free_bytes'] > 0
    assert not root.exists()
    assert center.tick(datetime.now(timezone.utc)) is None
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app_config WHERE key='backup_center_v1'")).scalar_one() == 0
    center.submit('backup', 'settings')
    center.wait()
    assert center.status()['job']['state'] == 'succeeded'
    assert center.status()['storage']['available'] is True
    assert not center.status()['storage']['can_initialize_default']
    assert len(center.status()['records']) == 1


def test_missing_custom_directory_is_not_offered_automatic_creation(engine, tmp_path):
    import json
    from app.services.backup_center import BackupCenter, KEY
    from app.schemas.backups import Config
    missing = tmp_path / 'custom-missing'
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO app_config(key,value) VALUES (:key,:value)'),
                     {'key': KEY, 'value': json.dumps({'config': Config(directory=str(missing)).model_dump(), 'job': None})})
    state = BackupCenter(engine, tmp_path / 'data', key=b'fixture').status()
    assert state['storage']['available'] is False
    assert state['storage']['can_initialize_default'] is False
    assert not missing.exists()


def test_default_directory_cannot_be_initialized_through_symlink(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    outside = tmp_path / 'outside'
    outside.mkdir()
    linked = tmp_path / 'linked'
    linked.symlink_to(outside, target_is_directory=True)
    state = BackupCenter(engine, linked / 'data', key=b'fixture').status()
    assert state['storage']['available'] is False
    assert state['storage']['can_initialize_default'] is False
    assert not (outside / 'data').exists()
