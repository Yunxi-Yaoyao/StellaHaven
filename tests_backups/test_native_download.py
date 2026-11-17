import io
import os
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def download_client():
    from app.routers import backups
    app = FastAPI()
    app.include_router(backups.router)
    # Focused transport test only; real management auth is exercised separately.
    app.dependency_overrides[backups.admin_user] = lambda: object()
    app.dependency_overrides[backups.get_db] = lambda: None
    return backups, app


def test_head_download_probes_metadata_without_hashing_or_reading_whole_zip(download_client, monkeypatch, tmp_path):
    from contextlib import contextmanager
    module, app = download_client
    calls = []
    probe = tmp_path / 'sparse-test-metadata'
    with probe.open('wb') as file:
        file.truncate(1024**3)
    real = probe.open('rb')
    stream = Mock()
    stream.fileno.return_value = real.fileno()
    @contextmanager
    def opened(identity, *, verify=True):
        calls.append((identity, verify))
        yield {'filename': 'stella-all-'+'a'*32+'.zip', 'bytes': 1024**3}, stream
    monkeypatch.setattr(module, 'release', lambda *a: None)
    monkeypatch.setattr(module, 'center', lambda *a: type('C', (), {'store': lambda self: type('S', (), {'open_record': staticmethod(opened)})()})())
    try:
        with TestClient(app) as client:
            response = client.head('/operations/backups/signed-record/download')
    finally:
        real.close()
    assert response.status_code == 200
    assert response.content == b''
    assert response.headers['content-length'] == str(1024**3)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-type'] == 'application/zip'
    assert calls == [('signed-record', False)]
    stream.read.assert_not_called()


def test_real_download_head_remains_management_only():
    from app.routers.backups import router
    app = FastAPI()
    app.include_router(router)
    # No cookie must fail authentication without requiring center initialization.
    with TestClient(app) as client:
        response = client.head('/operations/backups/signed-record/download')
    assert response.status_code == 401
