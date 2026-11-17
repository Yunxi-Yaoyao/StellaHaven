"""Owned-network test child: exact FileWorker + production stdlib transport.

Unlike the resident child loop, deliberately fail on the FIRST exception with
its complete traceback. Contains only synthetic fixture credentials/paths.
"""
import json
import os
from pathlib import Path
import signal
import sys
import time

import importlib.abc


class NoHttpx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'httpx' or fullname.startswith('httpx.'):
            raise ModuleNotFoundError('owned stdlib-only fixture')
        return None


sys.meta_path.insert(0, NoHttpx())
from agent.node_files import FileWorker, Sandbox
from agent.stella_agent import _FileHTTPClient


def main():
    assert not any(k == 'app' or k.startswith('app.') for k in sys.modules)
    assert not any(k.startswith('POSTGRES_') for k in os.environ)
    assert 'httpx' not in sys.modules
    sandbox = Sandbox.from_env()
    assert sandbox.roots()
    assert all(Path(v['path']).is_relative_to(os.environ['TMPDIR']) for v in sandbox.allowed.values())
    spec = {'origin': os.environ['NODE_FILE_WORKER_URL'], 'token': os.environ['NODE_FILE_WORKER_TOKEN'], 'allow_loopback': True}
    worker = FileWorker(spec['origin'], spec['token'], sandbox, client=_FileHTTPClient(spec))
    stop = False
    def shutdown(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(json.dumps({'event': 'start', 'pid': os.getpid(), 'uid': os.geteuid(), 'app_imported': False, 'postgres_environment_present': False, 'httpx_imported': False}), flush=True)
    try:
        while not stop:
            worker.tick()  # No exception masking, no execution replay.
            time.sleep(.02)
    finally:
        worker.client.close()


if __name__ == '__main__':
    main()
