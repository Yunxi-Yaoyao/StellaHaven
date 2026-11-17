"""Independent synthetic-node process: actual production FileWorker, no app/DB.

Only started by the owned netns harness. Token and local root grants are supplied
through its private environment, never command arguments or production defaults.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.parse import urlsplit
from agent import node_files


def main():
    assert not any(key == 'app' or key.startswith('app.') for key in sys.modules)
    assert not any(key.startswith('POSTGRES_') for key in os.environ)
    url = os.environ['NODE_FILE_WORKER_URL']
    assert urlsplit(url).hostname == '127.0.0.1'
    sandbox = node_files.Sandbox.from_env()
    assert sandbox.roots() and all(Path(value['path']).is_relative_to(os.environ['TMPDIR']) for value in sandbox.allowed.values())
    print(json.dumps({'event': 'start', 'pid': os.getpid(), 'python': sys.executable, 'module_sha256': hashlib.sha256(Path(node_files.__file__).read_bytes()).hexdigest(), 'app_imported': False, 'postgres_environment_present': False}), flush=True)
    stop = False
    def shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    worker = node_files.FileWorker(url, os.environ['NODE_FILE_WORKER_TOKEN'], sandbox)
    ticks = 0
    try:
        while not stop:
            try:
                worker.tick()
                ticks += 1
            except Exception as exc:
                print(json.dumps({'event': 'worker_error', 'kind': type(exc).__name__}), flush=True)
            time.sleep(.08)
    finally:
        worker.client.close()
        print(json.dumps({'event': 'stop', 'pid': os.getpid(), 'ticks': ticks}), flush=True)


if __name__ == '__main__':
    main()
