"""Bounded ACL refusal/draft control on unchanged native Vue, no response mocks."""
import hashlib
import json
import os
import sys
from pathlib import Path
import subprocess

from test_acl import dropped_read, setup_file, snapshot


def test_native_acl_refusal_retains_draft(system):
    s = system
    repo = Path(__file__).resolve().parents[1]
    evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
    dependencies = repo / 'frontend/node_modules'
    assert (dependencies / 'vite/dist/node/index.js').is_file(), 'reuse existing environment only'
    path = setup_file(s['root'])
    before = snapshot(path)
    assert dropped_read(s['root'])['returncode'] != 0
    scratch = s['root'].parent
    config = scratch / 'acl-browser-private.json'
    config.write_text(json.dumps({'repo': str(repo), 'dependencies': str(dependencies), 'scratch': str(scratch),
                                  'root': str(s['root']), 'backend': s['url'],
                                  'cookie': s['client'].cookies.get('stella_at'), 'evidence': str(evidence)}))
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'PYTHONPATH')}
    env.update({'NODE_FILE_WORKER_URL': s['url'], 'NODE_FILE_WORKER_TOKEN': s['token'],
                'STELLA_FILE_ROOTS': json.dumps({'fixture': {'path': str(s['root']), 'write': True}}),
                'PYTHONDONTWRITEBYTECODE': '1'})
    original_plain = (s['root'] / 'hello.txt').read_bytes()
    worker = subprocess.Popen([sys.executable, str(repo / 'tests_node_files/worker.py')],
                              env=env, cwd=scratch, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        result = subprocess.run([os.environ.get('STELLA_CI_NODE', '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'),
                                 str(repo / 'tests_node_files/acl_browser.mjs'), str(config)],
                                cwd=scratch, env={**os.environ, 'NODE_ENV': ''}, capture_output=True, text=True, timeout=90)
        (evidence / 'acl-browser.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        assert snapshot(path) == before
        assert dropped_read(s['root'])['returncode'] != 0
        assert worker.poll() is None
    finally:
        worker.terminate()
        output, errors = worker.communicate(timeout=15)
        # This positive-control edit belongs only to this case, not the later
        # independent preview journey sharing the session-owned fixture.
        (s['root'] / 'hello.txt').write_bytes(original_plain)
        (evidence / 'acl-independent-worker.log').write_text(output + errors)
        assert worker.returncode == 0, output + errors
        events = [json.loads(line) for line in output.splitlines()]
        assert not events[0]['app_imported'] and not events[0]['postgres_environment_present']
        assert events[0]['module_sha256'] == hashlib.sha256((repo / 'agent/node_files.py').read_bytes()).hexdigest()
        assert events[-1]['event'] == 'stop'
        assert not any(x['event'] == 'worker_error' for x in events)
