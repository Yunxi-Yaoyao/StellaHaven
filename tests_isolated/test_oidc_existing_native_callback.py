"""Regression from actual deployed Immich's registered native-app callback."""
from pathlib import Path
from unittest.mock import patch
import pytest


def test_exact_existing_native_app_callback_preserved_on_managed_edit(tmp_path,monkeypatch):
    from app.services import oidc
    monkeypatch.delenv('STELLA_SHARED_STATE',raising=False)
    monkeypatch.setattr(oidc,'CLIENT_FILE',tmp_path/'clients.json')
    original={'client_secret':'private-fixture','redirect_uris':['app.immich:///oauth-callback','http://192.168.1.5:2283/auth/login','https://immich.example.test/auth/login']}
    with oidc._locked_clients() as clients:clients['immich']=original.copy()
    result=oidc.update_client('immich',{'name':'相册','redirect_uris':original['redirect_uris']})
    assert result['redirect_uris']==original['redirect_uris']
    assert oidc.get_client_secret('immich')=='private-fixture'
    with pytest.raises(ValueError):oidc.update_client('immich',{'redirect_uris':['app.immich:///different']})
    with pytest.raises(ValueError):oidc.create_client('other',name='Other',redirect_uris=['app.immich:///oauth-callback'])
