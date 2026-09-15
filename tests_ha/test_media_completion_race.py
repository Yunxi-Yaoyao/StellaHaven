"""Deterministic completion/read race. Uses actual sidecars and actual flock."""
import pytest
from app.services import homebg_media as media

@pytest.mark.parametrize('initial',['queued','processing'])
@pytest.mark.parametrize('terminal',['ready','error'])
def test_finished_worker_is_not_reported_missing(tmp_path,monkeypatch,initial,terminal):
    source=tmp_path/'sample.png';source.write_bytes(b'unchanged-source')
    url='/assets/homebg/sample.png'
    data=dict(media._base(url),status=initial,_identity=media._identity(source))
    media._save(source,data)
    media._lock_path(source).touch()
    original=media.fcntl.flock;published=False
    def finish_between_sidecar_read_and_lock_check(fd,operation):
        nonlocal published
        if operation==media.fcntl.LOCK_EX|media.fcntl.LOCK_NB and not published:
            published=True
            media._save(source,dict(data,status=terminal))
        return original(fd,operation)
    monkeypatch.setattr(media.fcntl,'flock',finish_between_sidecar_read_and_lock_check)
    assert media.metadata(tmp_path,url)['status']==terminal
    assert published
