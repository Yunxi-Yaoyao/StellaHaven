import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

def test_cross_process_oauth_code_and_token_are_shared_and_single_use(tmp_path, monkeypatch):
    from app.services import oidc
    spec=importlib.util.spec_from_file_location('other_oidc',Path(oidc.__file__))
    other=importlib.util.module_from_spec(spec);spec.loader.exec_module(other)
    for module in (oidc,other):
        monkeypatch.setattr(module,'OIDC_DIR',tmp_path)
        monkeypatch.setattr(module,'get_client_secret',lambda _: 'test-secret')
        monkeypatch.setattr(module,'_sign_id_token',lambda *a,**kw: 'signed')
    code=oidc.create_authorization_code('immich','https://photos.test/callback','user','User','mail@test',None)
    assert other.exchange_code(code,'immich','wrong','https://photos.test/callback') is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda mod:mod.exchange_code(code,'immich','test-secret','https://photos.test/callback'),(oidc,other)))
    successes=[r for r in results if r]
    assert len(successes)==1
    assert other.userinfo(successes[0]['access_token'])['sub']=='user'
    assert oidc.exchange_code(code,'immich','test-secret','https://photos.test/callback') is None
