"""Run isolated website projection suites; never inherit live service routing.

Usage: /path/to/test/venv/bin/python tests_public_website/run.py [pytest args]
Default suites: public projections, generic templates, website settings.
No PG opt-in, external DNS or non-loopback socket connections are permitted.
"""
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def child():
    assert Path.cwd() != ROOT and not Path('.env').exists()
    assert 'STELLA_GENERIC_TEST_PG' not in os.environ
    original_dns = socket.getaddrinfo
    original_connect = socket.socket.connect

    def dns(host, *args, **kwargs):
        if host not in {'localhost', '127.0.0.1', '::1', b'localhost', b'127.0.0.1', b'::1'}:
            raise socket.gaierror('isolated website tests forbid external DNS')
        return original_dns(host, *args, **kwargs)

    def connect(sock, address):
        if isinstance(address, tuple) and not ipaddress.ip_address(address[0]).is_loopback:
            raise AssertionError('isolated website tests forbid non-loopback connections')
        return original_connect(sock, address)

    socket.getaddrinfo = dns
    socket.socket.connect = connect
    import pytest
    tests = [str(ROOT / p) for p in ('tests_public_website', 'tests_generic_templates', 'tests_website_settings')]
    print('ISOLATION: explicit child env; scratch cwd/HOME; external DNS/connect denied; no PG opt-in', flush=True)
    return pytest.main(['--noconftest', '-p', 'no:cacheprovider', '-q', *tests, *sys.argv[1:]])


def main():
    if os.environ.get('STELLA_PUBLIC_WEBSITE_TEST_CHILD') == '1':
        return child()
    scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
    scratch.mkdir(parents=True, exist_ok=True)
    node = shutil.which('node')
    path = (str(Path(node).resolve().parent) + ':' if node else '') + os.defpath
    with tempfile.TemporaryDirectory(prefix='website-projection-', dir=scratch) as home:
        env = dict(PATH=path, HOME=home, TMPDIR=home, PYTHONPATH=str(ROOT),
                   PYTHONDONTWRITEBYTECODE='1', STELLA_PUBLIC_WEBSITE_TEST_CHILD='1')
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
                              cwd=home, env=env, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
