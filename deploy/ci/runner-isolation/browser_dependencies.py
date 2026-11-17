#!/usr/bin/env python3
"""Bounded job-private browser prewarm on the unchanged CI172 Node image.

Reuse exact preinstalled tools. Otherwise apt authenticates and downloads the
complete closure once, then its resolver installs from that cache offline.
No shared cache, host package install, new image or runner boundary change.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

CHROMIUM = '156.0.8078.47-1~deb12u1'
MIRRORS = ('https://mirrors.tuna.tsinghua.edu.cn', 'https://deb.debian.org')
MODES = {
    'frontend': ['chromium=' + CHROMIUM, 'chromium-common=' + CHROMIUM],
    'experience': ['chromium=' + CHROMIUM, 'chromium-common=' + CHROMIUM,
                   'ffmpeg', 'python3', 'python3-pil', 'git', 'nginx', 'openssl'],
}
SOURCES = Path('/etc/apt/sources.list.d/debian.sources')


def apt(args, timeout):
    subprocess.run(['apt-get', '-o', 'Acquire::Retries=0', '-o', 'Acquire::https::Timeout=15',
                    '-o', 'APT::Update::Error-Mode=any', *args], check=True, timeout=timeout,
                   env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})


def preinstalled(packages):
    browser = subprocess.run(['dpkg-query', '-W', '-f=${Version}', 'chromium'], capture_output=True, text=True)
    if browser.returncode != 0 or not browser.stdout.strip():
        return False
    if browser.stdout.strip() != CHROMIUM:
        raise ValueError('preinstalled Chromium version drift')
    names = [p.split('=')[0] for p in packages]
    installed = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\\n', *names], capture_output=True, text=True)
    return installed.returncode == 0 and installed.stdout.splitlines() == ['installed'] * len(names)


def prepare(directory, packages):
    original = SOURCES.read_text()
    deadline = time.monotonic() + 240
    cache = ['-o', 'Dir::Cache::archives=' + str(directory)]
    chosen = None
    try:
        for index, mirror in enumerate(MIRRORS):
            attempt = min(deadline, time.monotonic() + 150) if index == 0 else deadline
            text = original
            for host in ('http://deb.debian.org', 'https://deb.debian.org',
                         'https://mirrors.ustc.edu.cn', 'https://mirrors.tuna.tsinghua.edu.cn'):
                text = text.replace(host, mirror)
            SOURCES.write_text(text)
            try:
                for args in (['update'],
                             [*cache, '--download-only', '--no-install-recommends', 'install', '-y', *packages]):
                    remaining = attempt - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired('apt-get', 0)
                    apt(args, remaining)
                chosen = mirror
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                print('Bounded dependency mirror failed: ' + mirror + ': ' + str(error), flush=True)
        if chosen is None:
            raise RuntimeError('all bounded dependency mirrors failed; tests must not start')
        # Keep the selected source URI until its authenticated index has resolved
        # the offline install. Restoring it earlier hides the URI-keyed apt index.
        # Do not call dpkg on sorted archives: systemd-sysv has Pre-Depends.
        apt([*cache, '--no-download', '--no-install-recommends', 'install', '-y', *packages], 120)
        installed = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'chromium'], text=True).strip()
        if installed != CHROMIUM:
            raise ValueError('installed Chromium version drift')
        print(json.dumps({'prepared': True, 'mirror': chosen, 'chromium_version': installed,
                          'offline_install': True, 'archives': len(list(directory.glob('*.deb')))}))
    finally:
        SOURCES.write_text(original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=MODES)
    packages = MODES[parser.parse_args().mode]
    if preinstalled(packages):
        print(json.dumps({'reused_preinstalled': True, 'chromium_version': CHROMIUM}))
        return
    parent = Path(os.environ.get('TMPDIR', '/root/stella-browser-ci-tmp'))
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='ci-browser-deps-', dir=parent))
    prepare(directory, packages)


if __name__ == '__main__':
    main()
