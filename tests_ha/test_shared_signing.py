import importlib.util
import os
from pathlib import Path
import pytest


def load_security(tmp_path,monkeypatch):
    source=Path(__file__).parents[1]/'app/security.py'
    # Use a copied module so legacy key creation can only touch test tmp files.
    target=tmp_path/'repo/app/security.py';target.parent.mkdir(parents=True)
    target.write_text(source.read_text())
    spec=importlib.util.spec_from_file_location('isolated_security',target)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ha_missing_signing_secret_refuses_start(tmp_path,monkeypatch):
    monkeypatch.setenv('STELLA_HA_MODE','primary-only')
    monkeypatch.delenv('STELLA_SECRET_KEY',raising=False)
    with pytest.raises(RuntimeError,match='signing'):
        load_security(tmp_path,monkeypatch)


def test_ha_uses_supplied_shared_signing_secret(tmp_path,monkeypatch):
    monkeypatch.setenv('STELLA_HA_MODE','primary-only')
    monkeypatch.setenv('STELLA_SECRET_KEY','synthetic-shared-key-for-tests-only-1234567890')
    m=load_security(tmp_path,monkeypatch)
    assert m.SECRET_KEY=='synthetic-shared-key-for-tests-only-1234567890'
    assert not (tmp_path/'data/secret_key').exists()
