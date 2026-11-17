import importlib.util
from pathlib import Path
import pytest


def cli():
    path=Path(__file__).resolve().parents[1]/'tools/backup_restore.py'
    spec=importlib.util.spec_from_file_location('isolated_backup_cli',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_restore_publication_never_overwrites_existing_empty_directory(tmp_path):
    module=cli()
    source=tmp_path/'stage';source.mkdir();(source/'secret').write_bytes(b'restored')
    target=tmp_path/'existing';target.mkdir()
    inode=target.stat().st_ino
    with pytest.raises(FileExistsError): module.publish_directory(source,target)
    assert target.stat().st_ino==inode and list(target.iterdir())==[]
    assert (source/'secret').read_bytes()==b'restored'
    target.rmdir()
    module.publish_directory(source,target)
    assert (target/'secret').read_bytes()==b'restored' and not source.exists()


def test_maintenance_confirmation_rejects_before_connect_or_file_io(tmp_path,monkeypatch):
    from types import SimpleNamespace
    module=cli()
    def forbidden(*a,**k): raise AssertionError('must not open target')
    monkeypatch.setattr(module.psycopg2,'connect',forbidden)
    args=SimpleNamespace(maintenance=False,confirm_target='wrong',host='127.0.0.1',port=5432,database='never-live')
    with pytest.raises(ValueError): module.restore(args)
    args.maintenance=True
    with pytest.raises(ValueError): module.restore(args)
