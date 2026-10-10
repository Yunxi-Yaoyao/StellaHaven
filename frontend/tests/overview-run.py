#!/usr/bin/env python3
"""Isolate overview tests and browser fixtures from inherited live routing."""
import os
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
home = Path('/root/.hermes/cache/scratch/overview-test-home')
home.mkdir(parents=True, exist_ok=True)
env = {k: v for k, v in os.environ.items() if not k.startswith(('HERMES_', 'MCP_')) and k != 'NODE_ENV'}
env.update(HOME=str(home), HERMES_HOME=str(home / '.hermes'), XDG_CACHE_HOME=str(home / 'cache'), TMPDIR=str(home))
print('Isolated overview test home:', home, '; inherited HERMES_/MCP_ routing removed', flush=True)
node = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
args = sys.argv[1:]
cmd = [node, str(root / 'tests/overview-browser.mjs')] if args == ['browser'] else [node, str(root / 'node_modules/vitest/vitest.mjs'), 'run', *(args or ['--config', 'vitest.overview.config.mjs'])]
sys.exit(subprocess.call(cmd, cwd=root, env=env))
