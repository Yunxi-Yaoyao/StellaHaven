"""Exact initial gap inventory and original-function hashes (no collection side effects)."""
import ast,hashlib,json
from control import REPO,ROOT,OUT,OLD
prior=json.loads((OLD/'backend-final-inventory.json').read_text())
cases=[dict(c,suite=s['file']) for s in prior['suites'] for c in s['cases'] if c['status']!='passed']
files=set(json.loads((OLD/'fixture-scope-audit.json').read_text())['tests_not_run'])|{'tests/test_alerts.py','tests/test_external_services_unit.py'}
for c in cases:
 name=c['id'].split('::')[0].split('.');p='/'.join(name[:2])+'.py'
 if (REPO/p).exists():files.add(p)
functions=[]
for file in sorted(files):
 raw=(REPO/file).read_bytes();copied=(ROOT/'application'/file).read_bytes();assert raw==copied
 text=raw.decode();tree=ast.parse(text);lines=text.splitlines(keepends=True)
 for n in ast.walk(tree):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
   start=min([n.lineno]+[d.lineno for d in n.decorator_list]);body=''.join(lines[start-1:n.end_lineno])
   functions.append(dict(file=file,name=n.name,start=start,end=n.end_lineno,sha256=hashlib.sha256(body.encode()).hexdigest(),file_sha256=hashlib.sha256(raw).hexdigest()))
(OUT/'original-function-hashes.json').write_text(json.dumps(functions,indent=2))
(OUT/'initial-gap-inventory.json').write_text(json.dumps(dict(prior_nonpassed=cases,unrun_files=json.loads((OLD/'fixture-scope-audit.json').read_text())['tests_not_run'],prior_skips=sum(c['status']=='skipped' for c in cases),prior_setup_errors=2,prior_collection_errors=1,attempt_inventory=json.loads((OLD/'attempt-inventory.json').read_text()),note='97 skips are all PG opt-in; no Windows/device cases in this exact gap inventory. Original source and assertions unchanged.'),indent=2))
print(len(files),'files',len(functions),'function hashes;',sum(c['status']=='skipped' for c in cases),'prior skips')
