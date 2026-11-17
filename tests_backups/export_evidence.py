"""Export only public test evidence, never fixture secrets or backups."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('fixture_root',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    fixture=args.fixture_root.resolve()
    cleanup=json.loads((fixture/'cleanup.json').read_text())
    assert cleanup['exact_container_absent'] and cleanup['private_receipt_removed']
    output=root/'docs/backup-center/evidence'
    output.mkdir(parents=True,exist_ok=True)
    allowed=sorted(fixture.glob('run-*.log'))+sorted(fixture.glob('*.xml'))
    allowed += [fixture/name for name in ('cleanup.json','streaming-budget.json','pg-roundtrip.json','settings-roundtrip.json')]
    for source in allowed:
        assert source.parent==fixture and source.is_file() and not source.is_symlink()
        shutil.copy2(source,output/source.name)
    tree=ET.parse(output/'final-handoff.xml')
    cases=tree.findall('.//testcase')
    names=[case.attrib.get('classname','')+'::'+case.attrib['name'] for case in cases]
    suites=tree.findall('.//testsuite')
    declared=sum(int(s.attrib['tests']) for s in suites)
    assert declared==len(cases)==len(set(names))
    assert not tree.findall('.//failure') and not tree.findall('.//error') and not tree.findall('.//skipped')
    source_paths=[root/'Dockerfile',root/'main.py',root/'tools/backup_restore.py',root/'app/routers/backups.py',root/'app/schemas/backups.py']
    source_paths+=sorted(root.glob('app/services/backup_*.py'))+sorted(root.glob('tests_backups/*.py'))
    sources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    scans=[]
    for path in source_paths:
        if path.suffix!='.py':continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Call) and (any(k.arg=='shell' and isinstance(k.value,ast.Constant) and k.value.value is True for k in node.keywords)
                or isinstance(node.func,ast.Name) and node.func.id in ('eval','exec')
                or isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and
                   (node.func.value.id,node.func.attr) in (('os','system'),('pickle','load'),('pickle','loads'))):
                scans.append({'path':str(path.relative_to(root)),'line':node.lineno})
    assert not scans
    versions=[]
    for log in sorted(output.glob('run-*.log')):
        for line in log.read_text().splitlines():
            try:obj=json.loads(line)
            except ValueError:continue
            if isinstance(obj,dict) and {'python','pg_dump','pg_restore','postgres','external_egress_blocked'}<=set(obj):versions.append(obj)
    assert versions and versions[-1]['external_egress_blocked']
    evidence={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file() and p.name!='manifest.json'}
    value={'baseline':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
           'tests':{'declared':declared,'unique_cases':len(names),'failed':0,'skipped':0,'case_ids':names},
           'runtime':versions[-1]|{'network':'none','shared_environment_modified':False},
           'static_dangerous_call_findings':scans,'source_sha256':sources,'evidence_sha256':evidence,
           'limits':['No Docker image build/deploy','No real Patroni failover','No frontend storage sync/browser acceptance','No legacy file/shared-state backup support','No production Alembic/main-suite claim']}
    (output/'manifest.json').write_text(json.dumps(value,indent=2,ensure_ascii=False))
    print(json.dumps({'directory':str(output),'logs':len(list(output.glob('run-*.log'))),'test_cases':len(names),'sources':len(sources),'evidence_files':len(evidence)}))


if __name__=='__main__':main()
