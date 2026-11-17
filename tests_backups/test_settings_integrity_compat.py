"""B04: preserve live protection/compatibility settings, never migration snapshots."""
import hashlib
import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy.orm import Session
from tests_backups.test_settings_integrity_resources import settings_zip


def test_restored_system_background_stays_undeletable(engine, tmp_path):
    from fastapi import HTTPException
    from app.models.user import User
    from app.models.config import AppConfig
    from app.services import blob_store
    from app.services.backup_projection import restore_settings
    from app.routers import homebg
    uid = uuid.uuid4()
    entry = dict(id='protected-system', name='System asset', ext='jpg', file='system.jpg',
                 isDefault=False, isSystem=True, owner=None)
    with Session(engine) as db:
        db.add(User(id=uid, username='system-owner', display_name='Owner', password_hash='synthetic-identity'))
        db.add(AppConfig(key='homebg_index', value=json.dumps([entry])))
        blob_store.put(db, 'homebg/system.jpg', io.BytesIO(b'system-background-bytes'), 'image/jpeg', 1000)
        db.commit()
    path = settings_zip(engine, tmp_path)
    with Session(engine) as db:
        db.get(AppConfig, 'homebg_index').value = json.dumps([entry | {'isSystem': False}])
        db.commit()
    restore_settings(engine, path)
    with Session(engine) as db:
        owner = db.get(User, uid)
        assert homebg.list_homebg(user=owner, db=db)[0]['isSystem'] is True
        with pytest.raises(HTTPException) as denied:
            homebg.delete_homebg('protected-system', user=owner, db=db)
        assert denied.value.status_code == 400
        db.rollback()
    with Session(engine) as db:
        assert json.loads(db.get(AppConfig, 'homebg_index').value)[0]['isSystem'] is True
        assert blob_store.metadata(db, 'homebg/system.jpg')['size'] == len(b'system-background-bytes')


@pytest.mark.parametrize('current_aliases', [None, {'drive': 'wrong-current-module'}], ids=['absent-aliases', 'changed-aliases'])
def test_restored_migration_alias_and_exact_dedup_remain_active(engine, tmp_path, current_aliases):
    from app.models.config import AppConfig
    from app.public_website import public_navigation
    from app.services import integrations
    from app.services.integrations_injection import strip_migrated_html
    from app.services.backup_projection import restore_settings
    mid = uuid.uuid4().hex
    css, js = '.legacy {color:red}', 'window.legacy = true;'
    signatures = {'style': [hashlib.sha256(css.encode()).hexdigest()],
                  'script': [hashlib.sha256(js.encode()).hexdigest()]}
    module = integrations.ModuleInput(name='Migrated drive', browser_url='https://fixture.invalid').model_dump()
    module.update(id=mid, migration=dict(exact_legacy_sha256=signatures | {'unknown': 'DIGEST-EXTENSION-PRIVATE'},
                  before={'secret': 'MIGRATION-BEFORE-PRIVATE'}, legacy_injection={'token': 'LEGACY-SNAPSHOT-PRIVATE'}))
    source = dict(modules={mid: module}, targets={}, navigation=[],
                  legacy_routes={'drive': mid, 'unknown': {'secret': 'ALIAS-EXTENSION-PRIVATE'}},
                  website_migration_v1={'before': {'private': 'WHOLE-BEFORE-PRIVATE'}},
                  grants={'old': 'OLD-GRANT-PRIVATE'})
    with Session(engine) as db:
        db.add(AppConfig(key='integrations_v1', value=json.dumps(source)))
        db.commit()
    path = settings_zip(engine, tmp_path)
    with zipfile.ZipFile(path) as z:
        raw = z.read('settings.json')
        for private in (b'MIGRATION-BEFORE-PRIVATE', b'LEGACY-SNAPSHOT-PRIVATE', b'WHOLE-BEFORE-PRIVATE',
                        b'OLD-GRANT-PRIVATE', b'ALIAS-EXTENSION-PRIVATE', b'DIGEST-EXTENSION-PRIVATE'):
            assert private not in raw
    target = dict(modules={}, targets={}, navigation=[], grants={'current': 'KEEP-CURRENT-GRANT'})
    if current_aliases is not None:
        target['legacy_routes'] = current_aliases
    with Session(engine) as db:
        db.get(AppConfig, 'integrations_v1').value = json.dumps(target)
        db.commit()
    restore_settings(engine, path)
    html = f'<style>{css}</style><script>{js}</script><script>window.different = true;</script>'
    with Session(engine) as db:
        restored = json.loads(db.get(AppConfig, 'integrations_v1').value)
        actual = dict(aliases=public_navigation(restored, integrations.BUILTINS)['legacy_routes'],
                      stripped=strip_migrated_html(html, restored['modules'][mid]))
        assert actual == dict(aliases={'drive': mid}, stripped='<script>window.different = true;</script>')
        assert restored['modules'][mid]['migration'] == {'exact_legacy_sha256': signatures}
        assert restored['grants'] == {'current': 'KEEP-CURRENT-GRANT'}
        assert 'website_migration_v1' not in restored


def test_archive_without_legacy_aliases_does_not_keep_newer_aliases(engine, tmp_path):
    from app.models.config import AppConfig
    from app.services import integrations
    from app.services.backup_projection import restore_settings
    mid = uuid.uuid4().hex
    module = integrations.ModuleInput(name='Unmigrated website', browser_url='https://fixture.invalid').model_dump() | {'id': mid}
    registry = dict(modules={mid: module}, targets={}, navigation=[])
    with Session(engine) as db:
        db.add(AppConfig(key='integrations_v1', value=json.dumps(registry)))
        db.commit()
    path = settings_zip(engine, tmp_path)
    with Session(engine) as db:
        db.get(AppConfig, 'integrations_v1').value = json.dumps(registry | {'legacy_routes': {'drive': mid}, 'grants': {'current': 'keep'}})
        db.commit()
    restore_settings(engine, path)
    with Session(engine) as db:
        restored = json.loads(db.get(AppConfig, 'integrations_v1').value)
        assert restored.get('legacy_routes', {}) == {}, 'absent archive aliases mean none, not retain a newer identity binding'
        assert restored['grants'] == {'current': 'keep'}
