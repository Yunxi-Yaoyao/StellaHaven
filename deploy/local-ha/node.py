#!/usr/bin/env python3
"""Operator-installed read-only agent; no unguarded compose up/DB mutation."""
import json
from pathlib import Path
import subprocess
import sys
from release import Refused, SCOPE, image_ref


def compose(config, *args):
    if args != ('ps', '-q', 'app'):
        raise Refused('only read-only compose inspection is implemented')
    return subprocess.run(['docker', 'compose', '--env-file', config['env_file'],
                           '-f', config['compose_file'], *args], check=True,
                          text=True, capture_output=True, timeout=15).stdout.strip()


def probe(config):
    if config.get('scope') != SCOPE or config.get('environment') != 'nonproduction':
        raise Refused('explicit isolated nonproduction inventory required')
    if config.get('node') not in ('nyarch', 'nas'):
        raise Refused('invalid node identity')
    container = compose(config, 'ps', '-q', 'app')
    if not container or '\n' in container:
        raise Refused('exactly one running app container required')
    inspected = json.loads(subprocess.run(['docker', 'inspect', container], check=True,
                           text=True, capture_output=True, timeout=15).stdout)[0]
    labels = inspected['Config'].get('Labels', {})
    if labels.get('com.docker.compose.project') != 'stella-local-ha-' + config['node']:
        raise Refused('container is not in the isolated project')
    image = image_ref(inspected['Config']['Image'])
    result = subprocess.run(['docker', 'exec', container, '/app/.venv/bin/python',
                             '/local-ha/readiness.py'], check=True, text=True,
                            capture_output=True, timeout=20)
    report = json.loads(result.stdout)
    if report.get('name') != config['node']:
        raise Refused('container node identity mismatch')
    report['image'] = image
    return report


def update_app(config, image, expected_image):
    image_ref(image)
    image_ref(expected_image)
    state = probe(config)
    if state.get('name') != config.get('node') or (state['primary_http'], state['in_recovery'], state['read_only']) != (503, True, True):
        raise Refused('app update must target the current standby')
    # Role checks cannot fence a node: do not pretend a boolean grants safety.
    raise Refused('app writes disabled: hardware fencing acceptance and release locking unavailable')


if __name__ == '__main__':
    try:
        request = json.loads(sys.stdin.read(8192))
        if request != {'op': 'probe'}:
            raise Refused('only read-only probe requests accepted')
        config = json.loads(Path('/etc/stella-local-ha/node.json').read_text())
        print(json.dumps(probe(config)))
    except Exception as exc:
        print(json.dumps({'status': 'refused', 'error': type(exc).__name__}), file=sys.stderr)
        raise SystemExit(2)
