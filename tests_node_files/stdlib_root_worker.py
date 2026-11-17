"""Stdlib-only variant of the owned automatic-root HTTP/PG worker."""
import ctypes  # Preload before fabricated chroot, as the original harness does.
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys
import uuid  # Sandbox.write_stream lazily imports this after fabricated chroot.


class NoHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'httpx' or fullname.startswith('httpx.'):
            raise ModuleNotFoundError('owned stdlib-only fixture')
        return None


sys.meta_path.insert(0, NoHttpx())
from agent.node_files import FileWorker, Sandbox
from agent.stella_agent import _FileHTTPClient

config = json.loads(Path(sys.argv[1]).read_text())
client = _FileHTTPClient({'origin': config['url'], 'token': config['token'], 'allow_loopback': True})
worker = FileWorker(config['url'], config['token'], Sandbox({}), client=client)
response = client.get('/agent/files/config')
response.raise_for_status()
value = response.json()
assert value['enabled'] is True
assert value['roots'] == {'system': {'path': '/', 'write': True}}
worker.tick()
worker.sandbox = Sandbox(value['roots'])
source = Path(sys.modules[FileWorker.__module__].__file__)
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
os.chroot(config['fabricated_root'])
os.chdir('/')
assert os.geteuid() == 0 and Path('/root').stat().st_mode & 0o777 == 0o700
assert not any(key.startswith('POSTGRES_') for key in os.environ)
assert 'httpx' not in sys.modules
worker.tick()
print(json.dumps({'event': 'ready', 'pid': os.getpid(), 'uid': os.geteuid(), 'revision': value['revision'], 'roots': value['roots'], 'module_sha256': source_sha, 'app_imported': any(key == 'app' or key.startswith('app.') for key in sys.modules)}), flush=True)
for line in sys.stdin:
    if line.strip() == 'stop':
        break
    assert line.strip() == 'tick'
    worker.tick()  # First native exception escapes with complete traceback.
    print(json.dumps({'event': 'tick'}), flush=True)
client.close()
print(json.dumps({'event': 'stopped'}), flush=True)
