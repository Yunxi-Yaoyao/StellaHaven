"""Run in a fresh interpreter against a source-only scratch copy of main/app."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys


def test_main_lifecycle_router_default_off_no_first_backup(engine, tmp_path):
    root = Path(__file__).resolve().parents[1]
    copy = tmp_path / 'source'
    copy.mkdir()
    shutil.copytree(root / 'app', copy / 'app', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(root / 'main.py', copy / 'main.py')
    env = dict(os.environ, PYTHONPATH=str(copy))
    code = """
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
with TestClient(app, base_url='http://testserver') as client:
    assert hasattr(app.state, 'backup_center'), 'main lifecycle must start real backup center'
    center = app.state.backup_center
    assert center.timer.is_alive()
    assert center.status()['config']['enabled'] is False
    assert center.status()['records'] == []
    assert not (center.data_root / 'backups').exists()
    assert client.get('/operations/backups').status_code == 401
    response = client.post('/auth/register', json={'username':'main-backup-owner','password':'isolated-main-daily','display_name':'Main fixture'})
    assert response.status_code == 201, response.text
    assert client.get('/operations/backups').status_code == 200
    assert client.get('/operations/backups').json()['job'] is None
assert not center.timer.is_alive()
print('real full-main lifecycle and auth router default-off receipt')
"""
    result = subprocess.run([sys.executable, '-c', code], env=env, cwd=copy, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
