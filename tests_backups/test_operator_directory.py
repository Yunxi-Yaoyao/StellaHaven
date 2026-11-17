"""Operator default storage is separate from the read-only resource bundle."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest


def test_explicit_operator_directory_keeps_resource_root_separate_and_default_off(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    resources = tmp_path / 'immutable-resources'
    resources.mkdir()
    (resources / 'manifest.json').write_text('{"files":{}}')
    destination = tmp_path / 'persistent' / 'backups'
    center = BackupCenter(engine, resources, key=b'fixture', default_directory=destination)
    assert center.directory({'directory':''}) == destination
    status = center.status()
    assert status['config']['directory'] == '' and status['config']['enabled'] is False
    assert status['storage']['can_initialize_default'] is True
    assert not destination.exists() and not (resources / 'backups').exists()
    center.submit('backup', 'settings')
    center.wait()
    state = center.status()
    assert state['job']['state'] == 'succeeded'
    assert len(state['records']) == 1
    assert destination.exists() and not (resources / 'backups').exists()
    assert (resources / 'manifest.json').read_text() == '{"files":{}}'


@pytest.mark.parametrize('path',['relative/backups','/','/a/../backups','/path\nprivate','/a//backups'])
def test_operator_default_rejects_noncanonical_unsafe_directory_before_io(engine, tmp_path, path):
    from app.services.backup_center import BackupCenter
    with pytest.raises(ValueError):
        BackupCenter(engine, tmp_path / 'resources', key=b'fixture', default_directory=path)
    assert not (tmp_path / 'resources').exists()


def test_main_uses_explicit_operator_default_without_redirecting_backup_source_root(engine, tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / 'source'
    source.mkdir()
    shutil.copytree(root / 'app', source / 'app', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(root / 'main.py', source / 'main.py')
    resources = tmp_path / 'resources'
    target = tmp_path / 'node-local' / 'backups'
    env = dict(os.environ, PYTHONPATH=str(source), STELLA_BACKUP_DATA_ROOT=str(resources),
               STELLA_BACKUP_DIRECTORY=str(target))
    code = '''
import os
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
with TestClient(app, base_url='http://testserver'):
    center=app.state.backup_center
    assert center.data_root == Path(os.environ['STELLA_BACKUP_DATA_ROOT'])
    assert center.directory({'directory':''}) == Path(os.environ['STELLA_BACKUP_DIRECTORY'])
    assert center.status()['config']['enabled'] is False
    assert not center.directory({'directory':''}).exists()
    assert not (center.data_root/'backups').exists()
assert not center.timer.is_alive()
'''
    p = subprocess.run([sys.executable,'-c',code],cwd=source,env=env,capture_output=True,text=True,timeout=30)
    assert p.returncode == 0,p.stdout+p.stderr
