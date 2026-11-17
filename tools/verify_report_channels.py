#!/usr/bin/env python3
"""Isolated channel acceptance. Does not deploy, install or access live services."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/Stella-监控第五轮-20261020/channels'
PY='/opt/hermes-workstation/stella-production-closure-20261017/.venv/bin/python'
NODE='/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
SCRATCH=Path('/root/.hermes/cache/scratch');OUT.mkdir(parents=True,exist_ok=True)
env={'PATH':str(Path(NODE).parent)+':/usr/bin:/bin','HOME':str(SCRATCH),'TMPDIR':str(SCRATCH),
     'PYTHONPATH':str(ROOT)+':'+str(ROOT/'tests_isolated'), 'DATABASE_URL':'sqlite://',
     'STELLA_SECRET_KEY':'isolated-channel-fixture-not-live-key-123456',
     'STELLA_HA_MODE':'primary-only','PLAYWRIGHT_BROWSERS_PATH':str(Path('/root/.cache/ms-playwright')),
     'STELLA_QA_OUTPUT':str(OUT/'browser')}
# Use the pre-existing browser cache; no download or package manager invocation.
if not Path(env['PLAYWRIGHT_BROWSERS_PATH']).exists():env.pop('PLAYWRIGHT_BROWSERS_PATH')
results=[]
changed=(subprocess.check_output(['git','diff','--name-only','-z','9004430fcca03407c42aa7b864ffb5c471518bcb'],cwd=ROOT)+subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT)).decode().split('\0')
source_paths=sorted({name for name in changed if name and not name.startswith('docs/') and Path(name).suffix in {'.py','.vue','.ts','.mjs'}})
before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_paths}
def run(name,argv,cwd,expected=0):
    result=subprocess.run(argv,cwd=cwd,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
    (OUT/(name+'.log')).write_text(result.stdout)
    results.append(dict(name=name,argv=argv,cwd=str(cwd),returncode=result.returncode,expected=expected))
    print(name,result.returncode,flush=True)
    return result

with tempfile.TemporaryDirectory(prefix='channels-acceptance-',dir=SCRATCH) as owned:
    suite=['test_report_channels.py','test_agent_channels.py','test_agent_channel_tls.py',
           'test_agent_release_continuity.py','test_agent_update.py','test_agent_scheduler.py',
           'test_entry_scope.py','test_machine_agent.py','test_hardware_agent.py']
    guard="""import socket,sys,pytest
original=socket.socket.connect
def connect(sock,address):
    if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1') or address[1] in (25436,24532,25451,12031):
        raise AssertionError('non-fixture network blocked')
    return original(sock,address)
socket.socket.connect=connect
raise SystemExit(pytest.main(sys.argv[1:]))
"""
    run('backend',[PY,'-c',guard,*[str(ROOT/'tests_isolated'/p) for p in suite],'-q','-s','--junitxml='+str(OUT/'backend.xml')],owned)
    run('compile',[PY,'-m','py_compile',str(ROOT/'agent/stella_agent.py'),str(ROOT/'app/services/agent_channels.py'),str(ROOT/'app/schemas/channel.py'),str(ROOT/'app/routers/monitor.py'),str(ROOT/'app/schemas/monitor.py')],owned)
    run('frontend-unit',[NODE,'node_modules/vitest/vitest.mjs','run','--config','vitest.channels.config.mjs'],ROOT/'frontend')
    run('frontend-types',[NODE,'node_modules/vue-tsc/bin/vue-tsc.js','-b'],ROOT/'frontend')
    run('frontend-build',[NODE,'node_modules/vite/bin/vite.js','build'],ROOT/'frontend')
    run('browser',[NODE,'e2e/report-channels.mjs'],ROOT/'frontend')
    # Existing reviewed fingerprints are intentionally NOT refreshed here.
    run('source-gate',[PY,str(ROOT/'tools/check_api_response_contracts.py'),'--require-complete'],owned,expected=1)

base=subprocess.check_output(['git','show','9004430fcca03407c42aa7b864ffb5c471518bcb:agent/stella_agent.py'],cwd=ROOT,text=True)
current=(ROOT/'agent/stella_agent.py').read_text()
def symbols(source):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(source)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a,b=symbols(base),symbols(current)
protected={name:a[name]==b[name] for name in ('_parse_entry_scope','_entry_ip_allowed','run_entry_probes')}
report={'commands':results,'isolated_env_keys':sorted(env),'protected_ast_unchanged':protected,
        'agent_version':'0.6.18','agent_sha256':hashlib.sha256(current.encode()).hexdigest(),
        'deployed':False,'live_config_changed':False,'global_source_hashes_refreshed':False}
report['tested_source_hashes']=before
report['tested_sources_unchanged']=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in before.items())
junit=ET.parse(OUT/'backend.xml').getroot()
report['pytest']={k:sum(int(s.get(k,'0')) for s in junit.iter('testsuite')) for k in ('tests','failures','errors','skipped')}
report['isolated_checks_passed']=all(r['returncode']==r['expected'] for r in results) and all(protected.values()) and report['tested_sources_unchanged']
report['release_gate_passed']=False
report['release_gate_pending']='Parent independent source/DTO review; existing reviewed hashes intentionally not refreshed.'
(OUT/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['isolated_checks_passed'] else 1)
