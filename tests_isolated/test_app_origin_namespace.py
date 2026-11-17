"""No DB/network: operator namespace only affects newly derived module origins."""
import pytest
from fastapi import HTTPException
from app.services.integrations import derived_origin

MID = 'a' * 32
VALUE = {'adapter': 'generic', 'mode': 'isolated_proxy'}

def test_default_namespace_unchanged(monkeypatch):
    monkeypatch.delenv('STELLA_APP_ORIGIN_TEMPLATE', raising=False)
    assert derived_origin(MID, VALUE) == f'https://app-{MID}.xiya.live'

def test_exact_test_namespace(monkeypatch):
    monkeypatch.setenv('STELLA_APP_ORIGIN_TEMPLATE', 'https://app-dev-{id}.p.xiya.live')
    assert derived_origin(MID, VALUE) == f'https://app-dev-{MID}.p.xiya.live'

@pytest.mark.parametrize('template', [
    'http://app-{id}.example.test', 'https://app-{id}.example.test/path',
    'https://app-{id}.example.test?x=1', 'https://user:pass@app-{id}.example.test',
    'https://*.example.test', 'https://app.example.test',
    'https://app-{id}-{id}.example.test', 'https://app-{other}.example.test',
    'https://app-{id}.example.test:443', 'https://APP-{id}.example.test',
])
def test_invalid_template_fails_closed(monkeypatch, template):
    monkeypatch.setenv('STELLA_APP_ORIGIN_TEMPLATE', template)
    with pytest.raises(HTTPException) as error:
        derived_origin(MID, VALUE)
    assert error.value.status_code == 503

def test_existing_immich_canonical_identity_unchanged(monkeypatch):
    monkeypatch.setenv('STELLA_APP_ORIGIN_TEMPLATE', 'invalid')
    assert derived_origin(MID, {'adapter':'immich', 'mode':'isolated_proxy', 'browser_url':'https://immich.xiya.live/'}) == 'https://immich.xiya.live'
