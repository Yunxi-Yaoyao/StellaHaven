"""Explicit migration, no startup/GET migration or service writes."""
import copy
import importlib.util
import json
import pytest
from tests_generic_templates.test_generic_templates import api_env


def seed(factory):
    from app.models.config import AppConfig
    from app.services import integrations as store, builtin_injection as builtin
    state = store.empty_state()
    state['modules']['a'*32] = dict(id='a'*32,name='Quota',icon='globe',adapter='generic',mode='isolated_proxy',browser_url='http://127.0.0.1:5255/',target_id='quota-target',initial_path='/',enabled=True,injection=dict(active=None,draft=None,previous=None),origin='https://app-'+('a'*32)+'.xiya.live')
    state['targets']['quota-target'] = {'id':'quota-target','untouched':'sentinel'}
    state['navigation'] = [dict(id='notes',visible=True),dict(id='drive',title='My files',icon='folder',visible=False),dict(id='a'*32,visible=True),dict(id='gallery',title='Photos',icon='image',visible=True)]
    versions = builtin.empty_state()
    versions['drive']['active'].update(enabled=True,css='body{--custom:1}',js='window.custom=1')
    versions['drive']['draft'] = versions['drive']['active'] | {'css':'body{--unpublished:1}'}
    versions['drive']['previous'] = versions['drive']['active'] | {'css':'body{--old:1}'}
    rows = {store.KEY:state,builtin.KEY:versions,'external_drive_connection':{'browser_url':'http://127.0.0.1:12544/drive/openlist/','upstream_url':'http://127.0.0.1:12544/drive/openlist/','auth_mode':'token','token':'synthetic-only'},'external_gallery_connection':{'browser_url':'https://immich.test','auth_mode':'oidc'}}
    with factory() as db:
        for key, value in rows.items(): db.add(AppConfig(key=key,value=json.dumps(value)))
        db.commit()
    return rows


def test_migration_preserves_nav_quota_credentials_and_versions_atomically(api_env):
    assert importlib.util.find_spec('app.services.website_migration'), 'explicit migration missing'
    from app.services.website_migration import migrate_legacy, rollback_legacy
    from app.services import integrations as store
    from app.models.config import AppConfig
    c, factory, _, _ = api_env
    rows = seed(factory)
    with factory() as db:
        result = migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001',main_origin='https://stella.test')
        state = store.state(db)
        assert set(result) == {'drive','gallery'}
        drive = state['modules'][result['drive']]; gallery=state['modules'][result['gallery']]
        assert drive['adapter'] == gallery['adapter'] == 'generic'
        assert drive['template_id'] == 'openlist' and gallery['template_id'] == 'immich'
        assert drive['name'] == 'My files'
        assert state['navigation'][1]['id'] == result['drive'] and state['navigation'][1]['visible'] is False
        assert state['navigation'][2]['id'] == 'a'*32
        assert state['modules']['a'*32] == rows[store.KEY]['modules']['a'*32]
        assert state['targets']['quota-target'] == rows[store.KEY]['targets']['quota-target']
        assert 'body{--custom:1}' in drive['injection']['active']['css']
        assert drive['injection']['draft'] == {k:v for k,v in drive['injection']['active'].items() if k!='version'}
        assert drive['migration']['legacy_injection']['draft']['css'] == 'body{--unpublished:1}'
        assert gallery['browser_url'] == 'https://immich.test/' and gallery['target_id'] is None
        assert drive['initial_path'] == '/drive/openlist/'
        assert state['targets'][drive['target_id']]['upstream_url'] == 'http://127.0.0.1:12544/'
        assert state['targets'][drive['target_id']]['headers']['authorization'] == 'synthetic-only'
        for key,value in rows.items():
            if key != store.KEY: assert json.loads(db.get(AppConfig,key).value) == value
        assert migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001',main_origin='https://stella.test') == result
        assert store.navigation(db)['legacy_routes'] == result
        rollback_legacy(db)
        assert store.state(db) == rows[store.KEY]
        migrated = migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001',main_origin='https://stella.test')
        store.delete_module(db,migrated['drive'],'00000000-0000-4000-8000-000000000001')
        assert 'drive' not in store.navigation(db)['legacy_routes']
        migrate_legacy(db,approved_ips=['127.0.0.1'],actor_id='00000000-0000-4000-8000-000000000001',main_origin='https://stella.test')
        assert migrated['drive'] not in store.state(db)['modules']
