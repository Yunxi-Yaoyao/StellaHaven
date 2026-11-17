"""Serialized subprocess runs; preserve every attempt without adding duplicates."""
import json,subprocess,sys,time
from control import ROOT,OUT,OLD,PY,REPO
label=sys.argv[1];files=sys.argv[2:]
if files==['main']:
 files=json.loads((OLD/'fixture-scope-audit.json').read_text())['tests_not_run']+['tests/test_alerts.py']
if files==['all']:
 gaps=json.loads((OUT/'initial-gap-inventory.json').read_text())
 files=sorted(set(gaps['unrun_files']+['tests/test_alerts.py','tests/test_external_services_unit.py']+['/'.join(c['id'].split('::')[0].split('.')[:2])+'.py' for c in gaps['prior_nonpassed'] if c['status']=='skipped']))
 files+=['qa/isolated_legacy_backends/test_current_contracts.py','qa/isolated_legacy_backends/test_owned_pg_equivalents.py','qa/isolated_legacy_backends/test_current_browser_contract.py']
for file in files:
 log=OUT/(label+'-'+file.replace('/','_')+'.log')
 with log.open('w') as f:
  try:r=subprocess.run([PY,str(REPO/'qa/isolated_legacy_backends/control.py'),'run',file,label],stdout=f,stderr=subprocess.STDOUT,timeout=300);rc=r.returncode
  except subprocess.TimeoutExpired:rc='timeout'
 with (OUT/'attempts.jsonl').open('a') as f:f.write(json.dumps(dict(file=file,label=label,exitcode=rc,log=str(log)))+'\n')
 print(file,rc,flush=True)
