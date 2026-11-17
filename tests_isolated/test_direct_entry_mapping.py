"""Generic direct browser entry selection; no network or database."""
import json
import pytest
from fastapi import HTTPException
from app.services import entry_registry as registry
P='https://stella.xiya.live';L='https://stella.p.xiya.live'

def test_registered_direct_site_preserves_path_query_and_fragment(monkeypatch):
 monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':P,'private':L},{'service_id':'generic-site','public':'https://site.xiya.live','private':'https://site.p.xiya.live'}]))
 module={'id':'generic-site','browser_url':'https://site.xiya.live/path?q=one%20two#part'}
 assert registry.browser_url(module,L)=='https://site.p.xiya.live/path?q=one%20two#part'
 assert registry.browser_url(module,P)==module['browser_url']
 module['browser_url']='https://other.invalid/path'
 with pytest.raises(HTTPException):registry.browser_url(module,L)

def test_unregistered_public_only_site_is_explicitly_unchanged(monkeypatch):
 monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':P,'private':L}]))
 module={'id':'external','browser_url':'https://example.org/path'}
 assert registry.browser_url(module,L)==module['browser_url']
 with pytest.raises(HTTPException):registry.browser_url(module,'https://evil.invalid')
