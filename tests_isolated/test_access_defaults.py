"""Default same-entry selection does not require the retired global switch."""
import json
import pytest
from fastapi import HTTPException
from tests_isolated.test_access_entries import access, P, L, OWNER
from tests_website_settings.test_website_settings import api_env


def test_legacy_disabled_row_defaults_to_registered_side_without_writing(access):
    from app.models.config import AppConfig
    from app.services import access_entries as service, entry_registry as registry
    c, factory, *_ = access
    legacy = {'revision':10,'enabled':False,'public_origin':P,'private_origin':L}
    raw = json.dumps({'owner_id':OWNER,'settings':legacy})
    with factory() as db:
        db.add(AppConfig(key=service.KEY,value=raw)); db.commit()
    with service.request_snapshot(factory):
        assert service.lane(L) == 'private'
        assert service.lane(L,policy='public') == 'public'
        assert registry.browser_url(dict(id='direct',mode='iframe',browser_url='https://remote.test/path',private_address='https://remote.lan.test/path'), L) == 'https://remote.lan.test/path'
        assert registry.browser_url(dict(id='thirdparty',mode='iframe',browser_url='https://thirdparty.test/path'), L) == 'https://thirdparty.test/path'
        with pytest.raises(HTTPException): service.lane('https://stella.p.test.evil')
    with factory() as db:
        assert db.get(AppConfig,service.KEY).value == raw


def test_registered_public_only_direct_website_keeps_original_address(access,monkeypatch):
    from app.services import entry_registry as registry
    import os
    rows=json.loads(os.environ['STELLA_ENTRY_REGISTRY'])
    rows.append({'service_id':'external','public':'https://external.test'})
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
    assert registry.browser_url(dict(id='external',mode='iframe',browser_url='https://external.test/path'),L) == 'https://external.test/path'


def test_private_entry_validation_cannot_be_bypassed_by_legacy_disabled_flag(access):
    c,*_=access
    draft=c.get('/config/access-entries').json()['settings']|{'enabled':False,'private_origin':'https://unknown.test'}
    checked=c.post('/config/access-entries/check',json=draft)
    assert checked.status_code == 200
    assert checked.json()['can_apply'] is False
