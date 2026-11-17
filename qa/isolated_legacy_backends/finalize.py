"""Verify approved test-only edits, immutable product, owned cleanup and secrets."""
import hashlib,json,os,shutil,socket,subprocess
from datetime import datetime,timezone
from pathlib import Path
from control import REPO,ROOT,OUT,STATE,PY,inspect,save

def main():
    summary=json.loads((OUT/'SUMMARY.json').read_text())
    assert summary['final_main_cases']==312 and summary['exact_previous_id_set_preserved']
    baseline_receipt='full-run-source-before.json' if (OUT/'full-run-source-before.json').exists() else 'source-before.json'
    before=json.loads((OUT/baseline_receipt).read_text())
    overlay=json.loads((OUT/'test-overlay.json').read_text())
    allowed={'frontend/tests/notes-zip-live.mjs','tests/test_attachments.py','tests/test_attachments_pg.py',
             'tests/test_drafts.py','tests/test_trash.py','tests_ha/test_shared_state.py',
             'tests_isolated/test_operations_audit_pg.py','tests_isolated/test_system_memory_roundtrip.py'}
    assert set(overlay)==allowed
    after={f:hashlib.sha256((REPO/f).read_bytes()).hexdigest() for f in before}
    changed={f for f in before if before[f]!=after[f]}
    assert changed==allowed,changed
    for file in allowed:
        assert after[file]==overlay[file]
        assert (ROOT/'application'/file).read_bytes()==(REPO/file).read_bytes()
    unchanged=set(before)-allowed
    for file in unchanged:
        archived=ROOT/'application'/file
        assert archived.is_file() and hashlib.sha256(archived.read_bytes()).hexdigest()==before[file],file
    assert not (ROOT/'application/.env').exists()
    s=json.loads(STATE.read_text());inspect(s)
    namespace=os.readlink(f'/proc/{s["pid"]}/ns/net');processes=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if os.readlink(p/'ns/net')==namespace:
                processes.append({'pid':int(p.name),'name':(p/'comm').read_text().strip()})
        except (FileNotFoundError,PermissionError,ProcessLookupError):pass
    assert all(p['name']=='postgres' for p in processes),processes
    screenshots=[]
    for p in (ROOT/'tmp').rglob('stella-notes-live-*.png'):
        dest=OUT/'screenshots'/p.relative_to(ROOT/'tmp');dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest);screenshots.append(str(dest.relative_to(OUT)))
    screenshots=sorted({*screenshots,*[str(p.relative_to(OUT)) for p in (OUT/'screenshots').rglob('*.png')]})
    redacted=[]
    for p in OUT.rglob('*'):
        if p.is_file() and p.suffix in {'.json','.jsonl','.xml','.log','.md'}:
            text=p.read_text()
            if s['password'] in text:
                p.write_text(text.replace(s['password'],'[owned-credential-redacted]'));redacted.append(str(p.relative_to(OUT)))
    subprocess.run([PY,str(REPO/'qa/isolated_legacy_backends/control.py'),'cleanup'],check=True)
    removed=[]
    for p in [ROOT/'tmp',ROOT/'home',ROOT/'application/data',ROOT/'data']:
        if p.exists():
            assert p.is_relative_to(ROOT) and not p.is_symlink()
            shutil.rmtree(p);removed.append(str(p))
    survivors=[]
    for base in (ROOT,OUT):
        for p in base.rglob('*'):
            if p.is_file() and not p.is_symlink():
                try:
                    if s['password'].encode() in p.read_bytes():survivors.append(str(p))
                except OSError:pass
    assert not survivors,survivors
    with socket.socket() as sock:
        sock.settimeout(.5);port_closed=sock.connect_ex(('127.0.0.1',s['port']))!=0
    assert port_closed and not STATE.exists()
    save('verification-final.json',{'verified_at':datetime.now(timezone.utc).isoformat(),
         'source_base':summary['source_base'],'baseline_source_receipt':baseline_receipt,'baseline_tracked_files':len(before),
         'untouched_tracked_files':len(unchanged),'approved_test_files':sorted(allowed),
         'archive_and_worktree_test_hashes_match':True,'all_other_archived_files_match_baseline':True,
         'owned_namespace_processes_before_removal':processes,'screenshots_preserved':screenshots,
         'redacted_artifacts':redacted,'owned_scratch_secret_directories_removed':removed,
         'random_db_secret_survivors':survivors,'host_pg_port_closed':port_closed,'private_state_absent':True,
         'product_edits':False,'production_guard_edits':False,'approved_assertion_migrations':11})
    save('source-after.json',after)
    print('Approved diff, unchanged product, exact owned cleanup and credential absence verified')
if __name__=='__main__':main()
