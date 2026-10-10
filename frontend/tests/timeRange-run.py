#!/usr/bin/env python3
"""Run isolated frontend time tests; never inherit worker live routing."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
home = root / 'node_modules/.tmp/time-test-home'
home.mkdir(parents=True, exist_ok=True)
env = {k: v for k, v in os.environ.items() if not k.startswith(('HERMES_', 'MCP_')) and k != 'NODE_ENV'}
env.update(HOME=str(home), HERMES_HOME=str(home / '.hermes'), XDG_CACHE_HOME=str(home / 'cache'), TMPDIR=str(home))
print('Isolated test homes:', home, '; removed inherited HERMES_/MCP_ routing', flush=True)
node = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
args = sys.argv[1:]
if '--config' not in args:
    args = ['--config', 'vitest.time-range.config.mjs', *args]
sys.exit(subprocess.call([node, str(root / 'node_modules/vitest/vitest.mjs'), 'run', *args], cwd=root, env=env))
