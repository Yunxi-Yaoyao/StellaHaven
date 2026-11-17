#!/usr/bin/env python3
"""Owned, frontend-only acceptance. No deployment/proxy/backend or Agent writes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/Stella-第八轮反馈-20261021/channels'
BASE = 'e143697c9e88433db006fadf667c869ebf46c408'
NODE = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
SCRATCH = Path('/root/.hermes/cache/scratch')
OUT.mkdir(parents=True, exist_ok=True)
protected = ['agent/stella_agent.py', 'frontend/src/App.vue', 'frontend/src/shell/Dropdown.vue', 'frontend/src/modules/home/auth.ts', 'frontend/src/modules/servers/AgentManager.vue', 'frontend/src/api/reportChannels.ts']
unchanged = {p: subprocess.check_output(['git', 'show', BASE + ':' + p], cwd=ROOT) == (ROOT / p).read_bytes() for p in protected}
source_names = ['frontend/src/modules/servers/ReportChannelManager.vue', 'frontend/src/modules/servers/channelInline.test.ts', 'frontend/src/modules/servers/reportChannels.test.ts', 'frontend/src/modules/servers/agentManagement.test.ts', 'frontend/src/modules/servers/agentManagementFix.test.ts', 'frontend/e2e/channel-inline.mjs', 'frontend/e2e/report-channels.mjs', 'frontend/vitest.channel-inline.config.mjs']
digests = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_names}
commands = []
with tempfile.TemporaryDirectory(prefix='channel-inline-v8-', dir=SCRATCH) as owned:
    env = {'PATH': str(Path(NODE).parent) + ':/usr/bin:/bin', 'HOME': owned, 'TMPDIR': str(SCRATCH), 'PLAYWRIGHT_BROWSERS_PATH': '/root/.cache/ms-playwright'}
    jobs = [
        ('unit', [NODE, 'node_modules/vitest/vitest.mjs', 'run', '--config', 'vitest.channel-inline.config.mjs', '--reporter=default', '--reporter=junit', '--outputFile=' + str(OUT / 'unit.xml')]),
        ('types', [NODE, 'node_modules/vue-tsc/bin/vue-tsc.js', '-b']),
        ('build', [NODE, 'node_modules/vite/bin/vite.js', 'build']),
        ('inline-browser', [NODE, 'e2e/channel-inline.mjs']),
        ('legacy-browser', [NODE, 'e2e/report-channels.mjs']),
    ]
    for name, argv in jobs:
        local = dict(env)
        if name.endswith('browser'):
            local['STELLA_QA_OUTPUT'] = str(OUT / name)
        proc = subprocess.run(argv, cwd=ROOT / 'frontend', env=local, capture_output=True, text=True, timeout=240)
        (OUT / (name + '.log')).write_text(proc.stdout + proc.stderr)
        commands.append({'name': name, 'argv': argv, 'cwd': str(ROOT / 'frontend'), 'returncode': proc.returncode})
        print(name, proc.returncode, flush=True)
    receipt = {'base': BASE, 'branch': 'fix/channel-inline-v8', 'kind': 'isolated frontend candidate + built actual App/router/shared CSS; synthetic API', 'commands': commands, 'environment_keys': sorted(env), 'source_sha256': digests, 'protected_unchanged': unchanged, 'deployed': False, 'installed': False, 'live_account_used': False, 'live_policy_changed': False, 'independent_review': 'pending parent review; do not merge/deploy on this receipt alone'}
    receipt['tested_sources_unchanged'] = all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in digests.items())
    xml = ET.parse(OUT / 'unit.xml').getroot()
    receipt['unit'] = {k: sum(int(s.get(k, '0')) for s in xml.iter('testsuite')) for k in ('tests', 'failures', 'errors', 'skipped')}
    inline = json.loads((OUT / 'inline-browser/browser-result.json').read_text())
    legacy = json.loads((OUT / 'legacy-browser/browser-result.json').read_text())
    receipt['browser'] = {'inline_result': inline['result'], 'inline_widths': [g['width'] for g in inline['geometry']], 'inline_screenshots': len(inline['screenshots']), 'inline_unknown': inline['unknown'], 'inline_errors': inline['errors'], 'legacy_unknown': legacy['unknown'], 'legacy_errors': legacy['errors'], 'inline_fixture_write_attempts': len(inline['writes']), 'inline_fixture_login_successes': inline['logins'], 'legacy_fixture_write_attempts': len(legacy['writes'])}
    receipt['passed'] = all(c['returncode'] == 0 for c in commands) and all(unchanged.values()) and receipt['tested_sources_unchanged'] and inline['result'] == 'passed'
    for name in ['channel-inline-red', 'channel-registry-red', 'channel-ack-red', 'channel-order-red', 'channel-prerequisite-red']:
        src = SCRATCH / (name + '.log')
        if src.exists(): shutil.copyfile(src, OUT / (name + '.log'))
    (OUT / 'RESULT.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    raise SystemExit(0 if receipt['passed'] else 1)
