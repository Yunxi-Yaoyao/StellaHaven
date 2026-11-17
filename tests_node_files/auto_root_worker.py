"""Test-only independent worker: fetched roots applied only inside fabricated /."""
# Sandbox.no_replace imports ctypes lazily; preload it before chroot removes
# access to the interpreter's stdlib/native-extension paths.
import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path
from agent.node_files import FileWorker, Sandbox

config = json.loads(Path(sys.argv[1]).read_text())
worker = FileWorker(config['url'], config['token'], Sandbox({}))
response = worker.client.get('/agent/files/config')
response.raise_for_status()
value = response.json()
assert value['enabled'] is True
assert value['roots'] == {'system':{'path':'/','write':True}}
# Prewarm HTTP/import machinery before the filesystem boundary; no queued work.
worker.tick()
worker.sandbox = Sandbox(value['roots'])
source = Path(sys.modules[FileWorker.__module__].__file__)
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
os.chroot(config['fabricated_root'])
os.chdir('/')
assert os.geteuid() == 0 and Path('/root').stat().st_mode & 0o777 == 0o700
assert not any(key.startswith('POSTGRES_') for key in os.environ)
worker.tick()  # Advertise fetched roots only AFTER entering fabricated /.
print(json.dumps({'event':'ready','pid':os.getpid(),'uid':os.geteuid(),'revision':value['revision'],'roots':value['roots'],'module_sha256':source_sha,'app_imported':any(key=='app' or key.startswith('app.') for key in sys.modules)}),flush=True)
for line in sys.stdin:
    if line.strip() == 'stop':
        break
    assert line.strip() == 'tick'
    worker.tick()
    print(json.dumps({'event':'tick'}),flush=True)
worker.client.close()
print(json.dumps({'event':'stopped'}),flush=True)
