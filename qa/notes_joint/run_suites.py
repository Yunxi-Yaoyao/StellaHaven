import os,sys,subprocess,shutil,json
from pathlib import Path
R=Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e');A=R/'application';O=Path('/opt/hermes-workstation/docs/Stella-API/remediation');Q=Path(__file__).resolve().parent
E={k:os.environ[k] for k in ['PATH','TZ','LANG'] if k in os.environ};E.update(HOME=str(R/'home'),TMPDIR=str(R/'tmp'),PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',STELLA_BLOB_STORAGE='postgres')
P='/opt/Yunxi-workstation/Stella/.venv/bin/python'
shutil.copy2(O/'review-lifecycle-harness/test_review_lifecycle.py',A/'tests_isolated/test_review_lifecycle.py')
shutil.copy2(Q/'test_independent_corrections.py',A/'tests_isolated/test_independent_corrections.py')
results=[]
def run(name,args,cwd=A):
    with (O/f'review-notes-joint-{name}.log').open('w') as f:r=subprocess.run(args,cwd=cwd,env=E,stdout=f,stderr=subprocess.STDOUT)
    results.append(dict(suite=name,exit=r.returncode));(O/'review-notes-joint-suites.json').write_text(json.dumps(results,indent=2));print(name,r.returncode,flush=True)
run('original-red',[P,'-m','pytest','--noconftest','-q','tests_isolated/test_review_lifecycle.py','--junitxml='+str(O/'review-notes-joint-original-red.xml')])
run('http',[P,'-m','pytest','--noconftest','-q','tests_isolated/test_independent_corrections.py','tests_isolated/test_notes_review_boundaries.py','tests_isolated/test_notes_lifecycle_http.py','tests_isolated/test_api_tag_contract.py','tests_isolated/test_api_draft_contract.py','--junitxml='+str(O/'review-notes-joint-http.xml')])
run('standalone',[P,'-m','pytest','--noconftest','-q','tests_isolated/test_notes_lifecycle.py','--junitxml='+str(O/'review-notes-joint-standalone.xml')])
# Scratch launcher preserves test functions/guards, adds required resource caps.
p=A/'tests_isolated/run_notes_boundary_pg.py';t=p.read_text();p.write_text(t.replace("'--publish', '127.0.0.1::5432'","'--memory', '768m', '--cpus', '1', '--publish', '127.0.0.1::5432'"))
run('boundary-pg',[P,'-I',str(p),'--run-disposable-postgres','--receipt='+str(O/'review-notes-joint-boundary-resource.json'),'--junitxml='+str(O/'review-notes-joint-boundary-pg.xml'),'-s'])
F=A/'frontend'
run('mounted',['node','node_modules/vitest/vitest.mjs','run','--config','vitest.notes-upgrade.config.mjs','--reporter=junit','--outputFile='+str(O/'review-notes-joint-mounted.xml')],F)
run('full-frontend',['node','node_modules/vitest/vitest.mjs','run','--config','vitest.full.config.mjs','--reporter=junit','--outputFile='+str(O/'review-notes-joint-full-frontend.xml')],F)
run('proxy',['node','notes-recovery-dev-proxy.mjs'],F)
