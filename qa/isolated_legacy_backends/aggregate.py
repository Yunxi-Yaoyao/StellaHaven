"""Reconcile exact historical IDs, final attempts, subtests and approval mapping."""
import ast,collections,hashlib,inspect,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
from control import OUT,OLD,REPO,ROOT

def digest_functions(path):
    source=path.read_text();lines=source.splitlines(keepends=True);result={}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            start=min([node.lineno]+[d.lineno for d in node.decorator_list])
            result[node.name]=hashlib.sha256(''.join(inspect.getblock(lines[start-1:])).encode()).hexdigest()
    return result

def collect(reports):
    records=[];subtests=[];junit=ET.Element('testsuites');declared=elements=0
    for path in reports:
        data=json.loads(path.read_text());events=collections.defaultdict(list)
        for event in data['events']:
            if event['subtest']:subtests.append(event)
            else:events[event['nodeid']].append(event)
        for row in data['collection']:
            sequence=events[row['nodeid']]
            failure=next((e for e in sequence if e['outcome']=='failed'),None)
            status=('failed' if failure['when']=='call' else 'error') if failure else ('skipped' if any(e['outcome']=='skipped' for e in sequence) else 'passed')
            if status=='passed':assert any(e['when']=='call' and e['outcome']=='passed' for e in sequence),row
            records.append({**row,'status':status,'report':path.name})
        tree=ET.parse(path.with_name(path.name.replace('-events.json','.xml'))).getroot()
        for suite in tree.iter('testsuite'):
            junit.append(suite);declared+=int(suite.get('tests','0'))
        elements+=sum(1 for _ in tree.iter('testcase'))
    return records,subtests,junit,declared,elements

def main():
    previous=json.loads((OUT.parent/'backend-coverage-close/final-case-inventory.json').read_text())
    baseline={r['original_id']:r for r in previous};assert len(baseline)==312
    reports=sorted(OUT.glob('final-*.py-events.json'));assert len(reports)==43
    records,subtests,junit,declared,elements=collect(reports)
    ids=[r['original_id'] for r in records]
    assert len(ids)==len(set(ids))==elements==312
    assert set(ids)==set(baseline),{'missing':sorted(set(baseline)-set(ids)),'extra':sorted(set(ids)-set(baseline))}
    successes=sum(e['outcome']=='passed' and e['when']=='call' for e in subtests)
    assert declared==elements+successes,(declared,elements,successes)
    mapping=[]
    for row in records:
        old=baseline[row['original_id']]
        row.update(previous_status=old['status'],previous_function_sha256=old['function_sha256'],approved_migration=old['status']!='passed')
        source=Path(row['function_file'])
        assert row['function_sha256'] in digest_functions(source).values(),row
        if source.is_relative_to(ROOT/'application'):
            assert source.read_bytes()==(REPO/source.relative_to(ROOT/'application')).read_bytes()
        if old['status']!='passed':
            mapping.append({'original_id':row['original_id'],'old_status':old['status'],'migration_reason':old['reason'],
                            'independent_current_contract':old['positive_contract'],'new_status':row['status'],
                            'old_function_sha256':old['function_sha256'],'new_function_sha256':row['function_sha256']})
    assert len(mapping)==11
    def blocks(source,names):
        lines=source.splitlines(keepends=True);result={}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
                start=min([node.lineno]+[d.lineno for d in node.decorator_list])
                result[node.name]=''.join(inspect.getblock(lines[start-1:]))
        return result
    for item in mapping:
        module,function=item['original_id'].split('::');function=function.split('[')[0]
        file=module.replace('.','/')+'.py'
        old_source=subprocess.run(['git','-C',str(REPO),'show','40f7332:'+file],capture_output=True,text=True,check=True).stdout
        item['old_assertion_source']=blocks(old_source,{function})
        item['new_assertion_source']=blocks((REPO/file).read_text(),{function,'_audit_roundtrip','_memory_roundtrip','legacy_audit_url','legacy_memory_engine'})
        if 'notes_zip_browser' in module:
            jsfile='frontend/tests/notes-zip-live.mjs'
            before=subprocess.run(['git','-C',str(REPO),'show','40f7332:'+jsfile],capture_output=True,text=True,check=True).stdout
            after=(REPO/jsfile).read_text()
            menu="await page.getByRole('button',{name:'更多',exact:true}).click();"
            assert after.replace(menu,'')==before
            item['browser_test_change']={'before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_sha256':hashlib.sha256(after.encode()).hexdigest(),'only_change':menu,'original_assertions_byte_preserved':True}

    # Keep the original opt-in 97 and formerly unrun 27 files separately visible.
    gaps=json.loads((OUT/'initial-gap-inventory.json').read_text())
    pg_ids={c['id'] for c in gaps['prior_nonpassed'] if c['status']=='skipped'};assert len(pg_ids)==97
    unrun={f[:-3].replace('/','.') for f in gaps['unrun_files']};assert len(unrun)==27
    grouped=lambda rs:dict(collections.Counter(r['status'] for r in rs))
    targeted=[r for r in records if not r['original_id'].startswith('qa.')]
    positive=[r for r in records if r['original_id'].startswith('qa.')]
    # Full owning reruns and guard proofs are NOT added again to the 312 collection.
    guard_reports=sorted(OUT.glob('guard-acceptance-*.py-events.json'))
    owning_reports=sorted(OUT.glob('owning-*.py-events.json'))
    extra={}
    for name,paths in [('guard_acceptance',guard_reports),('modified_owning_suites',owning_reports)]:
        rows,subs,xml,total,els=collect(paths)
        extra[name]={'case_events':len(rows),'unique_ids':len({r['original_id'] for r in rows}),'statuses':grouped(rows),'junit_declared':total,'junit_elements':els,'successful_subtests':sum(e['outcome']=='passed' and e['when']=='call' for e in subs),'reports':[p.name for p in paths]}
        ET.ElementTree(xml).write(OUT/(name+'.xml'),encoding='utf-8',xml_declaration=True)
    attempts=[]
    for p in sorted(OUT.glob('*.py-events.json')):
        data=json.loads(p.read_text())
        attempts.append({'report':p.name,'final_selected':p in reports,'collected':len(data['collection']),'successful_subtests':sum(e['subtest'] and e['when']=='call' and e['outcome']=='passed' for e in data['events']),'exitstatus':data['exitstatus']})
    summary={'source_base':'40f7332e760d84c8a3edd599850b947c3fd1ea3a','suite_processes':len(reports),
             'final_main_cases':len(records),'final_statuses':grouped(records),'original_cases':len(targeted),'original_statuses':grouped(targeted),
             'independent_positive_cases':len(positive),'independent_positive_statuses':grouped(positive),
             'pg_optin_original_cases':len(pg_ids),'pg_optin_statuses':grouped([r for r in records if r['original_id'] in pg_ids]),
             'original_27_files':sorted(gaps['unrun_files']),'original_27_statuses':grouped([r for r in records if r['original_id'].split('::')[0] in unrun]),
             'junit_declared':declared,'junit_elements':elements,'successful_subtests':successes,'approved_migrations':len(mapping),
             'exact_previous_id_set_preserved':True,'attempt_receipts':len(attempts),'attempt_collection_events':sum(a['collected'] for a in attempts),**extra,
             'scope':'Tests/QA only; historical 162 subtests and unrelated frontend/whole-app suites not rerun.'}
    for name,value in [('SUMMARY.json',summary),('final-case-inventory.json',records),('original-new-assertion-mapping.json',mapping),('attempt-inventory.json',attempts)]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    harness=[json.loads(p.with_name(p.name.replace('-events.json','-harness.json')).read_text()) for p in reports+guard_reports+owning_reports]
    (OUT/'guard-chain.json').write_text(json.dumps(harness,indent=2))
    ET.ElementTree(junit).write(OUT/'final-selected-junit.xml',encoding='utf-8',xml_declaration=True)
    print(json.dumps(summary,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
