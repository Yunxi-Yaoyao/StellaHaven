"""Read exact runtime schema and aggregate case IDs, never sum overlapping suites."""
import json,hashlib,io,tarfile,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import httpx
R=Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e');O=Path('/opt/hermes-workstation/docs/Stella-API/remediation');REPO=Path('/opt/hermes-workstation/stella-notes-final-joint-20261016')
s=json.loads((R/'private.json').read_text());url='http://127.0.0.1:'+str(s['http_port'])
r=httpx.get(url+'/openapi.json',timeout=20,trust_env=False);assert r.status_code==200;schema=r.json();(O/'review-notes-joint-runtime-openapi.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2))
policies=[]
for path,method in [('/documents/delete-preview','post'),('/documents/{doc_id}','delete'),('/documents/{doc_id}/permanent','delete'),('/documents/trash/empty','post'),('/notes-preferences','get'),('/notes-preferences','patch')]:
    op=schema['paths'][path][method];assert op['x-stella-auth-type']=='cookie-access' and op['x-stella-elevation']=='none';assert op['security']==[{'StellaAccessCookie':[]}]
    policies.append(dict(method=method,path=path,auth=op['x-stella-auth-type'],elevation=op['x-stella-elevation'],response_status=op.get('x-stella-contract-status')))
assert schema['paths']['/documents/{doc_id}/restore']['post']['x-stella-elevation']=='management-policy'
(O/'review-notes-joint-runtime-policy.json').write_text(json.dumps(policies,indent=2))
results=[]
for name in ['original-red','original-kwargs-only','http','standalone','boundary-pg','live-http','mounted','full-frontend','browser']:
    p=O/f'review-notes-joint-{name}.xml';root=ET.parse(p).getroot();cases=list(root.iter('testcase'));suites=[x for x in root.iter('testsuite') if not list(x.iter('testsuite'))[1:]]
    failures=[dict(name=c.get('name'),class_name=c.get('classname'),message=(c.find('failure').get('message','') if c.find('failure') is not None else c.find('error').get('message',''))) for c in cases if c.find('failure') is not None or c.find('error') is not None]
    skips=sum(c.find('skipped') is not None for c in cases);declared=sum(int(x.get('tests','0')) for x in suites)
    results.append(dict(suite=name,cases=len(cases),declared_reports=declared,passed=len(cases)-len(failures)-skips,failed=len(failures),skipped=skips,failures=failures,case_ids=[c.get('classname','')+'::'+c.get('name','') for c in cases]))
archive=subprocess.run(['git','-C',str(REPO),'archive','6b01e8e7714b7cd87c425ae71cb74ca3df956a65'],check=True,capture_output=True).stdout
hashes={};drift=[]
with tarfile.open(fileobj=io.BytesIO(archive)) as t:
    for member in t:
        if not member.isfile():continue
        data=t.extractfile(member).read();current=(REPO/member.name).read_bytes();a=hashlib.sha256(data).hexdigest();b=hashlib.sha256(current).hexdigest();hashes[member.name]=b
        if a!=b:drift.append(member.name)
assert not drift
contract=json.loads((O/'review-notes-joint-contract/response-contracts-coverage.json').read_text())
summary=dict(head=s['head'],product_tracked_files=len(hashes),product_drift=drift,hashes=hashes,suites=results,scope='Independent fixed-HEAD Notes F1-F9, real production dist / Chromium / Uvicorn / disposable PG, supplemental original fixture and source-shaped gates',contract={k:contract[k] for k in ['operation_count','classification','normalization_complete','source_and_classification_gate_passed','errors']},runtime_policy=policies)
(O/'review-notes-joint.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps([dict(suite=x['suite'],cases=x['cases'],reports=x['declared_reports'],passed=x['passed'],failed=x['failed'],skipped=x['skipped'],failed_names=[f['name'] for f in x['failures']]) for x in results],ensure_ascii=False,indent=2));print('source hashes matched',len(hashes))
