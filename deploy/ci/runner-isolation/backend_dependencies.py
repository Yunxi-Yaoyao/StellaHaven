#!/usr/bin/env python3
"""Job-private backend APT: authenticated HTTPS, bounded download, offline resolver.

Keep the image's suites and Signed-By unchanged. Each invocation permits at most
240s of index/archive download (TUNA 150s, official remaining <=90s), then 120s
of --no-download installation. A failed prepare must stop before backend tests.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import time

PACKAGES = ['ffmpeg', 'sudo', 'nodejs', 'acl']
MIRRORS = ('https://mirrors.tuna.tsinghua.edu.cn', 'https://deb.debian.org')
SOURCES = Path('/etc/apt/sources.list.d/debian.sources')
VERSIONS = {'ffmpeg': ['ffmpeg', '-version'], 'sudo': ['sudo', '--version'],
            'nodejs': ['node', '--version'], 'acl': ['getfacl', '--version'],
            'npm': ['npm', '--version']}


def run(args, timeout):
    # subprocess.run(timeout=...) kills only apt-get, leaving acquire/dpkg
    # children alive with locks. Own a process group, kill it and reap apt first.
    with subprocess.Popen(args, start_new_session=True,
                          env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'}) as proc:
        try:
            result = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # The process group exited at the deadline.
            proc.wait()
            # Parent reaping is not a barrier for its descendants' file locks:
            # SIGKILL delivery and resource teardown can be scheduled later.
            deadline=time.monotonic()+1.0
            while True:
                live=False
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdigit():
                        continue
                    try:
                        fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    except (FileNotFoundError,ProcessLookupError,PermissionError):
                        continue
                    if int(fields[2])==proc.pid and fields[0] not in ('Z','X'):
                        live=True
                        break
                if not live:
                    break
                if time.monotonic()>=deadline:
                    raise RuntimeError('Timed-out subprocess group teardown unconfirmed')
                time.sleep(.01)
            raise
        if result:
            raise subprocess.CalledProcessError(result, args)


def apt(args, timeout):
    run(['apt-get', '-o', 'Acquire::Retries=0', '-o', 'Acquire::https::Timeout=15',
         '-o', 'Acquire::http::Timeout=15', '-o', 'APT::Update::Error-Mode=any',
         *args], timeout)


def preinstalled(packages):
    installed = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\\n', *packages],
                               capture_output=True, text=True, timeout=10)
    if installed.returncode or installed.stdout.splitlines() != ['installed'] * len(packages):
        return False
    try:
        for package in packages:
            if package in VERSIONS:
                run(VERSIONS[package], 10)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def prepare(directory, packages):
    original = SOURCES.read_text()
    deadline = time.monotonic() + 240
    cache = ['-o', 'Dir::Cache::archives=' + str(directory)]
    chosen = None
    try:
        for index, mirror in enumerate(MIRRORS):
            attempt = min(deadline, time.monotonic() + (150 if index == 0 else 90))
            text = original
            for host in ('http://deb.debian.org', 'https://deb.debian.org',
                         'https://mirrors.ustc.edu.cn', 'https://mirrors.tuna.tsinghua.edu.cn'):
                text = text.replace(host, mirror)
            SOURCES.write_text(text)
            try:
                for args in (['update'], [*cache, '--download-only', '--no-install-recommends', 'install', '-y', *packages]):
                    remaining = attempt - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired('apt-get', 0)
                    apt(args, remaining)
                chosen = mirror
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                print('Bounded backend dependency mirror failed: ' + mirror + ': ' + str(error), flush=True)
        if chosen is None:
            raise RuntimeError('all bounded backend dependency mirrors failed; tests must not start')
        # Preserve URI-keyed authenticated indexes until offline resolution.
        # Let apt order Pre-Depends; never dpkg -i sorted archives.
        apt([*cache, '--no-download', '--no-install-recommends', 'install', '-y', *packages], 120)
        if not preinstalled(packages):
            raise RuntimeError('backend dependencies not fully installed/usable; tests must not start')
        print(json.dumps({'prepared': True, 'mirror': chosen, 'packages': packages,
                          'offline_install': True, 'archives': len(list(directory.glob('*.deb')))}), flush=True)
    finally:
        SOURCES.write_text(original)


def playwright_packages():
    # Ask the installed lock-pinned Playwright for this image's dependency plan.
    # Parse only its known dry-run grammar; never execute the emitted shell.
    output = subprocess.check_output(['node', 'frontend/node_modules/playwright/cli.js',
                                      'install-deps', '--dry-run', 'chromium'], text=True, timeout=30)
    prefix = ['apt-get', 'update', '&&', 'apt-get', 'install', '-y', '--no-install-recommends']
    outer = shlex.split(output.strip())
    if len(outer) != 3 or outer[:2] != ['sh', '-c'] or '\n' in output.strip():
        raise ValueError('unexpected Playwright APT dry-run wrapper; tests must not start')
    lexer = shlex.shlex(outer[2], posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    words = list(lexer)
    packages = words[len(prefix):]
    if words[:len(prefix)] != prefix or not packages or any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', p) for p in packages):
        raise ValueError('unexpected Playwright APT dry-run plan; tests must not start')
    return packages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('backend', 'npm', 'playwright'))
    mode = parser.parse_args().mode
    packages = PACKAGES if mode == 'backend' else ['npm'] if mode == 'npm' else playwright_packages()
    if preinstalled(packages):
        print(json.dumps({'reused_preinstalled': True, 'packages': packages}), flush=True)
        return
    parent = Path(os.environ.get('TMPDIR', '/root/stella-ci-tmp'))
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ci-backend-deps-', dir=parent) as tmp:
        prepare(Path(tmp), packages)


if __name__ == '__main__':
    main()
