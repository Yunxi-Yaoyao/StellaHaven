"""Pure guards for target admission and preference fields."""
import json
import pytest
from qa.native_nav_pg_guard import target

@pytest.mark.parametrize('port', ['24532', '5432', '25436'])
def test_refuse_production_ports(monkeypatch, port):
    monkeypatch.setenv('POSTGRES_PORT', port)
    with pytest.raises(AssertionError): target()


def test_refuse_missing_nonce(monkeypatch):
    monkeypatch.setenv('POSTGRES_PORT', '33070')
    monkeypatch.setenv('POSTGRES_DB', 'navqa')
    monkeypatch.setenv('POSTGRES_USER', 'navqa')
    monkeypatch.delenv('NAV_PG_NONCE', raising=False)
    with pytest.raises(AssertionError): target()
