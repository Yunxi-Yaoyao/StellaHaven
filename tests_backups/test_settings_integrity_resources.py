"""B03: settings ZIP dependencies include typed catalog filenames, not just URLs."""
import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy.orm import Session


def settings_zip(engine, tmp_path, filename='settings.zip'):
    from app.services.backup_projection import export_settings
    from app.services.backup_archive import create_archive
    path = tmp_path / filename
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn, tmp_path) as payload:
            create_archive(path, scope='settings', entries=payload.entries, warnings=payload.warnings)
    return path


def test_missing_unselected_catalog_original_refuses_settings_zip(engine, tmp_path):
    from app.models.config import AppConfig
    from app.services.backup_archive import InvalidArchive
    entry = dict(id='legacy-unselected', name='Catalog only', ext='jpg', file='missing.jpg',
                 owner=None, isDefault=False)
    with Session(engine) as db:
        db.add(AppConfig(key='homebg_index', value=json.dumps([entry])))
        db.commit()
    with pytest.raises(InvalidArchive, match='missing configuration resource'):
        settings_zip(engine, tmp_path)
    assert not (tmp_path / 'settings.zip').exists()


def test_self_consistent_zip_with_missing_catalog_original_cannot_restore(engine, tmp_path):
    from app.models.config import AppConfig
    from app.services.backup_projection import restore_settings, TABLES
    from app.services.backup_config_projection import project_config
    from app.services.backup_archive import create_archive, validate_archive, InvalidArchive
    data = dict(version=1, profiles=[], config=[
        dict(key='public_host', value='https://archive.invalid'),
        dict(key='homebg_index', value=project_config('homebg_index', json.dumps([
            dict(id='unselected', name='Legacy bare filename', ext='jpg', file='absent.jpg', isDefault=False)])))],
        tables={name: [] for name in TABLES}, shared=[], resources={})
    path = tmp_path / 'internally-valid-but-incomplete.zip'
    create_archive(path, scope='settings', entries={'settings.json': io.BytesIO(json.dumps(data).encode())})
    assert validate_archive(path)['scope'] == 'settings', 'byte-level ZIP integrity is not dependency completeness'
    with Session(engine) as db:
        db.add(AppConfig(key='public_host', value='https://keep-current.invalid'))
        db.commit()
    with pytest.raises(InvalidArchive, match='missing configuration resource'):
        restore_settings(engine, path)
    with Session(engine) as db:
        assert db.get(AppConfig, 'public_host').value == 'https://keep-current.invalid'
        assert db.get(AppConfig, 'homebg_index') is None


ASSET_KEYS = ('homebg/catalog-only.jpg', 'homebg/movie.mp4', 'homebg/media-url.mp4',
              'homebg/poster.webp', 'homebg/thumbnail.webp', 'homebg/display.webp',
              'homebg/variant-original.mp4', 'homebg/compressed1.mp4', 'homebg/compressed2.mp4',
              'homebg/profile-only.jpg', 'avatars/current.png', 'avatars/history1.png', 'avatars/history2.png')


def seed_assets(engine):
    from app.models.config import AppConfig
    from app.models.user import User
    from app.services import blob_store
    owner = uuid.uuid4()
    history = ['/assets/avatars/history1.png', '/assets/avatars/history2.png']
    catalog = [dict(id='unselected-bare', name='No sidecar', ext='jpg', file='catalog-only.jpg', isDefault=False),
               dict(id='movie', name='All media slots', ext='mp4', file='movie.mp4', isDefault=False,
                    media=dict(url='/assets/homebg/media-url.mp4', status='ready',
                               poster='/assets/homebg/poster.webp', thumbnail='/assets/homebg/thumbnail.webp',
                               display='/assets/homebg/display.webp',
                               variants=dict(original='/assets/homebg/variant-original.mp4',
                                             compressed1='/assets/homebg/compressed1.mp4',
                                             compressed2='/assets/homebg/compressed2.mp4')))]
    assets = {key: ('synthetic-resource:' + key).encode() for key in ASSET_KEYS}
    with Session(engine) as db:
        db.add(User(id=owner, username='asset-owner', display_name='Assets', password_hash='synthetic-identity',
                    avatar_url='/assets/avatars/current.png', avatar_history=json.dumps(history),
                    home_bg='/assets/homebg/profile-only.jpg'))
        db.add(AppConfig(key='homebg_index', value=json.dumps(catalog)))
        db.add(AppConfig(key='public_host', value='https://archive.invalid'))
        for key, content in assets.items():
            blob_store.put(db, key, io.BytesIO(content), 'image/webp' if key.endswith('.webp') else 'application/octet-stream', 1000)
        db.commit()
    return owner, history, catalog, assets


@pytest.mark.parametrize('missing_key', ASSET_KEYS)
def test_every_configuration_dependency_is_required_in_pg_and_zip(engine, tmp_path, missing_key):
    from app.models.config import AppConfig
    from app.services import blob_store
    from app.services.backup_projection import restore_settings
    from app.services.backup_archive import InvalidArchive, create_archive, validate_archive
    seed_assets(engine)
    good = settings_zip(engine, tmp_path)
    with Session(engine) as db:
        blob_store.delete(db, missing_key)
        db.get(AppConfig, 'public_host').value = 'https://keep-live.invalid'
        db.commit()
    with pytest.raises(InvalidArchive, match='missing configuration resource'):
        settings_zip(engine, tmp_path, filename='missing-pg.zip')
    assert not (tmp_path / 'missing-pg.zip').exists()
    with zipfile.ZipFile(good) as z:
        data = json.loads(z.read('settings.json'))
        del data['resources'][missing_key]
        entries = {name: io.BytesIO(z.read(name)) for name in z.namelist()
                   if name not in ('manifest.json', 'settings.json', 'resources/' + missing_key)}
        entries['settings.json'] = io.BytesIO(json.dumps(data).encode())
    missing_zip = tmp_path / 'self-consistent-missing.zip'
    create_archive(missing_zip, scope='settings', entries=entries)
    validate_archive(missing_zip)
    with pytest.raises(InvalidArchive, match='missing configuration resource'):
        restore_settings(engine, missing_zip)
    with Session(engine) as db:
        assert db.get(AppConfig, 'public_host').value == 'https://keep-live.invalid'
        assert blob_store.metadata(db, missing_key) is None


def test_complete_configuration_asset_graph_roundtrips_bytes_hashes_and_references(engine, tmp_path):
    import hashlib
    from app.models.config import AppConfig
    from app.models.user import User
    from app.services import blob_store
    from app.services.backup_projection import restore_settings, configuration_resources
    owner, history, catalog, assets = seed_assets(engine)
    archive = settings_zip(engine, tmp_path)
    with zipfile.ZipFile(archive) as z:
        data = json.loads(z.read('settings.json'))
        assert configuration_resources(data) == set(assets)
        assert set(data['resources']) == set(assets)
        for key, content in assets.items():
            assert z.read('resources/' + key) == content
            assert data['resources'][key]['sha256'] == hashlib.sha256(content).hexdigest()
    with Session(engine) as db:
        user = db.get(User, owner)
        user.avatar_url, user.avatar_history, user.home_bg = '', '[]', ''
        db.get(AppConfig, 'homebg_index').value = '[]'
        for key in assets:
            blob_store.delete(db, key)
        db.commit()
    restore_settings(engine, archive)
    with Session(engine) as db:
        user = db.get(User, owner)
        assert (user.avatar_url, json.loads(user.avatar_history), user.home_bg) == (
            '/assets/avatars/current.png', history, '/assets/homebg/profile-only.jpg')
        assert json.loads(db.get(AppConfig, 'homebg_index').value) == catalog
        for key, content in assets.items():
            meta = blob_store.metadata(db, key)
            assert (meta['size'], meta['sha256'], meta['mime']) == (
                len(content), hashlib.sha256(content).hexdigest(), data['resources'][key]['mime'])
            assert b''.join(blob_store.read_range(db, key, 0, meta['size'])) == content
