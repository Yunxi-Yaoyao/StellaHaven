"""Bounded lane evidence, using private deps and a disposable policy database."""
from pathlib import Path
import subprocess,os,json
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/Stella-追加修正-20261019/live-test-nodes';OUT.mkdir(parents=True,exist_ok=True)
PY='/opt/hermes-workstation/stella-preview-20261018/.venv/bin/python'
NODE='/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
commands=[('policy-tests',ROOT,[PY,'deploy/fixtures/live_test_nodes/verify_policy_pg.py']),
 ('fixture-tests',ROOT,[PY,'-m','unittest','discover','-s','deploy/fixtures/live_test_nodes','-p','test_*.py','-v']),
 ('frontend-tests',ROOT/'frontend',[NODE,'node_modules/vitest/vitest.mjs','run','--config','vitest.node-policy.config.mjs']),
 ('frontend-types',ROOT/'frontend',[NODE,'node_modules/vue-tsc/bin/vue-tsc.js','-b']),
 ('frontend-build',ROOT/'frontend',[NODE,'node_modules/vite/bin/vite.js','build'])]
results=[]
for name,cwd,argv in commands:
 env=dict(os.environ);env.pop('NODE_ENV',None)
 r=subprocess.run(argv,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
 (OUT/(name+'.log')).write_text(r.stdout)
 results.append({'name':name,'argv':argv,'returncode':r.returncode})
 print(name,r.returncode)
(OUT/'tests.json').write_text(json.dumps(results,indent=2)+'\n')
assert all(r['returncode']==0 for r in results)
