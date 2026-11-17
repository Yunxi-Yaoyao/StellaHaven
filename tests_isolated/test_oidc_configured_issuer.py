"""Configured identity is independent of browser entry; offline exact-host guards."""
import json
import pytest
from tests_isolated.test_oidc_pool_security import offline_modules
from tests_isolated.test_oidc_provider import oidc, api

ISSUER = 'https://stella-dev.p.xiya.live'
ALT = 'https://stella-alt-dev.p.xiya.live'


def configure(monkeypatch):
    monkeypatch.setenv('STELLA_OIDC_ISSUER', ISSUER)
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id': 'stella', 'public': ISSUER, 'private': ALT}]))


def test_configured_issuer_is_stable_for_both_exact_entries(oidc, monkeypatch):
    configure(monkeypatch)
    for host in (ISSUER[8:], ALT[8:]):
        assert oidc.resolve_issuer(host) == ISSUER


@pytest.mark.parametrize('value', ['', 'http://stella-dev.p.xiya.live', ISSUER+'/',
    ISSUER+'/oidc', ISSUER+'?x=1', 'https://user@stella-dev.p.xiya.live',
    ISSUER+':443', 'https://*.p.xiya.live'])
def test_malformed_explicit_issuer_fails_closed(oidc, monkeypatch, value):
    from fastapi import HTTPException
    configure(monkeypatch)
    monkeypatch.setenv('STELLA_OIDC_ISSUER', value)
    with pytest.raises(HTTPException) as error:
        oidc.resolve_issuer(ISSUER[8:])
    assert error.value.status_code == 503


@pytest.mark.parametrize('host', ['evil.test', 'stella.xiya.live', ISSUER[8:]+':443', ISSUER[8:]+'.evil.test'])
def test_configured_identity_does_not_trust_unregistered_host(oidc, monkeypatch, host):
    from fastapi import HTTPException
    configure(monkeypatch)
    with pytest.raises(HTTPException) as error:
        oidc.resolve_issuer(host)
    assert error.value.status_code == 421


def test_unset_config_preserves_production_compatibility(oidc, monkeypatch):
    monkeypatch.delenv('STELLA_OIDC_ISSUER', raising=False)
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id':'stella','public':'https://stella.xiya.live','private':'https://stella-private.test'}]))
    assert oidc.resolve_issuer('stella.xiya.live') == 'https://stella.xiya.live'
    assert oidc.resolve_issuer('stella.yunxi.life') == 'https://stella.yunxi.life'
    assert oidc.resolve_issuer('stella-private.test') == 'https://stella.xiya.live'


def test_http_discovery_ignores_forwarded_identity(api, oidc, monkeypatch):
    configure(monkeypatch)
    for host in (ISSUER[8:], ALT[8:]):
        response = api.client.get('/.well-known/openid-configuration', headers={
            'host':host, 'x-forwarded-host':'evil.test', 'forwarded':'host=evil.test;proto=http'})
        assert response.status_code == 200
        assert response.json() == oidc.openid_configuration(ISSUER)
    assert api.client.get('/.well-known/openid-configuration', headers={
        'host':'evil.test','x-forwarded-host':ISSUER[8:]}).status_code == 421
