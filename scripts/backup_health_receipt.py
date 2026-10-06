#!/usr/bin/env python3
"""Hash an existing private dump and run pg_restore --list; never restore/connect/write DB.

Emits a sanitized receipt to stdout. Store stdout in a deployment-owned receipt
folder (read-only mount into Stella). A dump-list check NEVER verifies restore.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


def make_receipt(dump: Path, expected_sha256: str, pg_container: str | None = None):
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise ValueError('expected SHA-256 must be lowercase hex')
    if dump.is_symlink() or not dump.is_file():
        raise ValueError('dump must be a regular non-symlink file')
    sha = hashlib.sha256()
    with dump.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            sha.update(block)
    matched = sha.hexdigest() == expected_sha256
    command = ['pg_restore', '--list']
    if pg_container:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', pg_container):
            raise ValueError('invalid container identifier')
        command = ['docker', 'exec', '-i', pg_container, 'pg_restore', '--list']
    list_verified = False
    if matched:
        with dump.open('rb') as file:
            result = subprocess.run(command, stdin=file, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=120, check=False)
        list_verified = result.returncode == 0
    return {'timestamp': datetime.fromtimestamp(dump.stat().st_mtime, timezone.utc).isoformat(),
            'status': 'verified' if matched and list_verified else 'failed',
            'checksumverified': matched, 'restoreverified': False, 'source': 'postgres-dump',
            'dump_list_verified': list_verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--pg-container', help='Existing container holding pg_restore (no container creation)')
    args = parser.parse_args()
    try:
        receipt = make_receipt(args.dump, args.expected_sha256, args.pg_container)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(1, 'Backup evidence verification failed (private details suppressed).\n')
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['status'] == 'verified' else 1
if __name__ == '__main__':
    raise SystemExit(main())
